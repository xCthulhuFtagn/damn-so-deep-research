"""
FastAPI API package.

Contains routes, dependencies, and WebSocket management.
"""

from backend.api.websocket import ConnectionManager, get_connection_manager

__all__ = ["ConnectionManager", "get_connection_manager"]
