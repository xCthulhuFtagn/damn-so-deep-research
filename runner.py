import threading
import logging
import time
import re
from typing import Optional, Dict

from agents import Runner, Agent, RunConfig, ModelSettings
from agents.exceptions import ModelBehaviorError
from agents.models.interface import Model, ModelProvider
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI, BadRequestError

from config import MAX_TURNS, OPENAI_API_KEY, OPENAI_BASE_URL, MAX_RETRIES, MODEL
from database import db_service
from db_session import DBSession
from research_agents import get_agent_by_name, planner_agent, executor_agent, reporter_agent
from utils.context import current_run_id, current_user_id

logger = logging.getLogger(__name__)

class VLLMChatCompletionsProvider(ModelProvider):
    def __init__(self, base_url: str, api_key: str, default_model: str):
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._default_model = default_model

        # Wrap the create method to track tokens
        original_create = self._client.chat.completions.create
        
        async def tracking_create(*args, **kwargs):
            response = await original_create(*args, **kwargs)
            
            # Sanitize tool calls to fix <|channel|>commentary suffix issue
            try:
                if response and response.choices:
                    for choice in response.choices:
                        if choice.message and choice.message.tool_calls:
                            for tool_call in choice.message.tool_calls:
                                if tool_call.function and tool_call.function.name:
                                    original_name = tool_call.function.name
                                    # Strip <|channel|> and anything after
                                    if "<|channel|>" in original_name:
                                        clean_name = original_name.split("<|channel|>")[0]
                                        logger.warning(f"Sanitizing tool name: '{original_name}' -> '{clean_name}'")
                                        tool_call.function.name = clean_name
            except Exception as e:
                logger.error(f"Failed to sanitize tool calls: {e}")

            try:
                if response and response.usage:
                    run_id = current_run_id.get()
                    if run_id:
                        db_service.increment_token_usage(run_id, response.usage.total_tokens)
            except Exception as e:
                logger.error(f"Failed to track tokens: {e}")
            return response
            
        self._client.chat.completions.create = tracking_create

    def get_model(self, model_name: str | None) -> Model:
        return OpenAIChatCompletionsModel(model=model_name or self._default_model, openai_client=self._client)

class SwarmRunner:
    def __init__(self):
        self.active_runs: Dict[str, threading.Thread] = {}

    def run_in_background(self, run_id: str, user_id: str, start_agent: Agent, input_text: str, max_turns: int = MAX_TURNS):
        if db_service.is_swarm_running(run_id):
            logger.warning("Swarm is already running for run_id=%s.", run_id)
            return

        db_service.set_swarm_running(run_id, True)
        
        thread = threading.Thread(
            target=self._run_wrapper,
            args=(run_id, user_id, start_agent, input_text, max_turns),
            daemon=True
        )
        self.active_runs[run_id] = thread
        thread.start()
        logger.info("Swarm background thread started for run_id=%s with max_turns=%d", run_id, max_turns)

    def _run_wrapper(self, run_id: str, user_id: str, start_agent: Agent, input_text: str, max_turns: int):
        token_run = current_run_id.set(run_id)
        token_user = current_user_id.set(user_id)
        
        try:
            run_config = RunConfig(
                model_provider=VLLMChatCompletionsProvider(
                    api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL, default_model=MODEL
                ),
                tracing_disabled=True,
            )

            current_agent = start_agent
            current_input = input_text
            
            if current_agent.name == "Planner":
                logger.info("=== PHASE 1: PLANNING for run %s ===", run_id)
                session = DBSession(f"planner_{run_id}")
                _execute_phase(run_id, current_agent, current_input, session, max_turns, run_config)
                
                if db_service.should_pause(run_id):
                    logger.info("Pause signal received after Phase 1 for run %s", run_id)
                    return

                current_agent = executor_agent
                current_input = "[INTERNAL SYSTEM NOTIFICATION]: Plan created. Begin execution."

            if current_agent.name in ["Executor", "Evaluator", "Strategist"]:
                logger.info("=== PHASE 2: EXECUTION for run %s ===", run_id)
                session = DBSession(f"research_{run_id}")
                
                while not db_service.should_pause(run_id):
                    next_step = db_service.get_next_step(run_id)
                    if not next_step:
                        logger.info("No more steps for run_id=%s. Execution Phase Complete.", run_id)
                        break
                    
                    # ISOLATION: Explicitly set active task so DBSession filters messages correctly
                    db_service.set_active_task(run_id, next_step['step_number'])
                    
                    # UI UPDATE: Mark step as IN_PROGRESS
                    db_service.update_step_status(next_step['id'], "IN_PROGRESS")
                    
                    logger.info(f"Executing Step {next_step['step_number']} for run {run_id}: {next_step['description']}")
                    step_input = f"Execute Step {next_step['step_number']}: {next_step['description']}"
                    
                    try:
                        _execute_phase(run_id, executor_agent, step_input, session, max_turns, run_config)
                    except Exception as e:
                        logger.error(f"Step {next_step['step_number']} for run {run_id} failed: {e}")
                        
                        # Fix: Ensure we mark the ACTUALLY failed step, not the stale next_step from loop start
                        failed_step_id = next_step['id']
                        active_task_num = db_service.get_active_task(run_id)
                        if active_task_num and active_task_num != next_step['step_number']:
                            logger.warning(f"Run {run_id}: Error occurred in step {active_task_num}, but loop was at {next_step['step_number']}. Finding correct step ID.")
                            plan_df = db_service.get_all_plan(run_id)
                            row = plan_df[plan_df['step_number'] == active_task_num]
                            if not row.empty:
                                failed_step_id = int(row.iloc[0]['id'])
                        
                        db_service.update_step_status(failed_step_id, "FAILED", f"System Error: {e}")
                
                if db_service.should_pause(run_id):
                    logger.info("Pause signal received during/after Phase 2 for run %s", run_id)
                    return

                current_agent = reporter_agent
                current_input = "[INTERNAL SYSTEM NOTIFICATION]: All steps completed. Generate the final report."

            if current_agent.name == "Reporter":
                logger.info("=== PHASE 3: REPORTING for run %s ===", run_id)
                session = DBSession(f"reporter_{run_id}")
                _execute_phase(run_id, current_agent, current_input, session, max_turns, run_config)
                # Mark run as completed after Reporter finishes
                db_service.update_run_status(run_id, 'completed')
                logger.info("Run %s marked as completed", run_id)

        except Exception as e:
            logger.exception("Error in swarm background thread for run %s: %s", run_id, e)
            db_service.save_message(run_id, "system", f"Runner Error: {e}")
        finally:
            db_service.set_swarm_running(run_id, False)
            if run_id in self.active_runs:
                del self.active_runs[run_id]
            current_run_id.reset(token_run)
            current_user_id.reset(token_user)
            logger.info("Swarm background thread finished for run_id=%s", run_id)

def _execute_phase(run_id: str, agent: Agent, input_text: str, session: DBSession, max_turns: int, run_config: RunConfig):
    retry_count = 0
    current_input = input_text

    while retry_count <= MAX_RETRIES:
        if db_service.should_pause(run_id):
            logger.warning("Pause signal received for run %s during phase execution.", run_id)
            return

        try:
            logger.info("Runner: agent=%s, session=%s, run_id=%s", agent.name, session.session_id, run_id)
            Runner.run_sync(agent, input=current_input, session=session, max_turns=max_turns, run_config=run_config)
            
            # Strict tool enforcement: Check last assistant message
            messages = db_service.load_messages(run_id)
            # Find the last assistant message for this session
            last_assistant = None
            for msg in reversed(messages):
                if msg.role == "assistant" and msg.session_id == session.session_id:
                    last_assistant = msg
                    break
            
            if last_assistant:
                # Use sender if available (more accurate for handoffs), otherwise fallback to agent.name
                effective_agent_name = last_assistant.sender or agent.name
                
                # Only enforce for non-Reporter/Planner/Evaluator agents
                if effective_agent_name not in ["Reporter", "Planner", "Evaluator"]:
                    has_content = last_assistant.content and last_assistant.content.strip()
                    has_tool_calls = last_assistant.tool_calls and len(last_assistant.tool_calls) > 0
                    
                    # # Violation: No content and no tool calls
                    # if not has_content and not has_tool_calls:
                    #     error_msg = f"Strict mode violation: Agent {effective_agent_name} returned an empty response. It MUST call a tool."
                    #     logger.warning(error_msg)
                    #     raise ModelBehaviorError(error_msg)

                    # Violation: Has content but no tool calls
                    if has_content and not has_tool_calls:
                        # CHECK EXCEPTION: If the previous assistant message was a valid completion tool, ignore this chatter.
                        # We need to look back one more step in history, or check if ANY recent message was a completion.
                        # Since we re-load messages, let's check the last few.
                        is_completed = False
                        for m in reversed(messages[-5:]): # Check last 5 messages
                            if m.role == "assistant" and m.tool_calls:
                                for tc in m.tool_calls:
                                    if isinstance(tc, dict):
                                        fname = tc.get('function', {}).get('name')
                                        if fname in ["submit_step_result", "mark_step_failed", "insert_corrective_steps"]:
                                            is_completed = True
                                            break
                            if is_completed: break
                        
                        if is_completed:
                            logger.info(f"Ignoring strict mode violation for {effective_agent_name} because step is completed/failed.")
                            return
                            
                        error_msg = f"Strict mode violation: Agent {effective_agent_name} output text without calling a tool. Text: {last_assistant.content[:200]}"
                        logger.warning(error_msg)
                        raise ModelBehaviorError(error_msg)

            
            return
        except (ModelBehaviorError, BadRequestError) as e:
            retry_count += 1
            error_msg = str(e)
            short_error = error_msg[:500] + "..." if len(error_msg) > 500 else error_msg
            logger.warning("API/Model Error (attempt %s) for run %s: %s", retry_count, run_id, short_error)
            db_service.save_message(run_id, "system", f"System Feedback: {short_error}", session_id=session.session_id)
            current_input = "[INTERNAL SYSTEM NOTIFICATION]: An error occurred. Please review the feedback and continue."
        except Exception as e:
            retry_count += 1
            err_msg = str(e)
            short_err = err_msg[:500] + "..." if len(err_msg) > 500 else err_msg
            logger.exception("Generic error in phase (attempt %s) for run %s: %s", retry_count, run_id, short_err)
            db_service.save_message(run_id, "system", f"System Error: {short_err}", session_id=session.session_id)
            current_input = "[INTERNAL SYSTEM NOTIFICATION]: An internal error occurred. Please try to recover."
            time.sleep(2)

    raise RuntimeError(f"Swarm execution failed for run {run_id} after {MAX_RETRIES} retries.")

runner = SwarmRunner()