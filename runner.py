import threading
import logging
import time
from typing import Optional
from agents import Runner, Agent, RunConfig, ModelSettings
from agents.exceptions import ModelBehaviorError
from agents.models.interface import ModelProvider
from agents.models.interface import Model
from openai import AsyncOpenAI, BadRequestError
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from database import DatabaseManager
from db_session import DBSession
from config import MAX_TURNS, OPENAI_API_KEY, OPENAI_BASE_URL, MAX_RETRIES, MODEL

# Delayed import to avoid circular dependency issues if possible, 
# or ensure research_agents imports database/tools safely.
# Assuming research_agents is importable.
from research_agents import get_agent_by_name, planner_agent, executor_agent, reporter_agent

logger = logging.getLogger(__name__)

class VLLMChatCompletionsProvider(ModelProvider):
    """
    Forces Agents SDK to use Chat Completions API shape against an OpenAI-compatible server (vLLM).
    This avoids Responses API 'input' incompatibilities when Session injects history as a list.
    """
    def __init__(self, base_url: str, api_key: str, default_model: str):
        # AsyncOpenAI is required by OpenAIChatCompletionsModel
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key
        )
        self._default_model = default_model

    def get_model(self, model_name: str | None) -> Model:
        return OpenAIChatCompletionsModel(
            model=model_name or self._default_model,
            openai_client=self._client
        )



class SwarmRunner:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None

    def run_in_background(self, start_agent: Agent, input_text: str, max_turns: int = MAX_TURNS):
        """Starts the swarm execution in a background thread."""
        if DatabaseManager.get_instance().is_swarm_running():
            logger.warning("Swarm is already running. Cannot start another instance.")
            return

        DatabaseManager.get_instance().set_swarm_running(True)
        DatabaseManager.get_instance().set_stop_signal(False)
        
        self.thread = threading.Thread(
            target=self._run_wrapper,
            args=(start_agent, input_text, max_turns),
            daemon=True
        )
        self.thread.start()
        logger.info("Swarm background thread started with max_turns=%d", max_turns)

    def _run_wrapper(self, start_agent: Agent, input_text: str, max_turns: int):
        """Wrapper to run the synchronous Runner in a thread with Phase management."""

        # Standard OpenAI Configuration
        run_config = RunConfig(
            model_provider=VLLMChatCompletionsProvider(
                api_key=OPENAI_API_KEY,
                base_url=OPENAI_BASE_URL,
                default_model=MODEL
            ),
            tracing_disabled=True,
            model_settings=ModelSettings(
            temperature=0.0,
            parallel_tool_calls=False,
                tool_choice="auto",
            ),
        )

        try:
            current_agent = start_agent
            current_input = input_text
            
            # --- PHASE 1: PLANNING ---
            if current_phase_is_planner(current_agent):
                logger.info("=== PHASE 1: PLANNING ===")
                session = DBSession("planner_init")
                
                # Execute Planner
                # We expect Planner to add steps and then finish (return text or stop).
                # Logic: Planner runs, calls add_steps_to_plan, then should output "Plan created" and stop.
                _execute_phase(current_agent, current_input, session, max_turns, run_config)
                
                # Transition to Execution
                current_agent = executor_agent
                current_input = "Plan created. Begin execution of the first step."

            # --- PHASE 2: EXECUTION ---
            # This loop continues as long as there are steps to do.
            # Executor, Evaluator, Strategist run in the same 'main_research' session.
            if current_phase_is_executor(current_agent):
                logger.info("=== PHASE 2: EXECUTION ===")
                session = DBSession("main_research")
                
                while True:
                    if DatabaseManager.get_instance().should_stop():
                        logger.info("Stop signal received in Execution Phase.")
                        break
                        
                    next_step = DatabaseManager.get_instance().get_next_step()
                    if next_step is None:
                        logger.info("No more steps (TODO/IN_PROGRESS). Execution Phase Complete.")
                        break
                        
                    logger.info(f"Starting execution for Step {next_step['step_number']}: {next_step['description']}")
                    
                    # Update input to focus on current step
                    # Note: We rely on Task-Scoped Memory in DBSession to filter history.
                    # We inject a specific trigger for the agent.
                    step_input = f"Execute Step {next_step['step_number']}: {next_step['description']}"
                    if current_input:
                        step_input = f"{current_input}\n{step_input}"
                        current_input = None # Clear after first use
                    
                    try:
                        # Run the swarm for this step.
                        # It returns when the agent chain finishes (e.g. Evaluator says "Step Done").
                        # If the agents loop forever, max_turns will catch them.
                        _execute_phase(current_agent, step_input, session, max_turns, run_config)
                    except Exception as step_err:
                        logger.error(f"Step {next_step['step_number']} failed with unhandled error: {step_err}")
                        DatabaseManager.get_instance().update_step_status(next_step['id'], "FAILED", f"System Error: {str(step_err)}")
                        # We don't raise here, so the while loop picks up the next step (or recovery)
                    
                    # Check if we should continue
                    # If the step is still IN_PROGRESS/TODO after the run, something might be wrong,
                    # or max_turns was hit. The loop will retry or pick it up again.
                    pass
                
                # Transition to Reporting
                current_agent = reporter_agent
                current_input = "All steps completed. Generate the final report."

            # --- PHASE 3: REPORTING ---
            if current_phase_is_reporter(current_agent):
                logger.info("=== PHASE 3: REPORTING ===")
                session = DBSession("reporter_flow")
                _execute_phase(current_agent, current_input, session, max_turns, run_config)

        except Exception as e:
            logger.exception("Unexpected error in swarm background thread: %s", e)
            DatabaseManager.get_instance().save_message("system", f"Error in background runner: {str(e)}")

        finally:
            DatabaseManager.get_instance().set_swarm_running(False)
            logger.info("Swarm background thread finished.")

def current_phase_is_planner(agent: Agent) -> bool:
    return agent.name == "Planner"

def current_phase_is_executor(agent: Agent) -> bool:
    return agent.name in ["Executor", "Evaluator", "Strategist"]

def current_phase_is_reporter(agent: Agent) -> bool:
    return agent.name == "Reporter"

def _execute_phase(agent: Agent, input_text: str, session: DBSession, max_turns: int, run_config: RunConfig):
    """Helper to run a single phase with retry logic."""
    retry_count = 0
    current_input = input_text

    while retry_count <= MAX_RETRIES:
        if DatabaseManager.get_instance().should_stop():
            return

        try:
            logger.info("Runner: Starting run with agent=%s session=%s", agent.name, session.session_id)
            result = Runner.run_sync(
                agent,
                input=current_input,
                session=session,
                max_turns=max_turns,
                run_config=run_config,
            )
            # If successful, we return. The logic outside determines next steps.
            return result

        except ModelBehaviorError as mbe:
            logger.exception("ModelBehaviorError: %s", mbe)
            retry_count += 1
            logger.warning("ModelBehaviorError (attempt %s): %s", retry_count, mbe)
            DatabaseManager.get_instance().save_message("system", f"System Feedback: {str(mbe)}", session_id=session.session_id)
            current_input = "Please fix the previous error and continue."
        except BadRequestError as bre:
            retry_count += 1
            # Обрезаем сообщение об ошибке до 500 символов
            error_msg = str(bre)
            if len(error_msg) > 1000:
                short_error = error_msg[:1000] + "... [TRUNCATED]"
            else:
                short_error = error_msg
            
            # Логируем только короткую версию
            logger.warning("BadRequestError (attempt %s): %s", retry_count, short_error)
            
            # В базу тоже лучше писать сокращенную версию, чтобы не раздувать файл
            DatabaseManager.get_instance().save_message("system", f"System Feedback: {short_error}", session_id=session.session_id)
            current_input = "Reduce output length and continue."
        except Exception as e:
            retry_count += 1
            err_msg = str(e)
            short_err = err_msg[:500] + "... [TRUNCATED]" if len(err_msg) > 500 else err_msg
            logger.exception("Generic error in _execute_phase (attempt %s): %s", retry_count, short_err)
            DatabaseManager.get_instance().save_message("system", f"System Error: {short_err}", session_id=session.session_id)
            current_input = "An internal error occurred. Please try to recover or continue."
            # Small delay to prevent tight loop
            time.sleep(2)

    # If we get here, we exhausted retries
    raise RuntimeError(f"Swarm execution failed after {MAX_RETRIES} retries.")


# Global instance
runner = SwarmRunner()
