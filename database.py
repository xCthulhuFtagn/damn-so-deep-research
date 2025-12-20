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
                    sender TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
    
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
    conn.commit()
    conn.close()
    logger.debug("DB clear done")

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

def save_message(role: str, content: str, tool_calls: list = None, sender: str = None):
    """Saves a message to the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
    c.execute(
        "INSERT INTO messages (role, content, tool_calls, sender) VALUES (?, ?, ?, ?)",
        (role, content, tool_calls_json, sender)
    )
    conn.commit()
    conn.close()
    logger.debug("DB save_message: role=%s content_chars=%s", role, len(content or ""))

def load_messages():
    """Loads all messages from the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content, tool_calls, sender FROM messages ORDER BY id")
    rows = c.fetchall()
    conn.close()
    
    messages = []
    for row in rows:
        role, content, tool_calls_json, sender = row
        msg = {
            "role": role,
            "content": content,
            "sender": sender
        }
        if tool_calls_json:
            msg["tool_calls"] = json.loads(tool_calls_json)
        messages.append(msg)
    
    logger.debug("DB load_messages: count=%s", len(messages))
    return messages
