import threading
import logging
from typing import Optional
from agents import Runner, Agent, RunConfig, ModelSettings
from agents.models.openai_provider import OpenAIProvider
import database
from db_session import DBSession
from config import MAX_TURNS, OPENAI_API_KEY, OPENAI_BASE_URL

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
        try:
            logger.info("Starting Runner.run_sync with input length: %s", len(input_text) if input_text else 0)
            
            # Create the session adapter
            session = DBSession()

            # Standard OpenAI Configuration without vLLM hacks
            run_config = RunConfig(
                model_provider=OpenAIProvider(
                    api_key=OPENAI_API_KEY,
                    base_url=OPENAI_BASE_URL
                ),
                tracing_disabled=True,
                model_settings=ModelSettings(
                    temperature=0.0,
                    parallel_tool_calls=False,
                    tool_choice="auto",
                ),
            )
            
            # The Runner will handle the loop, tool calls, and state updates (via session)
            result = Runner.run_sync(
                agent,
                input=input_text,
                session=session,
                max_turns=max_turns,
                run_config=run_config,
            )
            
            logger.info("Runner finished. Final output chars: %s", len(result.final_output) if result.final_output else 0)
            
        except Exception as e:
            logger.exception("Error in swarm background thread: %s", e)
            database.save_message("system", f"Error in background runner: {str(e)}")
        finally:
            database.set_swarm_running(False)
            logger.info("Swarm background thread finished.")

# Global instance
runner = SwarmRunner()
