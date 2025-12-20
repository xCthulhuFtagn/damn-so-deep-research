import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def _parse_level(level_str: str) -> int:
    if not level_str:
        return logging.INFO
    level = logging.getLevelNamesMapping().get(level_str.upper())
    return level if isinstance(level, int) else logging.INFO


def setup_logging() -> None:
    """
    Central logging setup.

    Env vars:
      - LOG_LEVEL: DEBUG/INFO/WARNING/ERROR (default: INFO)
      - LOG_FILE:  optional path to a file (enables RotatingFileHandler)
      - LOG_FORMAT: optional python logging format string

    Safe to call multiple times (Streamlit reruns, repeated imports).
    """
    root = logging.getLogger()

    # Avoid duplicated handlers on Streamlit reruns
    for h in root.handlers:
        if getattr(h, "_deep_research_configured", False):
            return

    level = _parse_level(os.getenv("LOG_LEVEL", "INFO"))
    fmt = os.getenv("LOG_FORMAT", DEFAULT_LOG_FORMAT)
    formatter = logging.Formatter(fmt)

    root.setLevel(level)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler._deep_research_configured = True  # type: ignore[attr-defined]
    root.addHandler(stream_handler)

    log_file = (os.getenv("LOG_FILE") or "").strip()
    if log_file:
        p = Path(log_file)
        if p.parent:
            p.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            p, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler._deep_research_configured = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    # Reduce noise from chatty libraries (raise per your needs via LOG_LEVEL)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    # DuckDuckGo search dependencies
    logging.getLogger("primp").setLevel(logging.WARNING)
    logging.getLogger("rquest").setLevel(logging.WARNING)
    logging.getLogger("cookie_store").setLevel(logging.WARNING)
    logging.getLogger("duckduckgo_search").setLevel(logging.WARNING)
    
    # Streamlit uses watchdog for file watching; with root DEBUG it can spam heavily,
    # especially when LOG_FILE is inside the project and is being modified constantly.
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("streamlit").setLevel(logging.WARNING)


