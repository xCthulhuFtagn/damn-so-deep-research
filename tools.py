import subprocess
import hashlib
import sqlite3
import logging
from duckduckgo_search import DDGS
from config import DB_PATH
import database
from logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# --- External Tools ---

def web_search(query: str, **kwargs):
    """Использует DuckDuckGo для поиска в интернете."""
    logger.info("web_search: query=%s kwargs=%s", query, kwargs)
    try:
        results = DDGS().text(query, max_results=3)
        # DDGS returns generator-like; str() is what this project expects today
        logger.debug("web_search: ok")
        return str(results)
    except Exception as e:
        logger.exception("web_search failed")
        return f"Error searching: {e}"

def read_file(file_path: str, **kwargs):
    """Читает локальный файл."""
    try:
        logger.info("read_file: path=%s kwargs=%s", file_path, kwargs)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            logger.debug("read_file: ok chars=%s", len(content))
            return content
    except Exception as e:
        logger.exception("read_file failed: path=%s", file_path)
        return f"Error reading file: {e}"

def execute_terminal_command(command: str, **kwargs):
    """
    Выполняет bash-команду.
    ВАЖНО: Перед выполнением проверяет таблицу approvals.
    Если одобрения нет, возвращает запрос на одобрение.
    """
    cmd_hash = hashlib.md5(command.encode()).hexdigest()
    logger.info("execute_terminal_command: requested hash=%s cmd=%s kwargs=%s", cmd_hash, command, kwargs)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT approved FROM approvals WHERE command_hash = ?", (cmd_hash,)).fetchone()
    
    # Если запись есть и approved=1 -> выполняем
    if row and row[0] == 1:
        try:
            # Выполняем
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
            logger.info("execute_terminal_command: executed hash=%s returncode=%s", cmd_hash, result.returncode)
            return f"Output:\n{result.stdout}\nErrors:\n{result.stderr}"
        except Exception as e:
            logger.exception("execute_terminal_command failed: hash=%s", cmd_hash)
            return f"Execution Error: {e}"
    else:
        # Если записи нет -> создаем запрос
        if not row:
            c.execute("INSERT OR IGNORE INTO approvals (command_hash, command_text, approved) VALUES (?, ?, 0)", 
                      (cmd_hash, command))
            conn.commit()
            logger.info("execute_terminal_command: approval requested hash=%s", cmd_hash)
        
        return (f"STOP_EXECUTION_REQUEST: Команда '{command}' требует одобрения пользователя. "
                "Сообщи пользователю: 'Жду подтверждения команды в панели управления'.")

# --- Database / Context Tools ---

def add_steps_to_plan(steps_list: str, **kwargs):
    """
    Добавляет шаги в план. 
    Format: '1. Step description\n2. Step description'
    """
    logger.info("add_steps_to_plan: chars=%s kwargs=%s", len(steps_list or ""), kwargs)
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
    logger.info("add_steps_to_plan: added=%s", count)
    return f"{count} steps added to database."

def get_current_plan_step(**kwargs):
    """Возвращает текущую задачу из БД."""
    logger.info("get_current_plan_step: kwargs=%s", kwargs)
    step = database.get_next_step()
    if step is None:
        logger.info("get_current_plan_step: NO_MORE_STEPS")
        return "NO_MORE_STEPS"
    logger.info("get_current_plan_step: step_id=%s step_number=%s", step["id"], step["step_number"])
    return f"Current Step ID: {step['id']}, Step Number: {step['step_number']}, Task: {step['description']}"

def get_completed_research_context(**kwargs):
    """
    Возвращает список всех ВЫПОЛНЕННЫХ (DONE) пунктов плана и их результаты.
    Используй это, чтобы учитывать предыдущий контекст.
    """
    logger.debug("get_completed_research_context called: kwargs=%s", kwargs)
    return database.get_done_results_text()

def submit_step_result(step_id: int, result_text: str, **kwargs):
    """
    Сохраняет результат шага в БД и помечает его как DONE.
    """
    logger.info("submit_step_result: step_id=%s result_chars=%s kwargs=%s", step_id, len(result_text or ""), kwargs)
    database.update_step_status(step_id, "DONE", result_text)
    return "Result saved to Database. Step marked as DONE."

def mark_step_failed(step_id: int, error_msg: str, **kwargs):
    """Помечает шаг как FAILED."""
    logger.warning("mark_step_failed: step_id=%s error_chars=%s kwargs=%s", step_id, len(error_msg or ""), kwargs)
    database.update_step_status(step_id, "FAILED", error_msg)
    return "Step marked as FAILED."
