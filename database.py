import sqlite3
import pandas as pd
from config import DB_NAME

def init_db():
    conn = sqlite3.connect(DB_NAME)
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
    
    conn.commit()
    conn.close()

def clear_db():
    """Очистка базы для новой сессии"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM plan")
    c.execute("DELETE FROM approvals")
    conn.commit()
    conn.close()

# --- Plan Operations ---

def add_plan_step(description, step_number):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Проверяем дубликаты по номеру шага, если нужно, или просто вставляем
    c.execute("INSERT INTO plan (description, step_number) VALUES (?, ?)", (description, step_number))
    conn.commit()
    conn.close()

def get_next_step():
    """Возвращает первый невыполненный шаг"""
    conn = sqlite3.connect(DB_NAME)
    # Берем TODO или IN_PROGRESS, сортируем по номеру
    df = pd.read_sql_query("SELECT * FROM plan WHERE status IN ('TODO', 'IN_PROGRESS') ORDER BY step_number LIMIT 1", conn)
    conn.close()
    return df.iloc[0] if not df.empty else None

def update_step_status(step_id, status, result=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if result:
        c.execute("UPDATE plan SET status = ?, result = ? WHERE id = ?", (status, result, step_id))
    else:
        c.execute("UPDATE plan SET status = ? WHERE id = ?", (status, step_id))
    conn.commit()
    conn.close()

def get_all_plan():
    """Для отображения в UI"""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM plan ORDER BY step_number", conn)
    conn.close()
    return df

def get_completed_steps_count():
    """Для логики очистки памяти"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM plan WHERE status='DONE'").fetchone()[0]
    conn.close()
    return count

def get_done_results_text():
    """Возвращает контекст выполненных шагов для агентов"""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT step_number, description, result FROM plan WHERE status='DONE' ORDER BY step_number", conn)
    conn.close()
    
    if df.empty:
        return "No completed steps yet."
    
    text = "COMPLETED RESEARCH STEPS:\n"
    for _, row in df.iterrows():
        text += f"Step {row['step_number']}: {row['description']}\nResult: {row['result']}\n{'-'*20}\n"
    return text

