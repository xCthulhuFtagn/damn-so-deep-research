import sqlite3
import pandas as pd
import json
import logging
import uuid
import bcrypt
from typing import List, Optional, Dict

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
        self.init_db()

    def get_connection(self):
        # Enables WAL mode for better concurrency every time a connection is made.
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        logger.info("DB init: path=%s", self.db_path)
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, user_id TEXT, title TEXT, status TEXT DEFAULT 'active',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS plan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, step_number INTEGER,
                    description TEXT, status TEXT DEFAULT 'TODO', result TEXT, feedback TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS approvals (
                    command_hash TEXT, run_id TEXT, command_text TEXT, approved INTEGER DEFAULT 0,
                    PRIMARY KEY (run_id, command_hash), FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, role TEXT, content TEXT,
                    tool_calls TEXT, tool_call_id TEXT, sender TEXT, session_id TEXT,
                    task_number INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS run_state (
                    run_id TEXT, key TEXT, value TEXT,
                    PRIMARY KEY (run_id, key), FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # --- Lightweight Migration ---
            def add_column_if_not_exists(table_name, column_name, column_type):
                c.execute(f"PRAGMA table_info({table_name})")
                columns = [info['name'] for info in c.fetchall()]
                if column_name not in columns:
                    logger.info(f"Migrating DB: adding {column_name} to {table_name}")
                    c.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

            add_column_if_not_exists("messages", "run_id", "TEXT")
            add_column_if_not_exists("plan", "run_id", "TEXT")
            add_column_if_not_exists("approvals", "run_id", "TEXT")
            
            # Recreate approvals table if it has the old primary key
            c.execute("PRAGMA table_info(approvals)")
            cols = {info['name']: info for info in c.fetchall()}
            if 'run_id' in cols and not cols['run_id']['pk']:
                logger.info("Recreating approvals table for new composite primary key.")
                c.execute("DROP TABLE approvals")
                c.execute('''
                    CREATE TABLE approvals (
                        command_hash TEXT, run_id TEXT, command_text TEXT, approved INTEGER DEFAULT 0,
                        PRIMARY KEY (run_id, command_hash), FOREIGN KEY(run_id) REFERENCES runs(id)
                    )
                ''')


            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_run_id ON messages(run_id)")
            conn.commit()
        logger.debug("DB init done")

    def clear_db(self):
        logger.info("Clearing all data from all tables")
        with self.get_connection() as conn:
            c = conn.cursor()
            for table in ["plan", "approvals", "messages", "run_state", "runs", "users"]:
                c.execute(f"DELETE FROM {table}")
            conn.commit()
        logger.debug("DB clear done")

    # --- User & Auth Methods ---
    def register_user(self, username: str, password: str) -> Optional[str]:
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user_id = str(uuid.uuid4())
        try:
            with self.get_connection() as conn:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                    (user_id, username, hashed_password.decode('utf-8'))
                )
            return user_id
        except sqlite3.IntegrityError:
            logger.warning(f"Username '{username}' already exists.")
            return None

    def authenticate_user(self, username: str, password: str) -> Optional[str]:
        with self.get_connection() as conn:
            user_row = conn.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,)).fetchone()
        if user_row and bcrypt.checkpw(password.encode('utf-8'), user_row["password_hash"].encode('utf-8')):
            return user_row["id"]
        return None

    # --- Run Management ---
    def create_run(self, user_id: str, initial_prompt: str) -> str:
        run_id = str(uuid.uuid4())
        with self.get_connection() as conn:
            conn.execute("INSERT INTO runs (id, user_id, title) VALUES (?, ?, ?)", (run_id, user_id, initial_prompt))
        return run_id

    def get_run_title(self, run_id: str) -> Optional[str]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT title FROM runs WHERE id = ?", (run_id,)).fetchone()
        return row["title"] if row else None

    def update_run_title(self, run_id: str, new_title: str):
        with self.get_connection() as conn:
            conn.execute("UPDATE runs SET title = ? WHERE id = ?", (new_title, run_id))

    def update_run_status(self, run_id: str, status: str):
        """Update the status of a run (e.g., 'active', 'completed')."""
        with self.get_connection() as conn:
            conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))

    def get_user_runs(self, user_id: str) -> List[Dict]:
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute("SELECT id, title, status, created_at FROM runs WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()]

    # --- State Operations (Per Run) ---
    def _set_run_state(self, run_id: str, key: str, value: str):
        with self.get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO run_state (run_id, key, value) VALUES (?, ?, ?)", (run_id, key, value))

    def _get_run_state(self, run_id: str, key: str) -> Optional[str]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT value FROM run_state WHERE run_id = ? AND key = ?", (run_id, key)).fetchone()
        return row["value"] if row else None

    def set_swarm_running(self, run_id: str, running: bool):
        self._set_run_state(run_id, 'swarm_running', '1' if running else '0')
        if not running: self.set_pause_signal(run_id, False)

    def is_swarm_running(self, run_id: str) -> bool:
        return self._get_run_state(run_id, 'swarm_running') == '1'

    def set_pause_signal(self, run_id: str, requested: bool):
        self._set_run_state(run_id, 'pause_requested', '1' if requested else '0')

    def should_pause(self, run_id: str) -> bool:
        return self._get_run_state(run_id, 'pause_requested') == '1'
        
    def set_active_task(self, run_id: str, task_number: Optional[int]):
        self._set_run_state(run_id, 'active_task', str(task_number) if task_number is not None else '')

    def get_active_task(self, run_id: str) -> Optional[int]:
        task_str = self._get_run_state(run_id, 'active_task')
        return int(task_str) if task_str and task_str.isdigit() else None

    # --- Plan Operations (Per Run) ---
    def add_plan_step(self, run_id: str, description: str, step_number: int):
        with self.get_connection() as conn:
            conn.execute("INSERT INTO plan (run_id, description, step_number) VALUES (?, ?, ?)", (run_id, description, step_number))

    def get_next_step(self, run_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM plan WHERE run_id = ? AND status IN ('TODO', 'IN_PROGRESS') ORDER BY step_number LIMIT 1", (run_id,)).fetchone()
        return dict(row) if row else None

    def update_step_status(self, step_id: int, status: str, result: Optional[str] = None):
        with self.get_connection() as conn:
            if result:
                conn.execute("UPDATE plan SET status = ?, result = ? WHERE id = ?", (status, result, step_id))
            else:
                conn.execute("UPDATE plan SET status = ? WHERE id = ?", (status, step_id))

    def get_all_plan(self, run_id: str) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM plan WHERE run_id = ? ORDER BY step_number", self.get_connection(), params=(run_id,))

    def get_max_step_number(self, run_id: str) -> int:
        with self.get_connection() as conn:
            row = conn.execute("SELECT COALESCE(MAX(step_number), 0) FROM plan WHERE run_id = ?", (run_id,)).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
        
    def get_existing_step_numbers(self, run_id: str) -> set[int]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT step_number FROM plan WHERE run_id = ?", (run_id,)).fetchall()
        return {int(r["step_number"]) for r in rows}

    def get_done_results_text(self, run_id: str) -> str:
        df = pd.read_sql_query("SELECT step_number, description, result FROM plan WHERE run_id = ? AND status='DONE' ORDER BY step_number", self.get_connection(), params=(run_id,))
        if df.empty: return "No completed steps yet."
        return "COMPLETED RESEARCH STEPS:\n" + "\n".join(f"Step {row['step_number']}: {row['description']}\nResult: {row['result']}\n{'-'*20}" for _, row in df.iterrows())

    # --- Message Persistence (Per Run) ---
    def save_message(self, run_id: str, role: str, content: str, tool_calls: Optional[list] = None, tool_call_id: Optional[str] = None, sender: Optional[str] = None, session_id: str = "default"):
        task_num = self.get_active_task(run_id)
        with self.get_connection() as conn:
            conn.execute("INSERT INTO messages (run_id, role, content, tool_calls, tool_call_id, sender, session_id, task_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (run_id, role, content, json.dumps(tool_calls) if tool_calls else None, tool_call_id, sender, session_id, task_num))

    def load_messages(self, run_id: str) -> List[ChatMessage]:
        with self.get_connection() as conn:
            return [self._row_to_chat_message(row) for row in conn.execute("SELECT * FROM messages WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()]
        
    def get_messages_for_task(self, run_id: str, task_number: int) -> List[ChatMessage]:
        with self.get_connection() as conn:
            return [self._row_to_chat_message(row) for row in conn.execute("SELECT * FROM messages WHERE run_id = ? AND task_number = ? ORDER BY id", (run_id, task_number)).fetchall()]
        
    def _row_to_chat_message(self, row: sqlite3.Row) -> ChatMessage:
        data = dict(row)
        if data.get("tool_calls"):
            try:
                data["tool_calls"] = json.loads(data["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                data["tool_calls"] = None
        return ChatMessage(**data)

    # --- Approvals (Per Run) ---
    def get_pending_approvals(self, run_id: str) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM approvals WHERE run_id = ? AND approved = 0", self.get_connection(), params=(run_id,))

    def update_approval_status(self, run_id: str, command_hash: str, status: int):
        with self.get_connection() as conn:
            conn.execute("UPDATE approvals SET approved=? WHERE run_id=? AND command_hash=?", (status, run_id, command_hash))
            
    def request_approval(self, run_id: str, command_hash: str, command_text: str):
        with self.get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO approvals (run_id, command_hash, command_text, approved) VALUES (?, ?, ?, 0)", (run_id, command_hash, command_text))

    def get_approval_status(self, run_id: str, command_hash: str) -> Optional[int]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT approved FROM approvals WHERE run_id = ? AND command_hash = ?", (run_id, command_hash)).fetchone()
        return row["approved"] if row else None
        
    # --- Complex Operations ---
    def insert_plan_steps_atomic(self, run_id: str, new_steps: List[str], insert_after_step: int):
        logger.info("DB: Inserting %d steps after step %d for run %s", len(new_steps), insert_after_step, run_id)
        with self.get_connection() as conn:
            try:
                shift_offset = len(new_steps)
                conn.execute("UPDATE plan SET step_number = step_number + ? WHERE run_id = ? AND step_number > ?", (shift_offset, run_id, insert_after_step))
                for i, desc in enumerate(new_steps):
                    conn.execute("INSERT INTO plan (run_id, description, step_number, status) VALUES (?, ?, ?, 'TODO')", (run_id, desc, insert_after_step + 1 + i))
                conn.commit()
            except Exception as e:
                conn.rollback(); logger.error("DB: Atomic insert failed: %s", e); raise

    def prune_last_tool_message(self, run_id: str) -> bool:
        with self.get_connection() as conn:
            try:
                c = conn.cursor()
                c.execute("SELECT id, content FROM messages WHERE run_id = ? AND role='tool' ORDER BY id DESC LIMIT 1", (run_id,))
                row = c.fetchone()
                if row:
                    msg_id, content = row["id"], row["content"]
                    content_str = str(content) if content else ""
                    if any(marker.lower() in content_str.lower() for marker in CRITICAL_ERROR_MARKERS):
                        logger.info(f"DB: Skipped pruning msg {msg_id} in run {run_id} due to error markers.")
                        return False
                    pruned_text = "[RAW DATA PRUNED. See summary in next message.]"
                    c.execute("UPDATE messages SET content = ? WHERE id = ?", (pruned_text, msg_id))
                    conn.commit()
                    logger.info("DB: Pruned content of tool message ID %s for run %s", msg_id, run_id)
                    return True
                else:
                    logger.warning("DB: Prune requested for run %s, but no tool message found.", run_id)
                    return False
            except Exception as e: logger.error("DB: Failed to prune tool message for run %s: %s", run_id, e); return False

# Global instance for convenience
db_service = DatabaseService()