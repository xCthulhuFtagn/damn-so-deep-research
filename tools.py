import subprocess
import hashlib
import sqlite3
import logging
import time
import typing
import json
from typing import List, Dict, Any, Optional
from ddgs import DDGS
from config import DB_PATH
import database
from logging_setup import setup_logging
from agents import function_tool

setup_logging()
logger = logging.getLogger(__name__)

# --- External Tools ---

@function_tool
def web_search(query: str) -> str:
    """
    Использует DuckDuckGo для поиска в интернете.
    
    Args:
        query (str): Строка поискового запроса.
    """
    logger.info("web_search: query=%s", query)
    try:
        results = DDGS().text(query, max_results=3)
        logger.debug("web_search: ok")
        return str(results)
    except Exception as e:
        logger.exception("web_search failed")
        return f"Error searching: {e}"

@function_tool
def read_file(file_path: str) -> str:
    """
    Читает содержимое локального файла.
    
    Args:
        file_path (str): Полный или относительный путь к файлу.
    """
    try:
        logger.info("read_file: path=%s", file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            logger.debug("read_file: ok chars=%s", len(content))
            return content
    except Exception as e:
        logger.exception("read_file failed: path=%s", file_path)
        return f"Error reading file: {e}"

@function_tool
def execute_terminal_command(command: str) -> str:
    """
    Выполняет bash-команду в терминале.
    ВАЖНО: Перед выполнением требует подтверждения пользователя в UI.
    
    Args:
        command (str): Текст команды для выполнения (например, 'ls -la').
    """
    cmd_hash = hashlib.md5(command.encode()).hexdigest()
    logger.info("execute_terminal_command: requested hash=%s cmd=%s", cmd_hash, command)
    
    # 1. Check existing approval or create request
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT approved FROM approvals WHERE command_hash = ?", (cmd_hash,)).fetchone()
    
    if not row:
        c.execute("INSERT OR IGNORE INTO approvals (command_hash, command_text, approved) VALUES (?, ?, 0)", 
                  (cmd_hash, command))
        conn.commit()
        logger.info("execute_terminal_command: approval requested hash=%s", cmd_hash)
        row = (0,) # Pending
    
    conn.close()
    
    # 2. Loop until approved or denied or stopped
    status = row[0]
    waited = 0
    
    while status == 0:
        if database.should_stop():
            logger.info("execute_terminal_command: stop signal received")
            return "Execution stopped by user signal."
            
        time.sleep(1)
        waited += 1
        if waited % 5 == 0:
            logger.info("Waiting for approval... hash=%s time=%ds", cmd_hash, waited)
            
        # Re-check status
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        r = c.execute("SELECT approved FROM approvals WHERE command_hash = ?", (cmd_hash,)).fetchone()
        conn.close()
        if r:
            status = r[0]
        else:
            # Should not happen unless row deleted
            status = 0

    # 3. Handle decision
    if status == 1:
        # Approved
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
            logger.info("execute_terminal_command: executed hash=%s returncode=%s", cmd_hash, result.returncode)
            return f"Output:\n{result.stdout}\nErrors:\n{result.stderr}"
        except Exception as e:
            logger.exception("execute_terminal_command failed: hash=%s", cmd_hash)
            return f"Execution Error: {e}"
            
    elif status == -1:
        # Denied
        logger.warning("execute_terminal_command: denied hash=%s", cmd_hash)
        return f"Execution denied by user for command: {command}"
        
    return "Unknown status"

# --- Database / Context Tools ---

@function_tool
def add_steps_to_plan(steps: List[str]) -> str:
    """
    Добавляет новые задачи в план исследования.
    
    Args:
        steps (List[str]): Список строк, каждая из которых должна начинаться с номера (например, ["1. Найти X"]).
    """
    logger.info("add_steps_to_plan: input_type=%s count=%s", type(steps), len(steps) if isinstance(steps, list) else "N/A")
    
    # Accept either a list of strings or a single string (possibly JSON).
    steps_list: list[str] = []
    if isinstance(steps, list):
        steps_list = [str(s) for s in steps if s is not None]
    elif isinstance(steps, str):
        raw = steps.strip()
        if not raw:
            return "0 steps added to database."
        # If the model returned JSON, decode it.
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, list):
                steps_list = [str(s) for s in decoded if s is not None]
            else:
                steps_list = raw.splitlines()
        except Exception:
            steps_list = raw.splitlines()
    else:
        return "Error: 'steps' must be a list of strings or a single string."

    # If we received a single long line like "1) ... 2) ... 3) ...", split it into steps.
    if len(steps_list) == 1:
        one = (steps_list[0] or "").strip()
        if one and ("\n" not in one):
            import re
            # Capture "N. ..." or "N) ..." chunks until the next step marker or end.
            parts = re.findall(r'(\d+)[\.\)]\s*(.*?)(?=(?:\s+\d+[\.\)]\s)|$)', one)
            if parts and len(parts) >= 2:
                steps_list = [f"{num}. {txt.strip()}" for num, txt in parts if (txt or "").strip()]

    count = 0
    # Offset-from-max dedupe policy: if a parsed step number already exists, assign max+1.
    existing_nums = database.get_existing_step_numbers()
    max_num = database.get_max_step_number()
    used_nums = set(existing_nums)

    for line in steps_list:
        line = line.strip()
        if not line: continue
            
        # Улучшенный парсинг: ищем число в начале строки
        import re
        match = re.match(r'^(\d+)[\.\)]\s*(.*)', line)
        try:
            if match:
                step_num = int(match.group(1))
                desc = match.group(2).strip()
            else:
                # If numbering is missing, treat the whole line as the description.
                step_num = None
                desc = line

            if not desc:
                continue

            if step_num is None or step_num in used_nums:
                step_num = max_num + 1

            # Update max (in case model provides a large non-duplicate number)
            if step_num > max_num:
                max_num = step_num

            used_nums.add(step_num)
            database.add_plan_step(desc, step_num)
            count += 1
        except Exception as e:
            logger.error("Failed to add step line '%s': %s", line, e)

    logger.info("add_steps_to_plan: added=%s", count)
    return f"{count} steps added to database."

@function_tool
def get_current_plan_step() -> str:
    """
    Возвращает текущую активную задачу из плана.
    ЭТОТ ИНСТРУМЕНТ НЕ ПРИНИМАЕТ АРГУМЕНТОВ.
    """
    logger.info("get_current_plan_step called")
    step = database.get_next_step()
    if step is None:
        logger.info("get_current_plan_step: NO_MORE_STEPS")
        return "NO_MORE_STEPS"
    logger.info("get_current_plan_step: step_id=%s step_number=%s", step["id"], step["step_number"])
    return f"Current Step ID: {step['id']}, Step Number: {step['step_number']}, Task: {step['description']}"

@function_tool
def get_completed_research_context() -> str:
    """
    Возвращает список всех уже выполненных шагов и их результаты.
    ЭТОТ ИНСТРУМЕНТ НЕ ПРИНИМАЕТ АРГУМЕНТОВ.
    """
    logger.debug("get_completed_research_context called")
    return database.get_done_results_text()

@function_tool
def submit_step_result(step_id: int, result_text: str) -> str:
    """
    Сохраняет финальный результат выполнения текущего шага.
    
    Args:
        step_id (int): ID шага из базы данных.
        result_text (str): Текст с результатами исследования.
    """
    logger.info("submit_step_result: step_id=%s result_chars=%s", step_id, len(result_text or ""))
    database.update_step_status(step_id, "DONE", result_text)
    return "Result saved to Database. Step marked as DONE."

@function_tool
def mark_step_failed(step_id: int, error_msg: str) -> str:
    """
    Помечает шаг как проваленный.
    
    Args:
        step_id (int): ID шага из базы данных.
        error_msg (str): Причина провала.
    """
    logger.warning("mark_step_failed: step_id=%s error_chars=%s", step_id, len(error_msg or ""))
    database.update_step_status(step_id, "FAILED", error_msg)
    return "Step marked as FAILED."
