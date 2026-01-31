"""
Logging configuration with console and file output.

Sets up logging with:
- Console handler (always enabled)
- Rotating file handler (when log_file is configured)
- Noise reduction for chatty libraries
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_format: str = DEFAULT_LOG_FORMAT,
) -> None:
    """
    Configure logging with console and optional file output.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file (enables RotatingFileHandler)
        log_format: Log message format string

    Safe to call multiple times (handlers won't be duplicated).
    """
    root = logging.getLogger()

    # Avoid duplicated handlers on repeated calls
    for h in root.handlers:
        if getattr(h, "_deep_research_configured", False):
            return

    # Parse level
    log_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(log_format)

    root.setLevel(log_level)

    # Console handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler._deep_research_configured = True  # type: ignore[attr-defined]
    root.addHandler(stream_handler)

    # File handler (if configured)
    if log_file:
        log_path = Path(log_file)
        if log_path.parent:
            log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._deep_research_configured = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

        logging.getLogger(__name__).info(f"Logging to file: {log_path.absolute()}")

    # Reduce noise from chatty libraries
    _silence_noisy_loggers()


def _silence_noisy_loggers() -> None:
    """Reduce log noise from third-party libraries."""
    noisy_loggers = [
        # HTTP clients
        "urllib3",
        "httpx",
        "httpcore",
        # OpenAI
        "openai",
        "openai.agents",
        # DuckDuckGo
        "primp",
        "rquest",
        "cookie_store",
        "duckduckgo_search",
        # Content extraction
        "trafilatura",
        "htmldate",
        "charset_normalizer",
        # Uvicorn internals
        "uvicorn.access",
        # LangChain
        "langchain",
        "langsmith",
    ]

    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Extra noisy - set to CRITICAL
    logging.getLogger("openai.agents").setLevel(logging.CRITICAL)
    logging.getLogger("agents").setLevel(logging.CRITICAL)
