import threading
import logging
from typing import Optional
from agents import Runner, Agent, RunConfig, ModelSettings
from agents.exceptions import ModelBehaviorError
from openai import BadRequestError
from agents.models.openai_provider import OpenAIProvider
import database
from db_session import DBSession
from config import MAX_TURNS, OPENAI_API_KEY, OPENAI_BASE_URL, MAX_RETRIES
from research_agents import get_agent_by_name

logger = logging.getLogger(__name__)

class SwarmRunner:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None

    def run_in_background(self, agent: Agent, input_text: str, max_turns: int = MAX_TURNS):
        """Starts the swarm execution in a background thread."""
        if database.is_swarm_running():
            logger.warning("Swarm is already running. Cannot start another instance.")
            return

        database.set_swarm_running(True)
        database.set_stop_signal(False)
        
        self.thread = threading.Thread(
            target=self._run_wrapper,
            args=(agent, input_text, max_turns),
            daemon=True
        )
        self.thread.start()
        logger.info("Swarm background thread started with max_turns=%d", max_turns)

    def _run_wrapper(self, agent: Agent, input_text: str, max_turns: int):
        """Wrapper to run the synchronous Runner in a thread."""
        def _resolve_last_agent_fallback(default_agent: Agent) -> Agent:
            """
            Resolves the last active agent from:
            1) Parsed error text (handled in except blocks)
            2) DB history: last assistant message with sender
            Fallbacks to the provided default_agent.
            """
            try:
                messages = database.load_messages()
                for m in reversed(messages):
                    if m.get("role") == "assistant" and m.get("sender"):
                        resolved = get_agent_by_name(m.get("sender"))
                        if resolved:
                            return resolved
            except Exception as err:
                logger.warning("Failed to resolve last agent from DB: %s", err)
            return default_agent

        try:
            logger.info("Starting Runner.run_sync with input length: %s", len(input_text) if input_text else 0)
            
            # Create the session adapter
            session = DBSession()

            # Standard OpenAI Configuration without vLLM hacks
            # Note: We only set global defaults here. Individual agent settings will take precedence.
            run_config = RunConfig(
                model_provider=OpenAIProvider(
                    api_key=OPENAI_API_KEY,
                    base_url=OPENAI_BASE_URL
                ),
                tracing_disabled=True,
                model_settings=ModelSettings(
                    temperature=0.0,  # Critical: deterministic tool calling
                    parallel_tool_calls=False,  # Critical: prevent parallel tool calls
                    tool_choice="auto",
                ),
            )

            retry_count = 0
            current_agent = agent
            current_input = input_text

            while retry_count <= MAX_RETRIES:
                try:
                    logger.info("Running swarm attempt %s with agent=%s max_turns=%s", retry_count + 1, current_agent.name, max_turns)
                    result = Runner.run_sync(
                        current_agent,
                        input=current_input,
                        session=session,
                        max_turns=max_turns,
                        run_config=run_config,
                    )
                    final_len = len(result.final_output) if result.final_output else 0
                    logger.info("Runner finished. Final output chars: %s", final_len)

                    # Post-run guard: if plan still has TODO/IN_PROGRESS and final output is empty/very short,
                    # treat as abnormal completion and retry with feedback (if retries remain).
                    try:
                        plan_df = database.get_all_plan()
                        pending = plan_df[plan_df["status"].isin(["TODO", "IN_PROGRESS"])]
                    except Exception as err:
                        pending = []
                        logger.warning("Post-run guard: failed to load plan status: %s", err)

                    if pending and final_len < 5 and retry_count < MAX_RETRIES:
                        retry_count += 1
                        feedback = (
                            "SYSTEM FEEDBACK: No tool was called or output was empty while tasks remain. "
                            "You must call an allowed tool (or handoff) to proceed."
                        )
                        database.save_message("system", feedback)
                        logger.warning(
                            "Post-run guard triggered (attempt %s/%s). Pending steps remain. Injecting feedback and retrying.",
                            retry_count, MAX_RETRIES
                        )
                        # Keep current_agent; set a minimal input to nudge continuation
                        current_input = "Please continue and call an allowed tool for the active task."
                        continue

                    # Normal completion
                    break

                except ModelBehaviorError as mbe:
                    retry_count += 1
                    error_msg = str(mbe)
                    logger.warning("ModelBehaviorError caught (attempt %s/%s): %s", retry_count, MAX_RETRIES, error_msg)

                    failed_agent = None
                    # Try parse agent name from error text
                    if "in agent" in error_msg:
                        import re
                        match = re.search(r"in agent (\\w+)", error_msg)
                        if match:
                            failed_agent = get_agent_by_name(match.group(1))

                    if not failed_agent:
                        failed_agent = _resolve_last_agent_fallback(current_agent)

                    # Prepare feedback
                    feedback = (
                        "SYSTEM FEEDBACK: Previous turn failed. "
                        "Likely cause: invalid or missing tool call. "
                        f"Error: {error_msg}. "
                        "Use only your allowed tools and continue."
                    )
                    database.save_message("system", feedback)
                    logger.warning("Injecting feedback to agent %s: %s", failed_agent.name if failed_agent else "UNKNOWN", feedback)

                    current_agent = failed_agent or current_agent
                    current_input = "Please continue after fixing the previous tool-call error."

                    if retry_count >= MAX_RETRIES:
                        logger.error("Max retries reached for ModelBehaviorError.")
                        database.save_message("system", "Critical: Max retries reached for behavior errors.")
                        break

                except BadRequestError as bre:
                    retry_count += 1
                    error_msg = str(bre)
                    logger.warning("BadRequestError caught (attempt %s/%s): %s", retry_count, MAX_RETRIES, error_msg)

                    feedback = (
                        "SYSTEM FEEDBACK: Request failed due to context length or bad request. "
                        f"Error: {error_msg}. Reduce output/context and continue."
                    )
                    database.save_message("system", feedback)
                    logger.warning("Injecting feedback due to BadRequestError: %s", feedback)

                    if retry_count >= MAX_RETRIES:
                        logger.error("Max retries reached for BadRequestError.")
                        database.save_message("system", "Critical: Max retries reached for request errors.")
                        break

                except Exception as e:
                    logger.exception("Unexpected error in swarm background thread: %s", e)
                    database.save_message("system", f"Error in background runner: {str(e)}")
                    break

        finally:
            database.set_swarm_running(False)
            logger.info("Swarm background thread finished.")

# Global instance
runner = SwarmRunner()
