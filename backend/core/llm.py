"""
LLM provider setup with ChatOpenAI.

Provides a configured ChatOpenAI instance for use in LangGraph nodes.
Includes token tracking with async callback support.
"""

import json
import logging
from typing import Any, Callable, Coroutine, Optional, Type, TypeVar

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from backend.core.config import config

logger = logging.getLogger(__name__)


class TokenTrackingCallback(AsyncCallbackHandler):
    """
    Async callback handler that tracks token usage from LLM responses.

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

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """Called when LLM finishes. Extract token usage from response."""
        try:
            input_tokens = 0
            output_tokens = 0

            logger.debug(f"on_llm_end called for run {self.run_id}, response type: {type(response).__name__}")

            # Method 1: Try llm_output.token_usage (OpenAI standard)
            if hasattr(response, "llm_output") and response.llm_output:
                token_usage = response.llm_output.get("token_usage", {})
                if token_usage:
                    logger.debug(f"Found token_usage in llm_output: {token_usage}")
                input_tokens = token_usage.get("prompt_tokens", 0)
                output_tokens = token_usage.get("completion_tokens", 0)

            # Method 2: Try generation's usage_metadata (modern langchain)
            if input_tokens == 0 and output_tokens == 0:
                if hasattr(response, "generations") and response.generations:
                    gen = response.generations[0][0] if response.generations[0] else None
                    if gen:
                        # Check usage_metadata on the message
                        if hasattr(gen, "message") and hasattr(gen.message, "usage_metadata"):
                            usage = gen.message.usage_metadata
                            if usage:
                                input_tokens = getattr(usage, "input_tokens", 0) or 0
                                output_tokens = getattr(usage, "output_tokens", 0) or 0

                        # Fallback: Check generation_info
                        if input_tokens == 0 and output_tokens == 0:
                            if hasattr(gen, "generation_info") and gen.generation_info:
                                input_tokens = gen.generation_info.get("prompt_tokens", 0)
                                output_tokens = gen.generation_info.get("completion_tokens", 0)

            # Method 3: Try response_metadata on generation message
            if input_tokens == 0 and output_tokens == 0:
                if hasattr(response, "generations") and response.generations:
                    gen = response.generations[0][0] if response.generations[0] else None
                    if gen and hasattr(gen, "message") and hasattr(gen.message, "response_metadata"):
                        metadata = gen.message.response_metadata
                        if metadata:
                            token_usage = metadata.get("token_usage", {})
                            input_tokens = token_usage.get("prompt_tokens", 0)
                            output_tokens = token_usage.get("completion_tokens", 0)

            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens

            total = input_tokens + output_tokens
            if total > 0 and self.on_tokens:
                # Directly await the async callback
                await self.on_tokens(self.run_id, input_tokens, output_tokens)
                logger.info(f"Token usage for run {self.run_id}: +{input_tokens} in, +{output_tokens} out (total: {total})")
            elif total == 0:
                logger.warning(f"No token usage info available for run {self.run_id} (LLM may not report tokens)")
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


def extract_tokens_from_response(response: Any) -> tuple[int, int]:
    """
    Extract token usage from an AIMessage or similar response object.

    Modern langchain returns tokens in usage_metadata attribute.

    Args:
        response: AIMessage or similar object from LLM invocation

    Returns:
        Tuple of (input_tokens, output_tokens)
    """
    input_tokens = 0
    output_tokens = 0

    # Method 1: usage_metadata (modern langchain)
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = response.usage_metadata
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

    # Method 2: response_metadata.token_usage (OpenAI format)
    if input_tokens == 0 and output_tokens == 0:
        if hasattr(response, "response_metadata") and response.response_metadata:
            metadata = response.response_metadata
            token_usage = metadata.get("token_usage", {})
            input_tokens = token_usage.get("prompt_tokens", 0)
            output_tokens = token_usage.get("completion_tokens", 0)

    return input_tokens, output_tokens


async def track_response_tokens(run_id: str, response: Any) -> int:
    """
    Extract and track tokens from an LLM response.

    This is a convenience function that extracts tokens from response
    and triggers the token callback if configured.

    Args:
        run_id: Run ID for tracking
        response: AIMessage or similar object from LLM invocation

    Returns:
        Total tokens (input + output)
    """
    input_tokens, output_tokens = extract_tokens_from_response(response)
    total = input_tokens + output_tokens

    if total > 0:
        provider = get_llm_provider()
        if provider._token_callback:
            try:
                await provider._token_callback(run_id, input_tokens, output_tokens)
            except Exception as e:
                logger.warning(f"Failed to call token callback: {e}")

        logger.debug(f"Tracked tokens for run {run_id}: {input_tokens} in, {output_tokens} out")
    else:
        logger.debug(f"No token info in response for run {run_id}")

    return total


T = TypeVar("T", bound=BaseModel)


async def invoke_structured_output(
    llm: ChatOpenAI,
    schema: Type[T],
    prompt: str,
) -> T:
    """
    Invoke LLM with structured output, falling back to JSON parsing if needed.

    Some models (especially open-source ones via OpenAI-compatible APIs) don't
    properly support structured output. This function tries structured output
    first, then falls back to parsing JSON from the raw content.

    Args:
        llm: ChatOpenAI instance
        schema: Pydantic model class for the expected output
        prompt: The prompt to send to the LLM

    Returns:
        Parsed instance of the schema

    Raises:
        ValueError: If structured output fails and fallback parsing also fails
    """
    # Try structured output with include_raw=True to access raw response on failure
    structured_llm = llm.with_structured_output(schema, include_raw=True)
    result = await structured_llm.ainvoke(prompt)

    # If parsed successfully, return it
    if result.get("parsed"):
        return result["parsed"]

    # Fallback: try to parse from raw response content
    raw = result.get("raw")
    if raw and hasattr(raw, "content") and raw.content:
        content = raw.content
        logger.debug(f"Structured output empty, trying to parse JSON from content: {content[:200]}...")
        try:
            # Try to extract JSON from content (might be wrapped in markdown code blocks)
            json_str = content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)
            return schema.model_validate(data)
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to parse JSON from content: {e}")
        except Exception as e:
            logger.warning(f"Failed to validate parsed JSON: {e}")

    raise ValueError(
        f"Could not get structured output from LLM. "
        f"Raw response content: {raw.content if raw and hasattr(raw, 'content') else raw}"
    )
