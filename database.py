import sqlite3
import pandas as pd
import json
from config import DB_PATH 
import logging

from logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

def init_db():
    logger.info("DB init: path=%s", DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Таблица Плана
    # status: TODO, IN_PROGRESS, DONE, FAILED
    c.execute('''CREATE TABLE IF NOT EXISTS plan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_number INTEGER,
                    description TEXT,
                    status TEXT DEFAULT 'TODO', 
                    result TEXT,
                    feedback TEXT
                )''')
    
    # Таблица Одобрений для терминала
    c.execute('''CREATE TABLE IF NOT EXISTS approvals (
                    command_hash TEXT PRIMARY KEY,
                    command_text TEXT,
                    approved BOOLEAN DEFAULT 0
                )''')
    
    # Таблица Истории Чата
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    sender TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
    
    # Таблица Глобального Состояния
    c.execute('''CREATE TABLE IF NOT EXISTS global_state (
                    key TEXT PRIMARY KEY,
                    value INTEGER
                )''')
    
    # Инициализация дефолтных значений, если их нет
    c.execute("INSERT OR IGNORE INTO global_state (key, value) VALUES ('swarm_running', 0)")
    c.execute("INSERT OR IGNORE INTO global_state (key, value) VALUES ('stop_requested', 0)")
    
    conn.commit()
    conn.close()
    logger.debug("DB init done")

def clear_db():
    """Очистка базы для новой сессии"""
    logger.info("DB clear: deleting plan + approvals + messages")
    conn = sqlite3.connect(DB_PATH)
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

def set_swarm_running(running: bool):
    """Sets the swarm_running flag in global_state."""
    val = 1 if running else 0
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE global_state SET value = ? WHERE key = 'swarm_running'", (val,))
    # Если мы останавливаем рой, сбрасываем сигнал остановки
    if not running:
        c.execute("UPDATE global_state SET value = 0 WHERE key = 'stop_requested'")
    conn.commit()
    conn.close()
    logger.debug("DB set_swarm_running: %s", running)

def is_swarm_running() -> bool:
    """Checks if the swarm is currently running."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT value FROM global_state WHERE key = 'swarm_running'").fetchone()
    conn.close()
    return bool(row[0]) if row else False

def set_stop_signal(requested: bool):
    """Sets the stop_requested flag in global_state."""
    val = 1 if requested else 0
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE global_state SET value = ? WHERE key = 'stop_requested'", (val,))
    conn.commit()
    conn.close()
    logger.info("DB set_stop_signal: %s", requested)

def should_stop() -> bool:
    """Checks if a stop has been requested."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT value FROM global_state WHERE key = 'stop_requested'").fetchone()
    conn.close()
    return bool(row[0]) if row else False

# --- Plan Operations ---

def add_plan_step(description, step_number):
    logger.info("DB add_plan_step: step_number=%s desc_chars=%s", step_number, len(description or ""))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Проверяем дубликаты по номеру шага, если нужно, или просто вставляем
    c.execute("INSERT INTO plan (description, step_number) VALUES (?, ?)", (description, step_number))
    conn.commit()
    conn.close()

def get_next_step():
    """Возвращает первый невыполненный шаг"""
    conn = sqlite3.connect(DB_PATH)
    # Берем TODO или IN_PROGRESS, сортируем по номеру
    df = pd.read_sql_query("SELECT * FROM plan WHERE status IN ('TODO', 'IN_PROGRESS') ORDER BY step_number LIMIT 1", conn)
    conn.close()
    logger.debug("DB get_next_step: found=%s", not df.empty)
    return df.iloc[0] if not df.empty else None

def update_step_status(step_id, status, result=None):
    logger.info(
        "DB update_step_status: step_id=%s status=%s has_result=%s",
        step_id,
        status,
        bool(result),
    )
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if result:
        c.execute("UPDATE plan SET status = ?, result = ? WHERE id = ?", (status, result, step_id))
    else:
        c.execute("UPDATE plan SET status = ? WHERE id = ?", (status, step_id))
    conn.commit()
    conn.close()

def get_all_plan():
    """Для отображения в UI"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM plan ORDER BY step_number", conn)
    conn.close()
    logger.debug("DB get_all_plan: rows=%s", len(df))
    return df


def get_max_step_number() -> int:
    """Returns the maximum step_number in the plan (0 if empty)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT COALESCE(MAX(step_number), 0) FROM plan").fetchone()
    conn.close()
    return int(row[0]) if row and row[0] is not None else 0


def get_existing_step_numbers() -> set[int]:
    """Returns a set of all step_number values currently in the plan."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT step_number FROM plan").fetchall()
    conn.close()
    out: set[int] = set()
    for (num,) in rows:
        try:
            out.add(int(num))
        except Exception:
            continue
    return out

def get_completed_steps_count():
    """Для логики очистки памяти"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM plan WHERE status='DONE'").fetchone()[0]
    conn.close()
    logger.debug("DB get_completed_steps_count: count=%s", count)
    return count

def get_done_results_text():
    """Возвращает контекст выполненных шагов для агентов"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT step_number, description, result FROM plan WHERE status='DONE' ORDER BY step_number", conn)
    conn.close()
    
    if df.empty:
        logger.debug("DB get_done_results_text: empty")
        return "No completed steps yet."
    
    text = "COMPLETED RESEARCH STEPS:\n"
    for _, row in df.iterrows():
        text += f"Step {row['step_number']}: {row['description']}\nResult: {row['result']}\n{'-'*20}\n"
    logger.debug("DB get_done_results_text: steps=%s chars=%s", len(df), len(text))
    return text

# --- Message Persistence ---

def save_message(role: str, content: str, tool_calls: list = None, tool_call_id: str = None, sender: str = None):
    """Saves a message to the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
    c.execute(
        "INSERT INTO messages (role, content, tool_calls, tool_call_id, sender) VALUES (?, ?, ?, ?, ?)",
        (role, content, tool_calls_json, tool_call_id, sender)
    )
    conn.commit()
    conn.close()
    logger.debug("DB save_message: role=%s content_chars=%s", role, len(content or ""))

def load_messages():
    """Loads all messages from the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content, tool_calls, tool_call_id, sender FROM messages ORDER BY id")
    rows = c.fetchall()
    conn.close()
    
    messages = []
    for row in rows:
        role, content, tool_calls_json, tool_call_id, sender = row
        msg = {
            "role": role,
            "content": content,
            "sender": sender,
            "tool_call_id": tool_call_id
        }
        if tool_calls_json:
            msg["tool_calls"] = json.loads(tool_calls_json)
        messages.append(msg)
    
    logger.debug("DB load_messages: count=%s", len(messages))
    return messages

def get_active_step_description() -> str:
    """Returns the description of the current active step."""
    conn = sqlite3.connect(DB_PATH)
    # Get the IN_PROGRESS step, or the first TODO step
    df = pd.read_sql_query("SELECT description FROM plan WHERE status IN ('IN_PROGRESS', 'TODO') ORDER BY status ASC, step_number ASC LIMIT 1", conn)
    conn.close()
    
    if not df.empty:
        return str(df.iloc[0]['description'])
    return "No active research step found. Waiting for plan."

def load_agent_window(limit: int = 10):
    """
    Loads a minimal context window:
    1. The FIRST message (User Prompt)
    2. The LAST N messages (Recent conversation history)
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Get First Message (ID=1 usually, or just LIMIT 1)
    c.execute("SELECT role, content, tool_calls, tool_call_id, sender FROM messages ORDER BY id ASC LIMIT 1")
    first_row = c.fetchall()
    
    # 2. Get Last N Messages
    # We use a subquery to order by ID desc first to get the last N, then re-order ASC
    c.execute(f'''
        SELECT role, content, tool_calls, tool_call_id, sender 
        FROM (
            SELECT role, content, tool_calls, tool_call_id, sender, id
            FROM messages 
            ORDER BY id DESC 
            LIMIT ?
        ) 
        ORDER BY id ASC
    ''', (limit,))
    last_rows = c.fetchall()
    
    conn.close()
    
    # Combine and Deduplicate (if total messages < limit)
    # We'll use a set of signatures (role+content+sender) or just handle list logic carefully
    
    all_rows = []
    if first_row:
        all_rows.extend(first_row)
    
    # If first_row is also in last_rows (short history), avoid duplicating
    # Simple check: if len(last_rows) < limit, likely overlap might happen if total is small.
    # But strictly speaking, if we just blindly append, we might duplicate the first message if it's also in the last N.
    # Let's simple check:
    
    for r in last_rows:
        if first_row and r == first_row[0]:
            continue # Skip if it's the exact same row content as the first one
        all_rows.append(r)
        
    messages = []
    for row in all_rows:
        role, content, tool_calls_json, tool_call_id, sender = row
        msg = {
            "role": role,
            "content": content,
            "sender": sender,
            "tool_call_id": tool_call_id
        }
        if tool_calls_json:
            try:
                msg["tool_calls"] = json.loads(tool_calls_json)
            except:
                pass
        messages.append(msg)
        
    logger.debug("DB load_agent_window: count=%s", len(messages))
    return messages

def clear_messages():
    """Clears all messages from the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM messages")
    conn.commit()
    conn.close()
    logger.debug("DB clear_messages done")


def has_pending_approvals() -> bool:
    """Returns True if there are terminal commands awaiting approval."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT COUNT(*) FROM approvals WHERE approved = 0").fetchone()
    conn.close()
    return bool(row[0]) if row else False


def prune_messages_for_ui():
    """
    Reduce chat noise without breaking user-visible history.
    Keeps:
      - user messages
      - assistant messages with non-empty content and without tool_calls
      - system messages that look like errors (so UI can show failures)
    Removes:
      - tool messages
      - assistant tool-call wrapper messages (tool_calls != NULL)
      - empty assistant messages
      - non-error system messages
    """
    conn = sqlite3.connect(DB_PATH)
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
    logger.debug("DB prune_messages_for_ui done")
