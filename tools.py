import trafilatura
from sentence_transformers import SentenceTransformer, CrossEncoder, util
import torch
import requests
import subprocess
import hashlib
import logging
import time
import concurrent.futures
from urllib.parse import urlparse
import json
from typing import List, Dict, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import MAX_SEARCH_RESULTS, MAX_FINAL_TOP_CHUNKS, MAX_CHUNK_SIZE, MIN_CHUNK_LEN_TO_MERGE, CHUNK_OVERLAP
from database import DatabaseManager
from logging_setup import setup_logging
from agents import function_tool

setup_logging()
logger = logging.getLogger(__name__)

# --- External Tools ---

# --- Инициализация глобальных моделей ---
# Загружаем один раз. Используем CPU, но если есть CUDA, torch сам может подхватить, если указать device='cuda'.
# Bi-Encoder: быстрый первичный поиск. Multilingual v2 отлично работает с русским.
bi_encoder = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', device='cpu')

# Cross-Encoder: точный реранкинг. MS Marco — стандарт для проверки релевантности "вопрос-ответ".
cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', device='cpu')

# Глобальный сплиттер LangChain
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=MAX_CHUNK_SIZE,        # Размер смыслового блока
    chunk_overlap=CHUNK_OVERLAP,     # Перекрытие для связности
    separators=["\n\n", "\n", ". ", " ", ""],
    length_function=len
)

@function_tool
def intelligent_web_search(query: str) -> str:
    """
    Выполняет поиск информации в интернете с глубокой фильтрацией контента.
    
    Алгоритм:
    1. Поиск ссылок через SearXNG.
    2. Параллельное скачивание и умная нарезка (RecursiveCharacterTextSplitter + Merge).
    3. Bi-Encoder: Векторизация всех чанков батчем и грубый отсев (Top-20).
    4. Cross-Encoder: Точная перепроверка пар "Запрос-Чанк" (Reranking -> Top-3).
    """
    searx_url = "http://localhost:666/search"
    
    # --- Шаг 1: Получение ссылок ---
    try:
        params = {
            'q': query, 
            'format': 'json', 
            'language': 'ru',
            'engines': 'google'
        }
        resp = requests.get(searx_url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # Берем чуть больше ссылок, так как у нас теперь мощный фильтр
        raw_results = data.get('results', [])[:MAX_SEARCH_RESULTS] 

        if not raw_results:
            return "По вашему запросу ничего не найдено."

    except Exception as e:
        logger.exception("intelligent_web_search error: %s", e)
        return f"Ошибка поискового движка: {e}"

    # --- Шаг 2: Параллельный процессинг ---
    all_chunks = []
    
    # 5 потоков обычно достаточно для текстовых страниц, не перегружая сеть
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {
            executor.submit(fetch_and_process_url, res.get('url'), res.get('title')): res 
            for res in raw_results
        }
        
        for future in concurrent.futures.as_completed(future_to_url):
            result = future.result()
            if result:
                all_chunks.extend(result)

    if not all_chunks:
        return "Не удалось извлечь контент из найденных страниц (возможно, защита от ботов или пустые страницы)."

    # Лимит на обработку, чтобы CPU не умер на огромных статьях
    # all_chunks = all_chunks[:300]

    # --- Шаг 3: Bi-Encoder (Грубая фильтрация) ---
    # Батчевая векторизация текстов
    chunk_texts = [c['text'] for c in all_chunks]
    
    # Кодируем (convert_to_tensor=True для скорости в torch)
    query_embed = bi_encoder.encode(query, convert_to_tensor=True)
    corpus_embeds = bi_encoder.encode(chunk_texts, convert_to_tensor=True, show_progress_bar=False)
    
    # Косинусное сходство
    top_k_coarse = min(20, len(all_chunks))
    cos_scores = util.cos_sim(query_embed, corpus_embeds)[0]
    
    # Выбираем Top-K кандидатов
    top_results = torch.topk(cos_scores, k=top_k_coarse)
    
    candidates = []
    for score, idx in zip(top_results.values, top_results.indices):
        idx = idx.item()
        # Мягкий порог для Bi-Encoder (он часто занижает скоры)
        if score.item() < 0.2: continue 
        
        candidates.append(all_chunks[idx])

    if not candidates:
        return "Найдены тексты, но они не соответствуют контексту запроса (Bi-Encoder filter)."

    # --- Шаг 4: Cross-Encoder (Точный реранкинг) ---
    # Формируем пары [Query, Text]
    cross_inp = [[query, item['text']] for item in candidates]
    
    # Предсказание (возвращает список float scores)
    cross_scores = cross_encoder.predict(cross_inp)
    
    # Объединяем результат
    scored_candidates = []
    for i, item in enumerate(candidates):
        scored_candidates.append({
            'item': item,
            'score': cross_scores[i]
        })
        
    # Сортировка по убыванию релевантности
    scored_candidates.sort(key=lambda x: x['score'], reverse=True)
    
    # --- Шаг 5: Формирование отчета ---
    # Берем ТОП-3 самых лучших
    final_top = scored_candidates[:MAX_FINAL_TOP_CHUNKS]
    if not final_top:
        return "Информация найдена, но отброшена фильтром Cross-Encoder как недостаточно точная."

    # Группируем сниппеты по URL и сохраняем их вместе с исходными данными
    grouped_snippets = {}
    for entry in final_top:
        score = entry['score']
        item = entry['item']
        url = item['url']

        if score < -1.0: # Порог для Cross-Encoder (MS Marco). < 0 обычно значит "не релевантно"
            continue

        if url not in grouped_snippets:
            grouped_snippets[url] = {
                'title': item['title'],
                'snippets': [],
                'max_score': -float('inf') # Для сортировки источников
            }
        
        grouped_snippets[url]['snippets'].append({
            'text': item['text'],
            'score': score
        })
        grouped_snippets[url]['max_score'] = max(grouped_snippets[url]['max_score'], score)

    # Сортируем источники по наивысшему баллу их сниппетов
    sorted_urls = sorted(grouped_snippets.keys(), key=lambda url: grouped_snippets[url]['max_score'], reverse=True)

    report_lines = []
    for url in sorted_urls:
        source_data = grouped_snippets[url]
        header = f"Источник: {source_data['title']} ({url})"
        report_lines.append(f"\n=== {header} ===")

        # Сортируем сниппеты внутри источника по их баллам
        sorted_source_snippets = sorted(source_data['snippets'], key=lambda s: s['score'], reverse=True)
        
        for snippet_data in sorted_source_snippets:
            clean_text = snippet_data['text'].replace("\n", " ").strip()
            report_lines.append(clean_text)
        
    if not report_lines:
        return "Информация найдена, но отброшена фильтром Cross-Encoder как недостаточно точная."

    return "\n".join(report_lines)

def fetch_and_process_url(url: str, title: str) -> List[Dict[str, Any]]:
    """
    Скачивает URL, чистит, нарезает и склеивает "огрызки" текста.
    Запускается в отдельном потоке.
    """
    domain = urlparse(url).netloc.lower()
    blocked_domains = ['youtube.com', 'bilibili.com', 'weibo.com', 'twitter.com', 'instagram.com']
    
    if any(bad in domain for bad in blocked_domains):
        return []
        
    if url.endswith(('.pdf', '.xml', '.doc', '.docx', '.xls', '.mp4', '.zip', '.exe')):
        return []

    try:
        # 1. Скачивание
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return []

        # 2. Экстракция чистого текста
        clean_text = trafilatura.extract(
            downloaded, 
            include_comments=False, 
            include_tables=False, 
            include_formatting=False
        )
        if not clean_text:
            return []

        # 3. Умная нарезка (LangChain)
        raw_chunks = text_splitter.split_text(clean_text)
        
        # 4. Логика "Smart Merge" (спасение маленьких чанков)
        merged_chunks = []
        min_chunk_len = MIN_CHUNK_LEN_TO_MERGE # Если меньше этого, пытаемся приклеить к предыдущему
        
        for chunk in raw_chunks:
            chunk = chunk.strip()
            if not chunk: continue
            
            if len(chunk) >= min_chunk_len:
                merged_chunks.append(chunk)
            else:
                # Если чанк маленький, клеим к предыдущему
                if merged_chunks:
                    prev = merged_chunks[-1]
                    # Добавляем пробел или точку, если нужно
                    sep = " " if prev.endswith(('.', '!', '?')) else ". "
                    merged_chunks[-1] = f"{prev}{sep}{chunk}"
                else:
                    # Если это самый первый и он короткий — оставляем (вдруг это просто ответ "Да")
                    merged_chunks.append(chunk)

        # 5. Упаковка результатов
        processed_chunks = []
        for txt in merged_chunks:
            # Финальная проверка на полный мусор
            if len(txt) < 10: continue
            
            processed_chunks.append({
                'text': txt,
                'title': title,
                'url': url
            })
        
        return processed_chunks

    except Exception as e:
        logger.warning(f"Error processing {url}: {e}")
        return []

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
    conn = DatabaseManager.get_instance().get_connection()
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
        if DatabaseManager.get_instance().should_stop():
            logger.info("execute_terminal_command: stop signal received")
            return "Execution stopped by user signal."
            
        time.sleep(1)
        waited += 1
        if waited % 5 == 0:
            logger.info("Waiting for approval... hash=%s time=%ds", cmd_hash, waited)
            
        # Re-check status
        conn = DatabaseManager.get_instance().get_connection()
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
    DatabaseManager.get_instance().prune_last_tool_message()
    
    # 2. Возвращаем успех
    # Сама суммаризация (summarized_content) сохранится в аргументах вызова этого инструмента
    return "Summary saved. Raw search data has been removed from history to free up context window."

@function_tool
def answer_from_knowledge(answer: str) -> str:
    """
    Эхо-инструмент: принимает сгенерированный текст и возвращает его как есть, чтобы зафиксировать ответ через tool_call.
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
    existing_nums = DatabaseManager.get_instance().get_existing_step_numbers()
    max_num = DatabaseManager.get_instance().get_max_step_number()
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
            DatabaseManager.get_instance().add_plan_step(desc, step_num)
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
    step = DatabaseManager.get_instance().get_next_step()
    if step is None:
        logger.info("get_current_plan_step: NO_MORE_STEPS")
        DatabaseManager.get_instance().set_active_task(None)
        return "NO_MORE_STEPS"
    
    # Set global active task so all subsequent messages are tagged with this task number
    DatabaseManager.get_instance().set_active_task(int(step["step_number"]))
    
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
    return DatabaseManager.get_instance().get_done_results_text()

@function_tool
def submit_step_result(step_id: int, result_text: str) -> str:
    """
    Сохраняет финальный результат выполнения текущего шага.
    
    Args:
        step_id (int): ID шага из базы данных.
        result_text (str): Текст с результатами исследования.
    """
    logger.info("submit_step_result: step_id=%s result_chars=%s", step_id, len(result_text or ""))
    DatabaseManager.get_instance().update_step_status(step_id, "DONE", result_text)
    # Clear active task as we are done
    DatabaseManager.get_instance().set_active_task(None)
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
    DatabaseManager.get_instance().update_step_status(step_id, "FAILED", error_msg)
    # Do NOT clear active task here, so Strategist can still see the context of this failed task
    return "Step marked as FAILED."

@function_tool
def get_recovery_context() -> str:
    """
    Возвращает контекст для восстановления: исходный запрос + план + детали провала.
    Для использования Стратегом.
    """
    # 1. User Prompt
    prompt = DatabaseManager.get_instance().get_initial_user_prompt() or "N/A"
    
    # 2. Plan Status
    plan = DatabaseManager.get_instance().get_plan_summary()
    
    # 3. Active (Failed) Step Details
    active_task = DatabaseManager.get_instance().get_active_task()
    failed_context = ""
    if active_task:
        # Get messages for this task
        # We assume we are in 'main_research' session usually
        msgs = DatabaseManager.get_instance().get_messages_for_task("main_research", active_task)
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
