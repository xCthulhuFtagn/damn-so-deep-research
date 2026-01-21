import threading
import asyncio
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
from research_agents import executor_agent, reporter_agent, evaluator_agent, strategist_agent, planner_agent
from utils.context import current_run_id, current_user_id

logger = logging.getLogger(__name__)

AGENT_MAP = {
    "Executor": executor_agent,
    "Evaluator": evaluator_agent,
    "Strategist": strategist_agent,
    "Planner": planner_agent,
    "Reporter": reporter_agent
}

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
                        # Token tracking - wrap в asyncio для async DB call
                        asyncio.create_task(db_service.increment_token_usage(run_id, response.usage.total_tokens))
            except Exception as e:
                logger.error(f"Failed to track tokens: {e}")
            return response
            
        self._client.chat.completions.create = tracking_create

    def get_model(self, model_name: str | None) -> Model:
        return OpenAIChatCompletionsModel(model=model_name or self._default_model, openai_client=self._client)

class SwarmRunner:
    def __init__(self):
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def run_in_background(self, run_id: str, user_id: str, start_agent: Agent, input_text: str, max_turns: int = MAX_TURNS):
        # Get or create event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop - create one for Streamlit
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                # Start loop in background thread
                threading.Thread(target=self._loop.run_forever, daemon=True).start()
            loop = self._loop

        # Create async task
        coro = self._run_wrapper_async(run_id, user_id, start_agent, input_text, max_turns)
        
        try:
            # Check if we are running in the same loop (unlikely for Streamlit)
            if asyncio.get_running_loop() == loop:
                task = loop.create_task(coro)
                self.active_tasks[run_id] = task
            else:
                # We are in a different thread, use threadsafe scheduling
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                self.active_tasks[run_id] = future
        except RuntimeError:
            # get_running_loop raises RuntimeError if no loop is running in current thread
            # This confirms we are in a sync thread (Streamlit)
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            self.active_tasks[run_id] = future

        logger.info("Swarm async task started for run_id=%s with max_turns=%d", run_id, max_turns)

    async def _run_wrapper_async(self, run_id: str, user_id: str, start_agent: Agent, input_text: str, max_turns: int):
        token_run = current_run_id.set(run_id)
        token_user = current_user_id.set(user_id)

        try:
            # Explicitly mark swarm as running
            await db_service.set_swarm_running(run_id, True)
            
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
                await _execute_phase_async(run_id, current_agent, current_input, session, max_turns, run_config)

                if await db_service.should_pause(run_id):
                    logger.info("Pause signal received after Phase 1 for run %s", run_id)
                    return

                current_agent = executor_agent
                current_input = "[INTERNAL SYSTEM NOTIFICATION]: Plan created. Begin execution."

            if current_agent.name in ["Executor", "Evaluator", "Strategist"]:
                logger.info("=== PHASE 2: EXECUTION for run %s ===", run_id)
                session = DBSession(f"research_{run_id}")

                while not await db_service.should_pause(run_id):
                    next_step = await db_service.get_next_step(run_id)
                    if not next_step:
                        logger.info("No more steps for run_id=%s. Execution Phase Complete.", run_id)
                        break

                    # ISOLATION: Explicitly set active task so DBSession filters messages correctly
                    await db_service.set_active_task(run_id, next_step['step_number'])

                    # UI UPDATE: Mark step as IN_PROGRESS
                    await db_service.update_step_status(next_step['id'], "IN_PROGRESS")

                    logger.info(f"Executing Step {next_step['step_number']} for run {run_id}: {next_step['description']}")
                    step_input = f"Execute Step {next_step['step_number']}: {next_step['description']}"

                    try:
                        await _execute_phase_async(run_id, executor_agent, step_input, session, max_turns, run_config)
                    except Exception as e:
                        logger.error(f"Step {next_step['step_number']} for run {run_id} failed: {e}")

                        # Fix: Ensure we mark the ACTUALLY failed step
                        failed_step_id = next_step['id']
                        active_task_num = await db_service.get_active_task(run_id)
                        if active_task_num and active_task_num != next_step['step_number']:
                            logger.warning(f"Run {run_id}: Error occurred in step {active_task_num}, but loop was at {next_step['step_number']}. Finding correct step ID.")
                            plan_df = await db_service.get_all_plan(run_id)
                            row = plan_df[plan_df['step_number'] == active_task_num]
                            if not row.empty:
                                failed_step_id = int(row.iloc[0]['id'])

                        await db_service.update_step_status(failed_step_id, "FAILED", f"System Error: {e}")

                if await db_service.should_pause(run_id):
                    logger.info("Pause signal received during/after Phase 2 for run %s", run_id)
                    return

                current_agent = reporter_agent
                current_input = "[INTERNAL SYSTEM NOTIFICATION]: All steps completed. Generate the final report."

            if current_agent.name == "Reporter":
                logger.info("=== PHASE 3: REPORTING for run %s ===", run_id)
                session = DBSession(f"reporter_{run_id}")
                await _execute_phase_async(run_id, current_agent, current_input, session, max_turns, run_config)
                # Mark run as completed after Reporter finishes
                await db_service.update_run_status(run_id, 'completed')
                logger.info("Run %s marked as completed", run_id)

        except Exception as e:
            logger.exception("Error in swarm async task for run %s: %s", run_id, e)
            await db_service.save_message(run_id, "system", f"Runner Error: {e}")
        finally:
            await db_service.set_swarm_running(run_id, False)
            if run_id in self.active_tasks:
                del self.active_tasks[run_id]
            current_run_id.reset(token_run)
            current_user_id.reset(token_user)
            logger.info("Swarm async task finished for run_id=%s", run_id)

async def _execute_phase_async(run_id: str, agent: Agent, input_text: str, session: DBSession, max_turns: int, run_config: RunConfig):
    retry_count = 0
    current_input = input_text

    while retry_count <= MAX_RETRIES:
        if await db_service.should_pause(run_id):
            logger.warning("Pause signal received for run %s during phase execution.", run_id)
            return

        try:
            logger.info("Runner: agent=%s, session=%s, run_id=%s", agent.name, session.session_id, run_id)

            # CRITICAL: Runner.run_sync is synchronous - wrap in asyncio.to_thread
            await asyncio.to_thread(
                Runner.run_sync,
                agent,
                input=current_input,
                session=session,
                max_turns=max_turns,
                run_config=run_config
            )

            # Strict tool enforcement: Check last assistant message
            messages = await db_service.load_messages(run_id)
            # Find the last assistant message for this session
            last_assistant = None
            for msg in reversed(messages):
                if msg.role == "assistant" and msg.session_id == session.session_id:
                    last_assistant = msg
                    break

            if last_assistant:
                # Use sender if available (more accurate for handoffs), otherwise fallback to agent.name
                effective_agent_name = last_assistant.sender or agent.name

                # Only enforce for non-Reporter agents
                if effective_agent_name != "Reporter":
                    has_content = last_assistant.content and last_assistant.content.strip()
                    has_tool_calls = last_assistant.tool_calls and len(last_assistant.tool_calls) > 0

                    # Violation: Has content but no tool calls
                    if has_content and not has_tool_calls:
                        error_msg = f"Strict mode violation: Agent {effective_agent_name} output text without calling a tool. Text: {last_assistant.content[:200]}"
                        logger.warning(error_msg)
                        raise ModelBehaviorError(error_msg)

            return
        except (ModelBehaviorError, BadRequestError) as e:
            retry_count += 1
            error_msg = str(e)
            short_error = error_msg[:500] + "..." if len(error_msg) > 500 else error_msg
            logger.warning("API/Model Error (attempt %s) for run %s: %s", retry_count, run_id, short_error)

            # RECOVERY: Try to find the last active agent to restart from
            messages = await db_service.load_messages(run_id)
            for msg in reversed(messages):
                if msg.role == "assistant" and msg.sender in AGENT_MAP:
                    agent = AGENT_MAP[msg.sender]
                    logger.info(f"Retrying with last active agent: {agent.name}")
                    break

            await db_service.save_message(run_id, "system", f"System Feedback: {short_error}", session_id=session.session_id)
            current_input = "[INTERNAL SYSTEM NOTIFICATION]: An error occurred. You were the last active agent. Please take into account the feedback and continue."
        except Exception as e:
            retry_count += 1
            err_msg = str(e)
            short_err = err_msg[:500] + "..." if len(err_msg) > 500 else err_msg
            logger.exception("Generic error in phase (attempt %s) for run %s: %s", retry_count, run_id, short_err)

            # RECOVERY: Try to find the last active agent to restart from
            messages = await db_service.load_messages(run_id)
            for msg in reversed(messages):
                if msg.role == "assistant" and msg.sender in AGENT_MAP:
                    agent = AGENT_MAP[msg.sender]
                    logger.info(f"Retrying with last active agent: {agent.name}")
                    break

            await db_service.save_message(run_id, "system", f"System Error: {short_err}", session_id=session.session_id)
            current_input = "[INTERNAL SYSTEM NOTIFICATION]: An internal error occurred. Please try to recover."
            await asyncio.sleep(2)  # НЕ time.sleep!

    raise RuntimeError(f"Swarm execution failed for run {run_id} after {MAX_RETRIES} retries.")

runner = SwarmRunner()