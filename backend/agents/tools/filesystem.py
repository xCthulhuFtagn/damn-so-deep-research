"""
Filesystem tools for file reading and command execution.

Command execution requires approval through the human-in-the-loop system.
"""

import asyncio
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Optional

from backend.core.exceptions import ExecutionError

logger = logging.getLogger(__name__)


async def read_file(file_path: str, max_lines: Optional[int] = None) -> str:
    """
    Read contents of a local file.

    Args:
        file_path: Path to the file to read
        max_lines: Maximum number of lines to read (None = all)

    Returns:
        File contents or error message
    """
    try:
        path = Path(file_path).resolve()

        if not path.exists():
            return f"Error: File not found: {file_path}"

        if not path.is_file():
            return f"Error: Not a file: {file_path}"

        # Read file
        content = path.read_text(encoding="utf-8", errors="replace")

        # Limit lines if requested
        if max_lines:
            lines = content.split("\n")
            if len(lines) > max_lines:
                content = "\n".join(lines[:max_lines])
                content += f"\n\n... (truncated, showing first {max_lines} of {len(lines)} lines)"

        logger.info(f"Read file: {file_path} ({len(content)} chars)")
        return content

    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return f"Error reading file: {e}"


def get_command_hash(command: str) -> str:
    """Generate hash for command approval tracking."""
    return hashlib.md5(command.encode()).hexdigest()


async def execute_command(
    command: str,
    timeout: int = 60,
    require_approval: bool = True,
    approval_callback: Optional[callable] = None,
) -> str:
    """
    Execute a terminal command.

    In the LangGraph system, approval is handled via interrupts.
    This function is primarily for direct execution after approval.

    Args:
        command: Shell command to execute
        timeout: Execution timeout in seconds
        require_approval: Whether to require approval (default True)
        approval_callback: Optional async callback to check approval

    Returns:
        Command output or error message
    """
    logger.info(f"Executing command: {command}")

    try:
        # Run in subprocess
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            raise ExecutionError(
                f"Command timed out after {timeout}s",
                command=command,
            )

        # Combine output
        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")

        if errors:
            output += f"\n\nSTDERR:\n{errors}"

        if process.returncode != 0:
            output += f"\n\nExit code: {process.returncode}"

        logger.info(f"Command completed: exit={process.returncode}")
        return output.strip() or "(no output)"

    except ExecutionError:
        raise
    except Exception as e:
        logger.error(f"Command execution error: {e}")
        raise ExecutionError(str(e), command=command)
