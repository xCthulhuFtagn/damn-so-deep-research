import sqlite3
import threading
import pandas as pd
import json
import logging
from typing import List, Optional, Any, Dict
from config import DB_PATH 
from logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


# Marker strings that indicate a system failure or critical error.
# If any of these are found in the tool output, we MUST NOT prune it.
CRITICAL_ERROR_MARKERS = [
    "Error:",
    "Exception:",
    "Traceback",
    "Timeout",
    "ConnectionRefused",
    "Ошибка поискового движка", # Specific to intelligent_web_search
    "failed to", # General failure indicator
    "status code:", # often appears in HTTP errors
]

class DatabaseManager:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        # Оптимизация: сначала проверяем без лока (быстро)
        if cls._instance is None:
            with cls._instance_lock:
                # Вторая проверка под локом (Double-Checked Locking)
                if cls._instance is None:
                    cls._instance = super(DatabaseManager, cls).__new__(cls)
                    
                    # --- ИНИЦИАЛИЗАЦИЯ ПРЯМО ЗДЕСЬ ---
                    # Делаем всё здесь, чтобы гарантировать выполнение 1 раз
                    # и под защитой лока.
                    cls._instance.db_path = DB_PATH
                    cls._instance._active_task_number = None
                    cls._instance.init_db() 
                    # ---------------------------------
                    
        return cls._instance

    def __init__(self):
        # __init__ будет вызываться Python'ом каждый раз при DatabaseManager(),
        # но нам он больше не нужен, так как всё сделано в __new__.
        pass

    def get_connection(self):
        return sqlite3.connect(self.db_path, timeout=30)

    def init_db(self):
        logger.info("DB init: path=%s", self.db_path)
        conn = self.get_connection()
        c = conn.cursor()
        
            # Plan Table
        c.execute('''CREATE TABLE IF NOT EXISTS plan (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        step_number INTEGER,
                        description TEXT,
                        status TEXT DEFAULT 'TODO', 
                        result TEXT,
                        feedback TEXT
                    )''')
        
            # Approvals Table
        c.execute('''CREATE TABLE IF NOT EXISTS approvals (
                        command_hash TEXT PRIMARY KEY,
                        command_text TEXT,
                        approved BOOLEAN DEFAULT 0
                    )''')
        
            # Messages Table (Updated with session_id and task_number)
        c.execute('''CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        role TEXT,
                        content TEXT,
                        tool_calls TEXT,
                        tool_call_id TEXT,
                        sender TEXT,
                            session_id TEXT DEFAULT 'default',
                            task_number INTEGER,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    
        # Check for new columns in messages if table exists (migration)
        c.execute("PRAGMA table_info(messages)")
        columns = [info[1] for info in c.fetchall()]
        if 'session_id' not in columns:
            logger.info("Migrating DB: adding session_id to messages")
            c.execute("ALTER TABLE messages ADD COLUMN session_id TEXT DEFAULT 'default'")
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)")
        
        if 'task_number' not in columns:
            logger.info("Migrating DB: adding task_number to messages")
            c.execute("ALTER TABLE messages ADD COLUMN task_number INTEGER")
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_task_number ON messages(task_number)")
            
        # Global State Table
        c.execute('''CREATE TABLE IF NOT EXISTS global_state (
                        key TEXT PRIMARY KEY,
                        value INTEGER
                    )''')
        
        c.execute("INSERT OR IGNORE INTO global_state (key, value) VALUES ('swarm_running', 0)")
        c.execute("INSERT OR IGNORE INTO global_state (key, value) VALUES ('stop_requested', 0)")
        
        conn.commit()
        conn.close()
        logger.debug("DB init done")

    def clear_db(self):
        """Очистка базы для новой сессии"""
        logger.info("DB clear: deleting plan + approvals + messages")
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM plan")
        c.execute("DELETE FROM approvals")
        c.execute("DELETE FROM messages")
        # Сбрасываем флаги в global_state
        c.execute("UPDATE global_state SET value = 0 WHERE key = 'swarm_running'")
        c.execute("UPDATE global_state SET value = 0 WHERE key = 'stop_requested'")
        conn.commit()
        conn.close()
        logger.debug("DB clear done")

# --- Global State Operations ---

    def set_swarm_running(self, running: bool):
        val = 1 if running else 0
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("UPDATE global_state SET value = ? WHERE key = 'swarm_running'", (val,))
        if not running:
            c.execute("UPDATE global_state SET value = 0 WHERE key = 'stop_requested'")
        conn.commit()
        conn.close()

    def is_swarm_running(self) -> bool:
        conn = self.get_connection()
        c = conn.cursor()
        row = c.execute("SELECT value FROM global_state WHERE key = 'swarm_running'").fetchone()
        conn.close()
        return bool(row[0]) if row else False

    def set_stop_signal(self, requested: bool):
        val = 1 if requested else 0
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("UPDATE global_state SET value = ? WHERE key = 'stop_requested'", (val,))
        conn.commit()
        conn.close()

    def should_stop(self) -> bool:
        conn = self.get_connection()
        c = conn.cursor()
        row = c.execute("SELECT value FROM global_state WHERE key = 'stop_requested'").fetchone()
        conn.close()
        return bool(row[0]) if row else False

    # --- Task Context ---

    def set_active_task(self, task_number: Optional[int]):
        self._active_task_number = task_number
        logger.debug("Set active task number: %s", task_number)

    def get_active_task(self) -> Optional[int]:
        return self._active_task_number

    @classmethod
    def get_instance(cls) -> "DatabaseManager":
        """Return the singleton instance (alias for cls())."""
        return cls()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (use for testing resets)."""
        with cls._instance_lock:
            cls._instance = None

# --- Plan Operations ---

    def add_plan_step(self, description, step_number):
        logger.info("DB add_plan_step: step_number=%s", step_number)
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO plan (description, step_number) VALUES (?, ?)", (description, step_number))
        conn.commit()
        conn.close()

    def get_next_step(self):
        conn = self.get_connection()
        df = pd.read_sql_query("SELECT * FROM plan WHERE status IN ('TODO', 'IN_PROGRESS') ORDER BY step_number LIMIT 1", conn)
        conn.close()
        return df.iloc[0] if not df.empty else None

    def update_step_status(self, step_id, status, result=None):
        logger.info("DB update_step_status: step_id=%s status=%s", step_id, status)
        conn = self.get_connection()
        c = conn.cursor()
        if result:
            c.execute("UPDATE plan SET status = ?, result = ? WHERE id = ?", (status, result, step_id))
        else:
            c.execute("UPDATE plan SET status = ? WHERE id = ?", (status, step_id))
        conn.commit()
        conn.close()

    def get_all_plan(self):
        conn = self.get_connection()
        df = pd.read_sql_query("SELECT * FROM plan ORDER BY step_number", conn)
        conn.close()
        return df

    def get_max_step_number(self) -> int:
        conn = self.get_connection()
        c = conn.cursor()
        row = c.execute("SELECT COALESCE(MAX(step_number), 0) FROM plan").fetchone()
        conn.close()
        return int(row[0]) if row and row[0] is not None else 0

    def get_existing_step_numbers(self) -> set[int]:
        conn = self.get_connection()
        c = conn.cursor()
        rows = c.execute("SELECT step_number FROM plan").fetchall()
        conn.close()
        return {int(r[0]) for r in rows}

    def get_completed_steps_count(self):
        conn = self.get_connection()
        c = conn.cursor()
        count = c.execute("SELECT COUNT(*) FROM plan WHERE status='DONE'").fetchone()[0]
        conn.close()
        return count

    def get_done_results_text(self):
        conn = self.get_connection()
        df = pd.read_sql_query("SELECT step_number, description, result FROM plan WHERE status='DONE' ORDER BY step_number", conn)
        conn.close()
        if df.empty:
            return "No completed steps yet."
        text = "COMPLETED RESEARCH STEPS:\n"
        for _, row in df.iterrows():
            text += f"Step {row['step_number']}: {row['description']}\nResult: {row['result']}\n{'-'*20}\n"
        return text

    def get_plan_summary(self) -> str:
        """Returns a compact status list of all steps."""
        df = self.get_all_plan()
        if df.empty:
            return "Plan is empty."
        summary = []
        for _, row in df.iterrows():
            summary.append(f"Step {row['step_number']}: {row['status']} - {row['description']}")
        return "\n".join(summary)

    def get_active_step_description(self) -> str:
        """Return the description of the current active step from the plan.

        Looks for the next actionable step (IN_PROGRESS or TODO) and returns its description.
        Falls back to generic messages if no active step is found.
        """
        # Reuse existing in-memory plan overview
        df = self.get_all_plan()
        if df.empty:
            return "Waiting for plan."

        conn = self.get_connection()
        try:
            active_df = pd.read_sql_query(
                "SELECT description FROM plan WHERE status IN ('IN_PROGRESS', 'TODO') "
                "ORDER BY status ASC, step_number ASC LIMIT 1",
                conn
            )
        finally:
            conn.close()

        if not active_df.empty:
            return str(active_df.iloc[0]['description'])
        return "No active research step."

# --- Message Persistence ---

    def save_message(self, role: str, content: str, tool_calls: list = None, tool_call_id: str = None, sender: str = None, session_id: str = "default"):
        conn = self.get_connection()
        c = conn.cursor()
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        
        # Use explicit task_number if provided via set_active_task (Task-Scoped Memory)
        task_num = self.get_active_task()
        
        c.execute(
                "INSERT INTO messages (role, content, tool_calls, tool_call_id, sender, session_id, task_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (role, content, tool_calls_json, tool_call_id, sender, session_id, task_num)
        )
        conn.commit()
        conn.close()
        logger.debug("DB save_message: role=%s session=%s task=%s", role, session_id, task_num)

    def load_messages(self, session_id: str = None):
        """Loads messages, optionally filtering by session_id."""
        conn = self.get_connection()
        c = conn.cursor()
        if session_id:
            c.execute("SELECT role, content, tool_calls, tool_call_id, sender, session_id, task_number FROM messages WHERE session_id = ? ORDER BY id", (session_id,))
        else:
            c.execute("SELECT role, content, tool_calls, tool_call_id, sender, session_id, task_number FROM messages ORDER BY id")
        rows = c.fetchall()
        conn.close()
        return self._rows_to_dicts(rows)

    def get_messages_for_task(self, session_id: str, task_number: int):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT role, content, tool_calls, tool_call_id, sender, session_id, task_number FROM messages WHERE session_id = ? AND task_number = ? ORDER BY id", 
            (session_id, task_number)
        )
        rows = c.fetchall()
        conn.close()
        return self._rows_to_dicts(rows)

    def get_last_n_messages(self, session_id: str, n: int):
        conn = self.get_connection()
        c = conn.cursor()
        # Subquery to get last N then order ASC
        c.execute(f'''
        SELECT role, content, tool_calls, tool_call_id, sender, session_id, task_number 
        FROM (
                SELECT * FROM messages 
                WHERE session_id = ?
            ORDER BY id DESC 
            LIMIT ?
        ) 
        ORDER BY id ASC
        ''', (session_id, n))
        rows = c.fetchall()
        conn.close()
        return self._rows_to_dicts(rows)

    def _rows_to_dicts(self, rows):
        messages = []
        for row in rows:
            role, content, tool_calls_json, tool_call_id, sender, session_id, task_number = row
            msg = {
                "role": role,
                "content": content if content is not None else "", # Добавлена эта часть
                "sender": sender,
                    "tool_call_id": tool_call_id,
                    "session_id": session_id,
                    "task_number": task_number
            }
            if tool_calls_json:
                try:
                    msg["tool_calls"] = json.loads(tool_calls_json)
                except:
                    pass
            messages.append(msg)
        return messages

    def get_initial_user_prompt(self, session_id: str = None) -> str | None:
        conn = self.get_connection()
        c = conn.cursor()
        query = "SELECT content FROM messages WHERE role='user'"
        params = []
        if session_id:
            query += " AND session_id=?"
            params.append(session_id)
        query += " ORDER BY id ASC LIMIT 1"
        
        c.execute(query, tuple(params))
        row = c.fetchone()
        conn.close()
        return str(row[0]) if row and row[0] else None
    
    def prune_last_tool_message(self) -> bool:
        """
        Conditionally prunes the last tool message.
        - Deletes content if it appears to be successful data (to save tokens).
        - PRESERVES content if it contains error markers (so Strategist can fix it).
        """
        conn = self.get_connection()
        c = conn.cursor()
        try:
            # 1. Find the last tool message and fetch its content
            c.execute("SELECT id, content FROM messages WHERE role='tool' ORDER BY id DESC LIMIT 1")
            row = c.fetchone()
            
            if row:
                msg_id, content = row
                content_str = str(content) if content else ""

                # 2. Check for Error Markers (Safety Check)
                # Defined as a class constant
                if any(marker.lower() in content_str.lower() for marker in CRITICAL_ERROR_MARKERS):
                    logger.info(f"DB: Skipped pruning for msg ID {msg_id} due to detected error markers.")
                    return False

                # 3. If safe, replace heavy content with a placeholder
                pruned_text = "[RAW DATA PRUNED. See summary in the next message arguments.]"
                c.execute("UPDATE messages SET content = ? WHERE id = ?", (pruned_text, msg_id))
                conn.commit()
                logger.info("DB: Pruned raw content of tool message ID %s", msg_id)
                return True
            else:
                logger.warning("DB: Prune requested, but no tool message found.")
                return False
                
        except Exception as e:
            logger.error("DB: Failed to prune tool message: %s", e)
            return False
        finally:
            conn.close()

    # --- Approvals ---

    def has_pending_approvals(self) -> bool:
        conn = self.get_connection()
        c = conn.cursor()
        row = c.execute("SELECT COUNT(*) FROM approvals WHERE approved = 0").fetchone()
        conn.close()
        return bool(row[0]) if row else False

    # --- UI Helpers ---

    def prune_messages_for_ui(self):
        """Clean up database messages."""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute(
            """
            DELETE FROM messages
            WHERE
            role = 'tool'
            OR (role = 'assistant' AND tool_calls IS NOT NULL)
            OR (role = 'assistant' AND (content IS NULL OR TRIM(content) = ''))
            OR (
                role = 'system'
                AND (
                content IS NULL
                OR (content NOT LIKE '%Error%' AND LOWER(content) NOT LIKE '%failed%')
                )
            )
            """
        )
        conn.commit()
        conn.close()


    def get_pending_approvals_count(self) -> int:
        """Return number of pending terminal approvals (approved = 0)."""
        try:
            conn = self.get_connection()
            c = conn.cursor()
            row = c.execute("SELECT COUNT(*) FROM approvals WHERE approved = 0").fetchone()
            conn.close()
            return int(row[0]) if row and row[0] is not None else 0
        except Exception:
            logger.exception("DatabaseManager: failed to count pending approvals")
            return 0

    def get_pending_approvals(self) -> pd.DataFrame:
        conn = self.get_connection()
        df = pd.read_sql_query("SELECT * FROM approvals WHERE approved = 0", conn)
        conn.close()
        return df

    def update_approval_status(self, command_hash: str, status: int):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("UPDATE approvals SET approved=? WHERE command_hash=?", (status, command_hash))
        conn.commit()
        conn.close()

# --- Backward Compatibility Wrappers (Proxies to db instance) ---

# Wrapper functions have been removed in favor of direct singleton access via `db`:
# Access DatabaseManager through the singleton instance (e.g., `DatabaseManager.get_instance().init_db()`).