"""
LLM provider setup with ChatOpenAI.

Provides a configured ChatOpenAI instance for use in LangGraph nodes.
"""

import logging
from functools import lru_cache
from typing import Optional

from langchain_openai import ChatOpenAI

from backend.core.config import config

logger = logging.getLogger(__name__)


class LLMProvider:
    """
    LLM provider with lazy initialization and token tracking.

    Wraps ChatOpenAI with configuration from settings.
    """

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None
        self._total_tokens: int = 0

    def get_llm(
        self,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> ChatOpenAI:
        """
        Get a configured ChatOpenAI instance.

        Args:
            temperature: Sampling temperature (0.0 = deterministic)
            max_tokens: Maximum tokens to generate (None = model default)

        Returns:
            Configured ChatOpenAI instance
        """
        return ChatOpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
            model=config.llm.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def get_llm_with_tools(
        self,
        tools: list,
        temperature: float = 0.0,
        tool_choice: str = "auto",
    ) -> ChatOpenAI:
        """
        Get ChatOpenAI instance with tools bound.

        Args:
            tools: List of LangChain tools to bind
            temperature: Sampling temperature
            tool_choice: Tool choice mode ("auto", "required", "none")

        Returns:
            ChatOpenAI with tools bound
        """
        llm = self.get_llm(temperature=temperature)
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


@lru_cache
def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    """
    Get a cached ChatOpenAI instance.

    For simple use cases where you don't need tools.
    """
    return get_llm_provider().get_llm(temperature=temperature)
