import requests
import torch
import logging
from sentence_transformers import util

from agents import function_tool
from config import MAX_SEARCH_RESULTS, MAX_FINAL_TOP_CHUNKS, FIRECRAWL_BASE_URL, FIRECRAWL_API_KEY, DEFAULT_TIMEOUT
from utils.text_processing import bi_encoder, cross_encoder, text_splitter

logger = logging.getLogger(__name__)

@function_tool
def intelligent_web_search(query: str) -> str:
    """
    Выполняет поиск информации в интернете через Firecrawl (Search API) с глубокой фильтрацией контента.
    
    Алгоритм:
    1. Поиск и автоматический скрейпинг через Firecrawl Search API.
    2. Нарезка полученного контента на чанки.
    3. Bi-Encoder: Векторизация всех чанков батчем и грубый отсев (Top-20).
    4. Cross-Encoder: Точная перепроверка пар "Запрос-Чанк" (Reranking -> Top-3).
    """
    
    # --- Шаг 1: Поиск и скрейпинг через Firecrawl ---
    try:
        search_url = f"{FIRECRAWL_BASE_URL}/v1/search"
        headers = {
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "query": query,
            "limit": MAX_SEARCH_RESULTS,
            "scrapeOptions": {
                "formats": ["markdown"]
            }
        }
        
        resp = requests.post(search_url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("success"):
            error_msg = data.get("error", "Unknown Firecrawl error")
            logger.error(f"Firecrawl search failed: {error_msg}")
            return f"Ошибка поиска: {error_msg}"

        raw_results = data.get('data', [])

        if not raw_results:
            logger.info("Search query '%s' returned 0 results from Firecrawl", query)
            return "По вашему запросу ничего не найдено."

        logger.info("Firecrawl returned %d search results for query '%s'", len(raw_results), query)

    except Exception as e:
        logger.exception("intelligent_web_search error during Firecrawl search: %s", e)
        return f"Ошибка поискового движка: {e}"

    # --- Шаг 2: Нарезка на чанки ---
    all_chunks = []
    for res in raw_results:
        url = res.get('url')
        title = res.get('title', 'No Title')
        markdown = res.get('markdown', '')
        
        if not markdown:
            # Если markdown пустой, пробуем использовать описание (snippet) если оно есть
            markdown = res.get('description', '')
            
        if not markdown:
            continue
            
        # Нарезка
        raw_chunks = text_splitter.split_text(markdown)
        for chunk in raw_chunks:
            chunk = chunk.strip()
            if len(chunk) < 10: continue
            all_chunks.append({
                'text': chunk,
                'title': title,
                'url': url
            })

    if not all_chunks:
        logger.warning("Failed to extract any content from Firecrawl results for query '%s'", query)
        return "Не удалось извлечь контент из найденных страниц."

    logger.info("Extracted %d chunks from Firecrawl results for query '%s'", len(all_chunks), query)

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
