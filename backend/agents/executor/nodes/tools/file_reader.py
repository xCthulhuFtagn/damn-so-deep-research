"""
File reader node - reads local files with optional line ranges.

Supports path:start-end syntax for line range specification.
"""

import logging
import re
from pathlib import Path

from backend.agents.state import ExecutorToolCall, ResearchState
from backend.core.config import config

logger = logging.getLogger(__name__)


def _parse_file_path(path_spec: str) -> tuple[str, int | None, int | None]:
    """
    Parse file path with optional line range.

    Supports formats:
    - /path/to/file.py
    - /path/to/file.py:10
    - /path/to/file.py:10-50

    Returns: (path, start_line, end_line)
    """
    # Match pattern: path:start-end or path:line
    match = re.match(r"^(.+?):(\d+)(?:-(\d+))?$", path_spec)

    if match:
        path = match.group(1)
        start = int(match.group(2))
        end = int(match.group(3)) if match.group(3) else start
        return path, start, end

    return path_spec, None, None


async def file_reader_node(state: ResearchState) -> dict:
    """
    Read a local file with optional line range.

    Params from executor_decision:
    - path: File path (can include :line or :start-end suffix)
    - start_line: Optional start line (1-indexed)
    - end_line: Optional end line (1-indexed)
    """
    run_id = state.get("run_id", "")
    decision = state.get("executor_decision", {})
    params = decision.get("params", {})
    tool_history = state.get("executor_tool_history", [])

    path_spec = params.get("path", "")
    explicit_start = params.get("start_line")
    explicit_end = params.get("end_line")

    # Parse path for embedded line range
    path, parsed_start, parsed_end = _parse_file_path(path_spec)

    # Explicit params override parsed ones
    start_line = explicit_start or parsed_start
    end_line = explicit_end or parsed_end

    logger.info(f"File reader for run {run_id}: {path} (lines {start_line}-{end_line})")

    # Create tool call record
    tool_call = ExecutorToolCall(
        id=len(tool_history) + 1,
        tool="read_file",
        params={"path": path, "start_line": start_line, "end_line": end_line},
        result=None,
        success=False,
        error=None,
    )

    try:
        resolved_path = Path(path).resolve()

        if not resolved_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not resolved_path.is_file():
            raise ValueError(f"Not a file: {path}")

        # Read file content
        content = resolved_path.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        total_lines = len(lines)

        # Apply line range if specified
        if start_line is not None:
            start_idx = max(0, start_line - 1)  # Convert to 0-indexed
            end_idx = min(total_lines, end_line) if end_line else total_lines
            lines = lines[start_idx:end_idx]
            content = "\n".join(lines)

            # Add line numbers for context
            numbered_lines = []
            for i, line in enumerate(lines, start=start_idx + 1):
                numbered_lines.append(f"{i:4d} | {line}")
            content = "\n".join(numbered_lines)

        # Enforce character limit
        max_chars = config.research.max_file_read_chars
        if len(content) > max_chars:
            content = content[:max_chars]
            content += f"\n\n... (truncated, showing first {max_chars} chars of file)"

        tool_call["result"] = content
        tool_call["success"] = True

        logger.info(f"File reader succeeded for run {run_id}: {len(content)} chars")

    except Exception as e:
        logger.error(f"File reader failed for run {run_id}: {e}")
        tool_call["error"] = str(e)
        tool_call["success"] = False

    return {
        "executor_tool_history": tool_call,  # Append via reducer
        "executor_call_count": 1,  # Increment via reducer
    }
