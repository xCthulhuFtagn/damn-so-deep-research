import threading
import logging
import time
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
                model_settings=ModelSettings(temperature=0.0, parallel_tool_calls=False, tool_choice="auto"),
            )

            current_agent = start_agent
            current_input = input_text
            
            if current_agent.name == "Planner":
                logger.info("=== PHASE 1: PLANNING for run %s ===", run_id)
                session = DBSession(f"planner_{run_id}")
                _execute_phase(run_id, current_agent, current_input, session, max_turns, run_config)
                
                if db_service.should_stop(run_id):
                    logger.info("Stop signal received after Phase 1 for run %s", run_id)
                    return

                current_agent = executor_agent
                current_input = "Plan created. Begin execution."

            if current_agent.name in ["Executor", "Evaluator", "Strategist"]:
                logger.info("=== PHASE 2: EXECUTION for run %s ===", run_id)
                session = DBSession(f"research_{run_id}")
                
                while not db_service.should_stop(run_id):
                    next_step = db_service.get_next_step(run_id)
                    if not next_step:
                        logger.info("No more steps for run_id=%s. Execution Phase Complete.", run_id)
                        break
                    
                    logger.info(f"Executing Step {next_step['step_number']} for run {run_id}: {next_step['description']}")
                    step_input = f"Execute Step {next_step['step_number']}: {next_step['description']}"
                    
                    try:
                        _execute_phase(run_id, current_agent, step_input, session, max_turns, run_config)
                    except Exception as e:
                        logger.error(f"Step {next_step['step_number']} for run {run_id} failed: {e}")
                        db_service.update_step_status(next_step['id'], "FAILED", f"System Error: {e}")
                
                if db_service.should_stop(run_id):
                    logger.info("Stop signal received during/after Phase 2 for run %s", run_id)
                    return

                current_agent = reporter_agent
                current_input = "All steps completed. Generate the final report."

            if current_agent.name == "Reporter":
                logger.info("=== PHASE 3: REPORTING for run %s ===", run_id)
                session = DBSession(f"reporter_{run_id}")
                _execute_phase(run_id, current_agent, current_input, session, max_turns, run_config)

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
        if db_service.should_stop(run_id):
            logger.warning("Stop signal received for run %s during phase execution.", run_id)
            return

        try:
            logger.info("Runner: agent=%s, session=%s, run_id=%s", agent.name, session.session_id, run_id)
            return Runner.run_sync(agent, input=current_input, session=session, max_turns=max_turns, run_config=run_config)
        except (ModelBehaviorError, BadRequestError) as e:
            retry_count += 1
            error_msg = str(e)
            short_error = error_msg[:500] + "..." if len(error_msg) > 500 else error_msg
            logger.warning("API/Model Error (attempt %s) for run %s: %s", retry_count, run_id, short_error)
            db_service.save_message(run_id, "system", f"System Feedback: {short_error}", session_id=session.session_id)
            current_input = "An error occurred. Please review the feedback and continue."
        except Exception as e:
            retry_count += 1
            err_msg = str(e)
            short_err = err_msg[:500] + "..." if len(err_msg) > 500 else err_msg
            logger.exception("Generic error in phase (attempt %s) for run %s: %s", retry_count, run_id, short_err)
            db_service.save_message(run_id, "system", f"System Error: {short_err}", session_id=session.session_id)
            current_input = "An internal error occurred. Please try to recover."
            time.sleep(2)

    raise RuntimeError(f"Swarm execution failed for run {run_id} after {MAX_RETRIES} retries.")

runner = SwarmRunner()