import trafilatura
from sentence_transformers import SentenceTransformer, util
import torch
import requests
import subprocess
import hashlib
import logging
import time
from urllib.parse import urlparse
import json
from typing import List, Dict, Any, Optional
from config import DB_PATH, NUM_SEARCHES_PER_CALL
from database import db
from logging_setup import setup_logging
from agents import function_tool

setup_logging()
logger = logging.getLogger(__name__)

# --- External Tools ---

embedder = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')

@function_tool
def intelligent_web_search(query: str) -> str:
    """
    Выполняет поиск, скачивает страницы, очищает HTML и возвращает
    только релевантные параграфы, ранжированные по смыслу.
    """
    # 1. Поиск через SearXNG (JSON)
    searx_url = "http://localhost:666/search"
    try:
        params = {
            'q': query, 
            'format': 'json', 
            'language': 'ru',
            'engines': 'google' # ,bing,duckduckgo' # Явно указываем движки
        }
        resp = requests.get(searx_url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        
        # Если results нет, берем пустой список
        search_results = data.get('results', [])[:NUM_SEARCHES_PER_CALL]
        
        if not search_results:
            return "По вашему запросу ничего не найдено."
            
    except Exception as e:
        logger.exception("intelligent_web_search failed: query=%s, error=%s", query, e)
        return f"Ошибка поиска: {e}"

    final_report = []
    logger.info("intelligent_web_search: query='%s' urls: %s", query, [res.get('url') for res in search_results])
    for res in search_results:
        url = res.get('url')
        title = res.get('title')

        domain = urlparse(url).netloc.lower()
        blocked_domains = ['zhihu.com', 'youtube.com', 'bilibili.com', 'weibo.com']
        
        if any(bad in domain for bad in blocked_domains):
            print(f"⏩ Пропуск (медленный домен): {domain}")
            continue
        
        # Пропуск бинарных файлов
        if url.endswith(('.pdf', '.xml', '.doc', '.mp4', '.zip')):
            continue
        
        # 2. Извлечение контента через Trafilatura
        # fetch_url и extract работают очень быстро и не грузят GPU
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            continue
            
        clean_text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        
        if not clean_text:
            continue

        # 3. Семантическая фильтрация (RAG on the Fly)
        # Разбиваем текст на смысловые блоки (например, по 500 символов)
        chunk_size = 500
        chunks = [clean_text[i:i+chunk_size] for i in range(0, len(clean_text), chunk_size)]

        if not chunks:
            continue

        # Кодируем запрос и чанки в векторы
        query_embedding = embedder.encode(query, convert_to_tensor=True)
        chunk_embeddings = embedder.encode(chunks, convert_to_tensor=True)

        # Считаем схожесть
        cos_scores = util.cos_sim(query_embedding, chunk_embeddings)[0]
        
        # Берем топ-2 лучших чанка из этой статьи
        top_results = torch.topk(cos_scores, k=min(3, len(chunks)))
        
        relevant_snippets = []
        for score, idx in zip(top_results.values, top_results.indices):
            if score.item() > 0.3: # Порог релевантности
                relevant_snippets.append(chunks[idx].replace("\n", " "))
        
        if relevant_snippets:
            formatted_entry = f"Источник: {title} ({url})\n" + "\n".join(relevant_snippets)
            final_report.append(formatted_entry)

    if not final_report:
        return "Удалось найти ссылки, но полезного контента на страницах не найдено (возможно, защита от ботов)."

    # Собираем финальный контекст
    return "\n\n".join(final_report)

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
    except FileNotFoundError:
        logger.warning("read_file: FileNotFoundError path=%s", file_path)
        return f"Error: File '{file_path}' not found. Verify the path or use other tools to find the correct file."
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
    conn = db.get_connection()
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
        if db.should_stop():
            logger.info("execute_terminal_command: stop signal received")
            return "Execution stopped by user signal."
            
        time.sleep(1)
        waited += 1
        if waited % 5 == 0:
            logger.info("Waiting for approval... hash=%s time=%ds", cmd_hash, waited)
            
        # Re-check status
        conn = db.get_connection()
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
def web_search_summary(summarized_content: str) -> str:
    """
    Сохраняет краткую сводку результатов поиска в контекст.
    АВТОМАТИЧЕСКИ удаляет полный текст исходного поиска из истории сообщений.
    
    Args:
        summarized_content (str): Краткая сводка результатов поиска.
    """
    # Логируем действие
    logger.info("summary: saving content (len=%s) and pruning previous raw output", len(summarized_content))
    
    # 1. Вызываем метод очистки в DatabaseManager
    # Это удалит "тяжелый" текст предыдущего шага (web_search) из БД
    db.prune_last_tool_message()
    
    # 2. Возвращаем успех
    # Сама суммаризация (summarized_content) сохранится в аргументах вызова этого инструмента
    return "Summary saved. Raw search data has been removed from history to free up context window."

@function_tool
def answer_from_knowledge(answer: str) -> str:
    """
    Эхо-инструмент: принимает сгенерированный текст ответа и возвращает его как есть,
    чтобы зафиксировать ответ через tool_call.
    """
    return answer

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
    # Offset-from-max dedupe policy
    existing_nums = db.get_existing_step_numbers()
    max_num = db.get_max_step_number()
    used_nums = set(existing_nums)

    for line in steps_list:
        line = line.strip()
        if not line: continue
            
        import re
        match = re.match(r'^(\d+)[\.\)]\s*(.*)', line)
        try:
            if match:
                step_num = int(match.group(1))
                desc = match.group(2).strip()
            else:
                step_num = None
                desc = line

            if not desc:
                continue

            if step_num is None or step_num in used_nums:
                step_num = max_num + 1

            if step_num > max_num:
                max_num = step_num

            used_nums.add(step_num)
            db.add_plan_step(desc, step_num)
            count += 1
        except Exception as e:
            logger.error("Failed to add step line '%s': %s", line, e)

    logger.info("add_steps_to_plan: added=%s", count)
    return f"{count} steps added to database."

@function_tool
def get_current_plan_step() -> str:
    """
    Возвращает текущую активную задачу из плана.
    Также устанавливает глобальный активный шаг в системе для контекста.
    ЭТОТ ИНСТРУМЕНТ НЕ ПРИНИМАЕТ АРГУМЕНТОВ.
    """
    logger.info("get_current_plan_step called")
    step = db.get_next_step()
    if step is None:
        logger.info("get_current_plan_step: NO_MORE_STEPS")
        db.set_active_task(None)
        return "NO_MORE_STEPS"
    
    # Set global active task so all subsequent messages are tagged with this task number
    db.set_active_task(int(step["step_number"]))
    
    logger.info("get_current_plan_step: step_id=%s step_number=%s", step["id"], step["step_number"])
    return f"Current Step ID: {step['id']}, Step Number: {step['step_number']}, Task: {step['description']}"

@function_tool
def get_research_summary() -> str:
    """
    Возвращает структурированный список всех уже выполненных шагов и их результаты.
    Используется для составления финального отчета.
    ЭТОТ ИНСТРУМЕНТ НЕ ПРИНИМАЕТ АРГУМЕНТОВ.
    """
    logger.debug("get_research_summary called")
    return db.get_done_results_text()

@function_tool
def submit_step_result(step_id: int, result_text: str) -> str:
    """
    Сохраняет финальный результат выполнения текущего шага.
    
    Args:
        step_id (int): ID шага из базы данных.
        result_text (str): Текст с результатами исследования.
    """
    logger.info("submit_step_result: step_id=%s result_chars=%s", step_id, len(result_text or ""))
    db.update_step_status(step_id, "DONE", result_text)
    # Clear active task as we are done
    db.set_active_task(None)
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
    db.update_step_status(step_id, "FAILED", error_msg)
    # Do NOT clear active task here, so Strategist can still see the context of this failed task
    return "Step marked as FAILED."

@function_tool
def get_recovery_context() -> str:
    """
    Возвращает контекст для восстановления: исходный запрос + план + детали провала.
    Для использования Стратегом.
    """
    # 1. User Prompt
    prompt = db.get_initial_user_prompt() or "N/A"
    
    # 2. Plan Status
    plan = db.get_plan_summary()
    
    # 3. Active (Failed) Step Details
    active_task = db.get_active_task()
    failed_context = ""
    if active_task:
        # Get messages for this task
        # We assume we are in 'main_research' session usually
        msgs = db.get_messages_for_task("main_research", active_task)
        # Extract last few messages as "Error Context"
        # Or just return a summary saying "Step X failed"
        failed_context = f"Step {active_task} logs:\n"
        for m in msgs[-5:]:
             failed_context += f"{m['role']}: {m['content'][:200]}...\n"
    
    return f"""RECOVERY CONTEXT:
Original Request: {prompt}
Plan Status:
{plan}

Failed Step Context:
{failed_context}
"""
