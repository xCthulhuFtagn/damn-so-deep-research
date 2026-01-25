"""
LLM provider setup with ChatOpenAI.

Provides a configured ChatOpenAI instance for use in LangGraph nodes.
Includes token tracking with async callback support.
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI

from backend.core.config import config

logger = logging.getLogger(__name__)


class TokenTrackingCallback(BaseCallbackHandler):
    """
    Callback handler that tracks token usage from LLM responses.

    Calls an async callback with (run_id, input_tokens, output_tokens) on each LLM response.
    """

    def __init__(
        self,
        run_id: str,
        on_tokens: Optional[Callable[[str, int, int], Coroutine[Any, Any, None]]] = None,
    ):
        super().__init__()
        self.run_id = run_id
        self.on_tokens = on_tokens
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """Called when LLM finishes. Extract token usage from response."""
        try:
            # Try to get token usage from response
            if hasattr(response, "llm_output") and response.llm_output:
                token_usage = response.llm_output.get("token_usage", {})
                input_tokens = token_usage.get("prompt_tokens", 0)
                output_tokens = token_usage.get("completion_tokens", 0)
            elif hasattr(response, "generations") and response.generations:
                # Try to get from generation info
                gen = response.generations[0][0] if response.generations[0] else None
                if gen and hasattr(gen, "generation_info") and gen.generation_info:
                    input_tokens = gen.generation_info.get("prompt_tokens", 0)
                    output_tokens = gen.generation_info.get("completion_tokens", 0)
                else:
                    input_tokens = 0
                    output_tokens = 0
            else:
                input_tokens = 0
                output_tokens = 0

            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens

            total = input_tokens + output_tokens
            if total > 0 and self.on_tokens:
                # Schedule async callback
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.on_tokens(self.run_id, input_tokens, output_tokens))
                except RuntimeError:
                    # No running loop - ignore (sync context)
                    pass

            logger.debug(f"Token usage for run {self.run_id}: +{input_tokens} in, +{output_tokens} out")
        except Exception as e:
            logger.warning(f"Failed to extract token usage: {e}")


class LLMProvider:
    """
    LLM provider with lazy initialization and token tracking.

    Wraps ChatOpenAI with configuration from settings.
    """

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None
        self._total_tokens: int = 0
        self._token_callback: Optional[Callable[[str, int, int], Coroutine[Any, Any, None]]] = None
        self._current_run_id: Optional[str] = None

    def set_token_callback(
        self,
        run_id: str,
        callback: Callable[[str, int, int], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Set callback for token tracking.

        Args:
            run_id: Current run ID
            callback: Async callback(run_id, input_tokens, output_tokens)
        """
        self._current_run_id = run_id
        self._token_callback = callback

    def clear_token_callback(self) -> None:
        """Clear the token callback."""
        self._current_run_id = None
        self._token_callback = None

    def get_llm(
        self,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        run_id: Optional[str] = None,
    ) -> ChatOpenAI:
        """
        Get a configured ChatOpenAI instance.

        Args:
            temperature: Sampling temperature (0.0 = deterministic)
            max_tokens: Maximum tokens to generate (None = model default)
            run_id: Optional run ID for token tracking (uses provider's run_id if not specified)

        Returns:
            Configured ChatOpenAI instance
        """
        callbacks = []
        effective_run_id = run_id or self._current_run_id

        if effective_run_id and self._token_callback:
            callbacks.append(TokenTrackingCallback(effective_run_id, self._token_callback))

        return ChatOpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
            model=config.llm.model,
            temperature=temperature,
            max_tokens=max_tokens,
            callbacks=callbacks if callbacks else None,
        )

    def get_creative_llm(
        self,
        run_id: Optional[str] = None,
    ) -> ChatOpenAI:
        """
        Get a ChatOpenAI instance optimized for creative/verbose generation.

        Uses higher temperature and max_tokens for more detailed output.
        Good for report generation where you want comprehensive content.

        Args:
            run_id: Optional run ID for token tracking

        Returns:
            ChatOpenAI configured for creative generation
        """
        return self.get_llm(
            temperature=config.llm.creative_temperature,
            max_tokens=config.llm.creative_max_tokens,
            run_id=run_id,
        )

    def get_llm_with_tools(
        self,
        tools: list,
        temperature: float = 0.0,
        tool_choice: str = "auto",
        run_id: Optional[str] = None,
    ) -> ChatOpenAI:
        """
        Get ChatOpenAI instance with tools bound.

        Args:
            tools: List of LangChain tools to bind
            temperature: Sampling temperature
            tool_choice: Tool choice mode ("auto", "required", "none")
            run_id: Optional run ID for token tracking

        Returns:
            ChatOpenAI with tools bound
        """
        llm = self.get_llm(temperature=temperature, run_id=run_id)
        return llm.bind_tools(tools, tool_choice=tool_choice)

    def track_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Track token usage."""
        self._total_tokens += input_tokens + output_tokens

    @property
    def total_tokens(self) -> int:
        """Get total tokens used."""
        return self._total_tokens

    def reset_token_count(self) -> None:
        """Reset token counter."""
        self._total_tokens = 0


# Global provider instance
_provider: Optional[LLMProvider] = None


def get_llm_provider() -> LLMProvider:
    """Get the global LLM provider instance."""
    global _provider
    if _provider is None:
        _provider = LLMProvider()
    return _provider


def get_llm(temperature: float = 0.0, run_id: Optional[str] = None) -> ChatOpenAI:
    """
    Get a ChatOpenAI instance.

    For simple use cases where you don't need tools.

    Args:
        temperature: Sampling temperature (0.0 = deterministic)
        run_id: Optional run ID for token tracking

    Returns:
        Configured ChatOpenAI instance
    """
    return get_llm_provider().get_llm(temperature=temperature, run_id=run_id)


def get_creative_llm(run_id: Optional[str] = None) -> ChatOpenAI:
    """
    Get a ChatOpenAI instance optimized for creative/verbose generation.

    Args:
        run_id: Optional run ID for token tracking

    Returns:
        ChatOpenAI configured for creative generation
    """
    return get_llm_provider().get_creative_llm(run_id=run_id)
