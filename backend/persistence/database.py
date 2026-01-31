"""
Async SQLite database service.

Simplified for LangGraph - handles only:
- Users (auth)
- Runs (metadata)
- Approvals (command execution approval)

Graph state is managed by LangGraph checkpointer.
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional

import aiosqlite
import bcrypt

from backend.core.config import config
from backend.core.exceptions import DatabaseError
from backend.persistence.models import User, Run, Approval

logger = logging.getLogger(__name__)


class DatabaseService:
    """
    Async database service for user and run management.

    Uses aiosqlite for async SQLite operations with WAL mode.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.database.app_db_path
        self._initialized = False

    @asynccontextmanager
    async def get_connection(self):
        """Async context manager for database connection."""
        conn = await aiosqlite.connect(self.db_path, timeout=30)
        await conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    async def init_db(self) -> None:
        """Initialize database schema."""
        if self._initialized:
            return

        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        logger.info(f"Initializing database at: {self.db_path}")

        async with self.get_connection() as conn:
            # Users table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Runs table (metadata only - state is in LangGraph)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    total_tokens INTEGER DEFAULT 0,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            """)

            # Approvals table (for command execution approval)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS approvals (
                    command_hash TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    command_text TEXT NOT NULL,
                    approved INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_id, command_hash),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            """)

            # Indexes
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_user_id ON runs(user_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_run_id ON approvals(run_id)"
            )

            await conn.commit()

        self._initialized = True
        logger.info("Database initialized successfully")

    # --- User Operations ---

    async def create_user(self, username: str, password: str) -> Optional[User]:
        """
        Create a new user with hashed password.

        Returns None if username already exists.
        """
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        user_id = str(uuid.uuid4())

        try:
            async with self.get_connection() as conn:
                await conn.execute(
                    "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                    (user_id, username, hashed.decode("utf-8")),
                )
                await conn.commit()

                async with conn.execute(
                    "SELECT id, username, created_at FROM users WHERE id = ?",
                    (user_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    return User(**dict(row)) if row else None

        except aiosqlite.IntegrityError:
            logger.warning(f"Username '{username}' already exists")
            return None

    async def authenticate_user(
        self, username: str, password: str
    ) -> Optional[User]:
        """
        Authenticate user with username and password.

        Returns User if credentials are valid, None otherwise.
        """
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
                (username,),
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            return None

        if bcrypt.checkpw(
            password.encode("utf-8"), row["password_hash"].encode("utf-8")
        ):
            return User(
                id=row["id"],
                username=row["username"],
                created_at=row["created_at"],
            )
        return None

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return User(**dict(row)) if row else None

    # --- Run Operations ---

    async def create_run(self, user_id: str, title: str) -> Run:
        """Create a new research run."""
        run_id = str(uuid.uuid4())

        async with self.get_connection() as conn:
            await conn.execute(
                "INSERT INTO runs (id, user_id, title) VALUES (?, ?, ?)",
                (run_id, user_id, title),
            )
            await conn.commit()

            async with conn.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return Run(**dict(row))

    async def get_run(self, run_id: str) -> Optional[Run]:
        """Get run by ID."""
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return Run(**dict(row)) if row else None

    async def get_user_runs(self, user_id: str) -> List[Run]:
        """Get all runs for a user, ordered by creation date (newest first)."""
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM runs WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [Run(**dict(row)) for row in rows]

    async def update_run(
        self,
        run_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[Run]:
        """Update run metadata."""
        updates = []
        values = []

        if title is not None:
            updates.append("title = ?")
            values.append(title)
        if status is not None:
            updates.append("status = ?")
            values.append(status)

        if not updates:
            return await self.get_run(run_id)

        values.append(run_id)

        async with self.get_connection() as conn:
            await conn.execute(
                f"UPDATE runs SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            await conn.commit()

        return await self.get_run(run_id)

    async def delete_run(self, run_id: str) -> bool:
        """Delete a run and its associated approvals."""
        async with self.get_connection() as conn:
            # Delete approvals first (foreign key)
            await conn.execute(
                "DELETE FROM approvals WHERE run_id = ?", (run_id,)
            )
            # Delete run
            cursor = await conn.execute(
                "DELETE FROM runs WHERE id = ?", (run_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def increment_tokens(self, run_id: str, tokens: int) -> None:
        """Increment token usage for a run."""
        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE runs SET total_tokens = total_tokens + ? WHERE id = ?",
                (tokens, run_id),
            )
            await conn.commit()

    async def mark_active_runs_as_interrupted(self) -> int:
        """
        Mark all active runs as interrupted.

        Called on server startup to handle runs that were interrupted by a crash.
        Returns the number of runs marked as interrupted.
        """
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "UPDATE runs SET status = 'interrupted' WHERE status = 'active'"
            )
            await conn.commit()
            count = cursor.rowcount
            if count > 0:
                logger.info(f"Marked {count} active runs as interrupted due to server restart")
            return count

    # --- Approval Operations ---

    async def create_approval(
        self, run_id: str, command_hash: str, command_text: str
    ) -> Approval:
        """Create a pending approval request."""
        async with self.get_connection() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO approvals (run_id, command_hash, command_text) VALUES (?, ?, ?)",
                (run_id, command_hash, command_text),
            )
            await conn.commit()

            async with conn.execute(
                "SELECT * FROM approvals WHERE run_id = ? AND command_hash = ?",
                (run_id, command_hash),
            ) as cursor:
                row = await cursor.fetchone()
                return Approval(**dict(row))

    async def get_approval(
        self, run_id: str, command_hash: str
    ) -> Optional[Approval]:
        """Get approval by run_id and command_hash."""
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM approvals WHERE run_id = ? AND command_hash = ?",
                (run_id, command_hash),
            ) as cursor:
                row = await cursor.fetchone()
                return Approval(**dict(row)) if row else None

    async def get_pending_approvals(self, run_id: str) -> List[Approval]:
        """Get all pending approvals for a run."""
        async with self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM approvals WHERE run_id = ? AND approved = 0",
                (run_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [Approval(**dict(row)) for row in rows]

    async def respond_to_approval(
        self, run_id: str, command_hash: str, approved: bool
    ) -> Optional[Approval]:
        """Respond to an approval request (approve or deny)."""
        status = 1 if approved else -1

        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE approvals SET approved = ? WHERE run_id = ? AND command_hash = ?",
                (status, run_id, command_hash),
            )
            await conn.commit()

        return await self.get_approval(run_id, command_hash)


# Global instance
_db_service: Optional[DatabaseService] = None


async def get_db_service() -> DatabaseService:
    """Get the global database service instance."""
    global _db_service

    if _db_service is None:
        _db_service = DatabaseService()
        await _db_service.init_db()

    return _db_service
