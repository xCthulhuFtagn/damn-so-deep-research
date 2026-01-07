import requests
import concurrent.futures
import torch
import logging
from sentence_transformers import util

from agents import function_tool
from config import MAX_SEARCH_RESULTS, MAX_FINAL_TOP_CHUNKS
from utils.web_scraper import fetch_and_process_url
from utils.text_processing import bi_encoder, cross_encoder, text_splitter

logger = logging.getLogger(__name__)

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
            'language': 'all', # Явно просим ВСЕ языки
            'safesearch': 0,
        }
        resp = requests.get(searx_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        # Берем чуть больше ссылок, так как у нас теперь мощный фильтр
        raw_results = data.get('results', [])[:MAX_SEARCH_RESULTS] 

        if not raw_results:
            logger.info("Search query '%s' returned 0 results from SearXNG", query)
            return "По вашему запросу ничего не найдено."

        logger.info("SearXNG returned %d raw results for query '%s'", len(raw_results), query)

    except Exception as e:
        logger.exception("intelligent_web_search error: %s", e)
        return f"Ошибка поискового движка: {e}"

    # --- Шаг 2: Параллельный процессинг ---
    all_chunks = []
    
    # 5 потоков обычно достаточно для текстовых страниц, не перегружая сеть
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {
            executor.submit(fetch_and_process_url, res.get('url'), res.get('title'), text_splitter): res 
            for res in raw_results
        }
        
        for future in concurrent.futures.as_completed(future_to_url):
            result = future.result()
            if result:
                all_chunks.extend(result)

    if not all_chunks:
        logger.warning("Failed to extract any content from %d URLs for query '%s'", len(raw_results), query)
        return "Не удалось извлечь контент из найденных страниц (возможно, защита от ботов или пустые страницы)."

    logger.info("Extracted %d chunks from web pages for query '%s'", len(all_chunks), query)

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
        logger.info("Bi-Encoder filtered out all %d chunks for query '%s'", len(all_chunks), query)
        return "Найдены тексты, но они не соответствуют контексту запроса (Bi-Encoder filter)."

    logger.info("Bi-Encoder selected %d candidate chunks for query '%s'", len(candidates), query)

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
        logger.info("Cross-Encoder filter: no top chunks for query '%s'", query)
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
        logger.info("Cross-Encoder filtered out all %d candidates for query '%s' due to low scores", len(candidates), query)
        return "Информация найдена, но отброшена фильтром Cross-Encoder как недостаточно точная."

    logger.info("Search successful for query '%s': found %d snippets from %d sources", query, len(final_top), len(sorted_urls))
    return "\n".join(report_lines)
