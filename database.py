import aiosqlite
import sqlite3
import pandas as pd
import json
import logging
import uuid
import bcrypt
import os
import asyncio
from typing import List, Optional, Dict
from contextlib import asynccontextmanager

from config import DB_PATH
from logging_setup import setup_logging
from schema import ChatMessage

setup_logging()
logger = logging.getLogger(__name__)

# Marker strings for critical errors or informative failures that should not be pruned
CRITICAL_ERROR_MARKERS = [
    "Error:", "Exception:", "Traceback", "Timeout", "ConnectionRefused",
    "Ошибка поискового движка", "failed to", "status code:",
    "ничего не найдено", "не удалось", "не соответствуют", "отброшена фильтром",
    "недоступны", "заблокированы"
]

class DatabaseService:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        # Init DB synchronously on first import (compatibility)
        asyncio.run(self.init_db())

    @asynccontextmanager
    async def get_connection(self):
        """Async context manager for aiosqlite connection"""
        conn = await aiosqlite.connect(self.db_path, timeout=30)
        await conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    async def init_db(self):
        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        logger.info("DB init: path=%s", self.db_path)
        async with self.get_connection() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, user_id TEXT, title TEXT, status TEXT DEFAULT 'active',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    total_tokens INTEGER DEFAULT 0,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS plan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, step_number INTEGER,
                    description TEXT, status TEXT DEFAULT 'TODO', result TEXT, feedback TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS approvals (
                    command_hash TEXT, run_id TEXT, command_text TEXT, approved INTEGER DEFAULT 0,
                    PRIMARY KEY (run_id, command_hash), FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, role TEXT, content TEXT,
                    tool_calls TEXT, tool_call_id TEXT, sender TEXT, session_id TEXT,
                    task_number INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS run_state (
                    run_id TEXT, key TEXT, value TEXT,
                    PRIMARY KEY (run_id, key), FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # --- Lightweight Migration ---
            async def add_column_if_not_exists(table_name, column_name, column_type):
                async with conn.execute(f"PRAGMA table_info({table_name})") as cursor:
                    columns = [info['name'] for info in await cursor.fetchall()]
                if column_name not in columns:
                    logger.info(f"Migrating DB: adding {column_name} to {table_name}")
                    await conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

            await add_column_if_not_exists("messages", "run_id", "TEXT")
            await add_column_if_not_exists("plan", "run_id", "TEXT")
            await add_column_if_not_exists("approvals", "run_id", "TEXT")
            await add_column_if_not_exists("runs", "total_tokens", "INTEGER DEFAULT 0")

            # Recreate approvals table if it has the old primary key
            async with conn.execute("PRAGMA table_info(approvals)") as cursor:
                cols = {info['name']: info for info in await cursor.fetchall()}
            if 'run_id' in cols and not cols['run_id']['pk']:
                logger.info("Recreating approvals table for new composite primary key.")
                await conn.execute("DROP TABLE approvals")
                await conn.execute('''
                    CREATE TABLE approvals (
                        command_hash TEXT, run_id TEXT, command_text TEXT, approved INTEGER DEFAULT 0,
                        PRIMARY KEY (run_id, command_hash), FOREIGN KEY(run_id) REFERENCES runs(id)
                    )
                ''')

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_run_id ON messages(run_id)")
            await conn.commit()
        logger.debug("DB init done")

    async def clear_db(self):
        logger.info("Clearing all data from all tables")
        async with self.get_connection() as conn:
            for table in ["plan", "approvals", "messages", "run_state", "runs", "users"]:
                await conn.execute(f"DELETE FROM {table}")
            await conn.commit()
        logger.debug("DB clear done")

    # --- User & Auth Methods ---
    async def register_user(self, username: str, password: str) -> Optional[str]:
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user_id = str(uuid.uuid4())
        try:
            async with self.get_connection() as conn:
                await conn.execute(
                    "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                    (user_id, username, hashed_password.decode('utf-8'))
                )
                await conn.commit()
            return user_id
        except aiosqlite.IntegrityError:
            logger.warning(f"Username '{username}' already exists.")
            return None

    async def authenticate_user(self, username: str, password: str) -> Optional[str]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,)) as cursor:
                user_row = await cursor.fetchone()
        if user_row and bcrypt.checkpw(password.encode('utf-8'), user_row["password_hash"].encode('utf-8')):
            return user_row["id"]
        return None

    # --- Run Management ---
    async def create_run(self, user_id: str, initial_prompt: str) -> str:
        run_id = str(uuid.uuid4())
        async with self.get_connection() as conn:
            await conn.execute("INSERT INTO runs (id, user_id, title) VALUES (?, ?, ?)", (run_id, user_id, initial_prompt))
            await conn.commit()
        return run_id

    async def get_run_title(self, run_id: str) -> Optional[str]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT title FROM runs WHERE id = ?", (run_id,)) as cursor:
                row = await cursor.fetchone()
        return row["title"] if row else None

    async def update_run_title(self, run_id: str, new_title: str):
        async with self.get_connection() as conn:
            await conn.execute("UPDATE runs SET title = ? WHERE id = ?", (new_title, run_id))
            await conn.commit()

    async def update_run_status(self, run_id: str, status: str):
        """Update the status of a run (e.g., 'active', 'completed')."""
        async with self.get_connection() as conn:
            await conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
            await conn.commit()

    async def get_user_runs(self, user_id: str) -> List[Dict]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT id, title, status, created_at, total_tokens FROM runs WHERE user_id = ? ORDER BY created_at DESC", (user_id,)) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def increment_token_usage(self, run_id: str, tokens: int):
        async with self.get_connection() as conn:
            await conn.execute("UPDATE runs SET total_tokens = total_tokens + ? WHERE id = ?", (tokens, run_id))
            await conn.commit()

    async def get_token_usage(self, run_id: str) -> int:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT total_tokens FROM runs WHERE id = ?", (run_id,)) as cursor:
                row = await cursor.fetchone()
        return (row["total_tokens"] or 0) if row else 0

    # --- State Operations (Per Run) ---
    async def _set_run_state(self, run_id: str, key: str, value: str):
        async with self.get_connection() as conn:
            await conn.execute("INSERT OR REPLACE INTO run_state (run_id, key, value) VALUES (?, ?, ?)", (run_id, key, value))
            await conn.commit()

    async def _get_run_state(self, run_id: str, key: str) -> Optional[str]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT value FROM run_state WHERE run_id = ? AND key = ?", (run_id, key)) as cursor:
                row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_swarm_running(self, run_id: str, running: bool):
        await self._set_run_state(run_id, 'swarm_running', '1' if running else '0')
        if not running:
            await self.set_pause_signal(run_id, False)

    async def is_swarm_running(self, run_id: str) -> bool:
        state = await self._get_run_state(run_id, 'swarm_running')
        return state == '1'

    async def set_pause_signal(self, run_id: str, requested: bool):
        await self._set_run_state(run_id, 'pause_requested', '1' if requested else '0')

    async def should_pause(self, run_id: str) -> bool:
        state = await self._get_run_state(run_id, 'pause_requested')
        return state == '1'

    async def set_active_task(self, run_id: str, task_number: Optional[int]):
        await self._set_run_state(run_id, 'active_task', str(task_number) if task_number is not None else '')

    async def get_active_task(self, run_id: str) -> Optional[int]:
        task_str = await self._get_run_state(run_id, 'active_task')
        return int(task_str) if task_str and task_str.isdigit() else None

    # --- Plan Operations (Per Run) ---
    async def add_plan_step(self, run_id: str, description: str, step_number: int):
        async with self.get_connection() as conn:
            await conn.execute("INSERT INTO plan (run_id, description, step_number) VALUES (?, ?, ?)", (run_id, description, step_number))
            await conn.commit()

    async def get_next_step(self, run_id: str) -> Optional[Dict]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT * FROM plan WHERE run_id = ? AND status IN ('TODO', 'IN_PROGRESS') ORDER BY step_number LIMIT 1", (run_id,)) as cursor:
                row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_step_status(self, step_id: int, status: str, result: Optional[str] = None):
        async with self.get_connection() as conn:
            if result:
                await conn.execute("UPDATE plan SET status = ?, result = ? WHERE id = ?", (status, result, step_id))
            else:
                await conn.execute("UPDATE plan SET status = ? WHERE id = ?", (status, step_id))
            await conn.commit()

    async def get_all_plan(self, run_id: str) -> pd.DataFrame:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT * FROM plan WHERE run_id = ? ORDER BY step_number", (run_id,)) as cursor:
                rows = await cursor.fetchall()
        return pd.DataFrame([dict(row) for row in rows])

    async def get_max_step_number(self, run_id: str) -> int:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT COALESCE(MAX(step_number), 0) FROM plan WHERE run_id = ?", (run_id,)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    async def get_step_id_by_number(self, run_id: str, step_number: int) -> Optional[int]:
        """Возвращает первичный ключ (id) шага по его порядковому номеру."""
        async with self.get_connection() as conn:
            async with conn.execute("SELECT id FROM plan WHERE run_id = ? AND step_number = ?", (run_id, step_number)) as cursor:
                row = await cursor.fetchone()
        return row["id"] if row else None

    async def get_existing_step_numbers(self, run_id: str) -> set[int]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT step_number FROM plan WHERE run_id = ?", (run_id,)) as cursor:
                rows = await cursor.fetchall()
        return {int(r["step_number"]) for r in rows}

    async def get_done_results_text(self, run_id: str) -> str:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT step_number, description, result FROM plan WHERE run_id = ? AND status='DONE' ORDER BY step_number", (run_id,)) as cursor:
                rows = await cursor.fetchall()
        if not rows:
            return "No completed steps yet."
        return "COMPLETED RESEARCH STEPS:\n" + "\n".join(f"Step {row['step_number']}: {row['description']}\nResult: {row['result']}\n{'-'*20}" for row in rows)

    # --- Message Persistence (Per Run) ---
    async def save_message(self, run_id: str, role: str, content: str, tool_calls: Optional[list] = None, tool_call_id: Optional[str] = None, sender: Optional[str] = None, session_id: str = "default"):
        task_num = await self.get_active_task(run_id)
        async with self.get_connection() as conn:
            await conn.execute("INSERT INTO messages (run_id, role, content, tool_calls, tool_call_id, sender, session_id, task_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (run_id, role, content, json.dumps(tool_calls) if tool_calls else None, tool_call_id, sender, session_id, task_num))
            await conn.commit()

    async def load_messages(self, run_id: str) -> List[ChatMessage]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT * FROM messages WHERE run_id = ? ORDER BY id", (run_id,)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_chat_message(row) for row in rows]

    async def get_messages_for_task(self, run_id: str, task_number: int) -> List[ChatMessage]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT * FROM messages WHERE run_id = ? AND task_number = ? ORDER BY id", (run_id, task_number)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_chat_message(row) for row in rows]

    def _row_to_chat_message(self, row) -> ChatMessage:
        data = dict(row)
        if data.get("tool_calls"):
            try:
                data["tool_calls"] = json.loads(data["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                data["tool_calls"] = None
        return ChatMessage(**data)

    # --- Approvals (Per Run) ---
    async def get_pending_approvals(self, run_id: str) -> pd.DataFrame:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT * FROM approvals WHERE run_id = ? AND approved = 0", (run_id,)) as cursor:
                rows = await cursor.fetchall()
        return pd.DataFrame([dict(row) for row in rows])

    async def update_approval_status(self, run_id: str, command_hash: str, status: int):
        async with self.get_connection() as conn:
            await conn.execute("UPDATE approvals SET approved=? WHERE run_id=? AND command_hash=?", (status, run_id, command_hash))
            await conn.commit()

    async def request_approval(self, run_id: str, command_hash: str, command_text: str):
        async with self.get_connection() as conn:
            await conn.execute("INSERT OR IGNORE INTO approvals (run_id, command_hash, command_text, approved) VALUES (?, ?, ?, 0)", (run_id, command_hash, command_text))
            await conn.commit()

    async def get_approval_status(self, run_id: str, command_hash: str) -> Optional[int]:
        async with self.get_connection() as conn:
            async with conn.execute("SELECT approved FROM approvals WHERE run_id = ? AND command_hash = ?", (run_id, command_hash)) as cursor:
                row = await cursor.fetchone()
        return row["approved"] if row else None
        
    # --- Complex Operations ---
    async def insert_plan_steps_atomic(self, run_id: str, new_steps: List[str], insert_after_step: int):
        logger.info("DB: Inserting %d steps after step %d for run %s", len(new_steps), insert_after_step, run_id)
        async with self.get_connection() as conn:
            try:
                shift_offset = len(new_steps)
                await conn.execute("UPDATE plan SET step_number = step_number + ? WHERE run_id = ? AND step_number > ?", (shift_offset, run_id, insert_after_step))
                for i, desc in enumerate(new_steps):
                    await conn.execute("INSERT INTO plan (run_id, description, step_number, status) VALUES (?, ?, ?, 'TODO')", (run_id, desc, insert_after_step + 1 + i))
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error("DB: Atomic insert failed: %s", e)
                raise

    async def prune_last_tool_message(self, run_id: str) -> bool:
        async with self.get_connection() as conn:
            try:
                async with conn.execute("SELECT id, content FROM messages WHERE run_id = ? AND role='tool' ORDER BY id DESC LIMIT 1", (run_id,)) as cursor:
                    row = await cursor.fetchone()
                if row:
                    msg_id, content = row["id"], row["content"]
                    content_str = str(content) if content else ""
                    if any(marker.lower() in content_str.lower() for marker in CRITICAL_ERROR_MARKERS):
                        logger.info(f"DB: Skipped pruning msg {msg_id} in run {run_id} due to error markers.")
                        return False
                    pruned_text = "[RAW DATA PRUNED. See summary in next message.]"
                    await conn.execute("UPDATE messages SET content = ? WHERE id = ?", (pruned_text, msg_id))
                    await conn.commit()
                    logger.info("DB: Pruned content of tool message ID %s for run %s", msg_id, run_id)
                    return True
                else:
                    logger.warning("DB: Prune requested for run %s, but no tool message found.", run_id)
                    return False
            except Exception as e:
                logger.error("DB: Failed to prune tool message for run %s: %s", run_id, e)
                return False

    # --- Sync Wrappers для Streamlit (используют asyncio.run) ---
    def authenticate_user_sync(self, username: str, password: str) -> Optional[str]:
        return asyncio.run(self.authenticate_user(username, password))

    def register_user_sync(self, username: str, password: str) -> Optional[str]:
        return asyncio.run(self.register_user(username, password))

    def create_run_sync(self, user_id: str, initial_prompt: str) -> str:
        return asyncio.run(self.create_run(user_id, initial_prompt))

    def is_swarm_running_sync(self, run_id: str) -> bool:
        return asyncio.run(self.is_swarm_running(run_id))

    def set_pause_signal_sync(self, run_id: str, requested: bool):
        return asyncio.run(self.set_pause_signal(run_id, requested))

    def get_user_runs_sync(self, user_id: str) -> List[Dict]:
        return asyncio.run(self.get_user_runs(user_id))

    def load_messages_sync(self, run_id: str) -> List[ChatMessage]:
        return asyncio.run(self.load_messages(run_id))

    def get_all_plan_sync(self, run_id: str) -> pd.DataFrame:
        return asyncio.run(self.get_all_plan(run_id))

    def get_token_usage_sync(self, run_id: str) -> int:
        return asyncio.run(self.get_token_usage(run_id))

    def get_pending_approvals_sync(self, run_id: str) -> pd.DataFrame:
        return asyncio.run(self.get_pending_approvals(run_id))

    def update_approval_status_sync(self, run_id: str, command_hash: str, status: int):
        return asyncio.run(self.update_approval_status(run_id, command_hash, status))

    def _get_run_state_sync(self, run_id: str, key: str) -> Optional[str]:
        return asyncio.run(self._get_run_state(run_id, key))

    def _set_run_state_sync(self, run_id: str, key: str, value: str):
        return asyncio.run(self._set_run_state(run_id, key, value))

    def get_run_title_sync(self, run_id: str) -> Optional[str]:
        return asyncio.run(self.get_run_title(run_id))

    def update_run_title_sync(self, run_id: str, new_title: str):
        return asyncio.run(self.update_run_title(run_id, new_title))

    def set_swarm_running_sync(self, run_id: str, running: bool):
        return asyncio.run(self.set_swarm_running(run_id, running))

    def get_approval_status_sync(self, run_id: str, command_hash: str) -> Optional[int]:
        return asyncio.run(self.get_approval_status(run_id, command_hash))

# Global instance for convenience
db_service = DatabaseService()