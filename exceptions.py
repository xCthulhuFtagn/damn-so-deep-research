"""
Custom exception hierarchy for Deep Research Swarm.

This module defines a hierarchy of exceptions for better error handling
and debugging throughout the research system.
"""


class ResearchError(Exception):
    """Base exception for all research system errors."""
    pass


class ConfigurationError(ResearchError):
    """Raised when configuration validation fails or required config is missing."""
    pass


class SearchError(ResearchError):
    """Raised when search or scraping operations fail."""

    def __init__(self, message: str, query: str = None, source: str = None):
        """
        Args:
            message: Error description
            query: The search query that failed (optional)
            source: The source/URL that failed (optional)
        """
        super().__init__(message)
        self.query = query
        self.source = source

    def __str__(self):
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

    def __init__(self, message: str, command: str = None, exit_code: int = None):
        """
        Args:
            message: Error description
            command: The command that failed (optional)
            exit_code: Process exit code (optional)
        """
        super().__init__(message)
        self.command = command
        self.exit_code = exit_code

    def __str__(self):
        parts = [super().__str__()]
        if self.command:
            parts.append(f"Command: {self.command}")
        if self.exit_code is not None:
            parts.append(f"Exit code: {self.exit_code}")
        return " | ".join(parts)


class ApprovalDeniedError(ResearchError):
    """Raised when user denies approval for an action."""
    pass


class PauseSignalError(ResearchError):
    """Raised when execution is paused by user signal."""
    pass


class RetryExhaustedError(ResearchError):
    """Raised when maximum retry attempts are exceeded."""

    def __init__(self, message: str, attempts: int):
        """
        Args:
            message: Error description
            attempts: Number of attempts made
        """
        super().__init__(message)
        self.attempts = attempts

    def __str__(self):
        return f"{super().__str__()} | Attempts: {self.attempts}"


class ModelError(ResearchError):
    """Raised when ML model loading or inference fails."""
    pass


class NetworkError(ResearchError):
    """Raised when network operations fail."""

    def __init__(self, message: str, url: str = None, status_code: int = None):
        """
        Args:
            message: Error description
            url: The URL that failed (optional)
            status_code: HTTP status code (optional)
        """
        super().__init__(message)
        self.url = url
        self.status_code = status_code

    def __str__(self):
        parts = [super().__str__()]
        if self.url:
            parts.append(f"URL: {self.url}")
        if self.status_code:
            parts.append(f"Status: {self.status_code}")
        return " | ".join(parts)
