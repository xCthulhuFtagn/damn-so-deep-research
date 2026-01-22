"""
Custom exception hierarchy for the research system.

Provides structured exceptions for better error handling and debugging.
"""

from typing import Optional


class ResearchError(Exception):
    """Base exception for all research system errors."""

    pass


class ConfigurationError(ResearchError):
    """Raised when configuration validation fails or required config is missing."""

    pass


class SearchError(ResearchError):
    """Raised when search or scraping operations fail."""

    def __init__(
        self,
        message: str,
        query: Optional[str] = None,
        source: Optional[str] = None,
    ):
        super().__init__(message)
        self.query = query
        self.source = source

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.query:
            parts.append(f"Query: {self.query}")
        if self.source:
            parts.append(f"Source: {self.source}")
        return " | ".join(parts)


class DatabaseError(ResearchError):
    """Raised when database operations fail."""

    pass


class ExecutionError(ResearchError):
    """Raised when command execution fails."""

    def __init__(
        self,
        message: str,
        command: Optional[str] = None,
        exit_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.command = command
        self.exit_code = exit_code

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.command:
            parts.append(f"Command: {self.command}")
        if self.exit_code is not None:
            parts.append(f"Exit code: {self.exit_code}")
        return " | ".join(parts)


class ApprovalDeniedError(ResearchError):
    """Raised when user denies approval for an action."""

    pass


class GraphInterruptError(ResearchError):
    """Raised when graph execution is interrupted for human input."""

    def __init__(
        self,
        message: str,
        interrupt_type: str = "generic",
        data: Optional[dict] = None,
    ):
        super().__init__(message)
        self.interrupt_type = interrupt_type
        self.data = data or {}

    def __str__(self) -> str:
        return f"{super().__str__()} | Type: {self.interrupt_type}"


class RetryExhaustedError(ResearchError):
    """Raised when maximum retry attempts are exceeded."""

    def __init__(self, message: str, attempts: int):
        super().__init__(message)
        self.attempts = attempts

    def __str__(self) -> str:
        return f"{super().__str__()} | Attempts: {self.attempts}"


class ModelError(ResearchError):
    """Raised when ML model loading or inference fails."""

    pass


class NetworkError(ResearchError):
    """Raised when network operations fail."""

    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        status_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.url = url
        self.status_code = status_code

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.url:
            parts.append(f"URL: {self.url}")
        if self.status_code:
            parts.append(f"Status: {self.status_code}")
        return " | ".join(parts)
