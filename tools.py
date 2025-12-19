import subprocess
import hashlib
import sqlite3
from duckduckgo_search import DDGS
from config import DB_NAME
import database

# --- External Tools ---

def web_search(query: str):
    """Использует DuckDuckGo для поиска в интернете."""
    print(f"DEBUG: Searching for {query}")
    try:
        results = DDGS().text(query, max_results=3)
        return str(results)
    except Exception as e:
        return f"Error searching: {e}"

def read_file(file_path: str):
    """Читает локальный файл."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def execute_terminal_command(command: str):
    """
    Выполняет bash-команду.
    ВАЖНО: Перед выполнением проверяет таблицу approvals.
    Если одобрения нет, возвращает запрос на одобрение.
    """
    cmd_hash = hashlib.md5(command.encode()).hexdigest()
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    row = c.execute("SELECT approved FROM approvals WHERE command_hash = ?", (cmd_hash,)).fetchone()
    
    # Если запись есть и approved=1 -> выполняем
    if row and row[0] == 1:
        try:
            # Выполняем
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
            return f"Output:\n{result.stdout}\nErrors:\n{result.stderr}"
        except Exception as e:
            return f"Execution Error: {e}"
    else:
        # Если записи нет -> создаем запрос
        if not row:
            c.execute("INSERT OR IGNORE INTO approvals (command_hash, command_text, approved) VALUES (?, ?, 0)", 
                      (cmd_hash, command))
            conn.commit()
        
        return (f"STOP_EXECUTION_REQUEST: Команда '{command}' требует одобрения пользователя. "
                "Сообщи пользователю: 'Жду подтверждения команды в панели управления'.")

# --- Database / Context Tools ---

def add_steps_to_plan(steps_list: str):
    """
    Добавляет шаги в план. 
    Format: '1. Step description\n2. Step description'
    """
    lines = steps_list.split('\n')
    count = 0
    for line in lines:
        if line.strip():
            # Простейший парсер "1. Текст"
            parts = line.split('. ', 1)
            if len(parts) == 2:
                try:
                    step_num = int(parts[0])
                    desc = parts[1]
                    database.add_plan_step(desc, step_num)
                    count += 1
                except:
                    continue
    return f"{count} steps added to database."

def get_current_plan_step():
    """Возвращает текущую задачу из БД."""
    step = database.get_next_step()
    if step is None:
        return "NO_MORE_STEPS"
    return f"Current Step ID: {step['id']}, Step Number: {step['step_number']}, Task: {step['description']}"

def get_completed_research_context():
    """
    Возвращает список всех ВЫПОЛНЕННЫХ (DONE) пунктов плана и их результаты.
    Используй это, чтобы учитывать предыдущий контекст.
    """
    return database.get_done_results_text()

def submit_step_result(step_id: int, result_text: str):
    """
    Сохраняет результат шага в БД и помечает его как DONE.
    """
    database.update_step_status(step_id, "DONE", result_text)
    return "Result saved to Database. Step marked as DONE."

def mark_step_failed(step_id: int, error_msg: str):
    """Помечает шаг как FAILED."""
    database.update_step_status(step_id, "FAILED", error_msg)
    return "Step marked as FAILED."

