"""
Tools package for the research system.

Contains tools that can be called by agents:
- search: Web search with ML-based filtering
- filesystem: File operations and command execution
- knowledge: Knowledge-based answering
"""

from backend.tools.search import intelligent_web_search
from backend.tools.filesystem import read_file, execute_command
from backend.tools.knowledge import answer_from_knowledge

__all__ = [
    "intelligent_web_search",
    "read_file",
    "execute_command",
    "answer_from_knowledge",
]
