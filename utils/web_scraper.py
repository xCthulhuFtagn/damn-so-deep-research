import requests
import trafilatura
import logging
import threading
from urllib.parse import urlparse
from typing import List, Dict, Any

from config import MIN_CHUNK_LEN_TO_MERGE, FIRECRAWL_BASE_URL, FIRECRAWL_API_KEY

logger = logging.getLogger(__name__)

def fetch_and_process_url(url: str, title: str, text_splitter) -> List[Dict[str, Any]]:
    """
    Скачивает URL через Firecrawl, нарезает и склеивает "огрызки" текста.
    """
    domain = urlparse(url).netloc.lower()
    blocked_domains = ['youtube.com', 'bilibili.com', 'weibo.com', 'twitter.com', 'instagram.com']
    
    if any(bad in domain for bad in blocked_domains):
        return []
        
    if url.endswith(('.pdf', '.xml', '.doc', '.docx', '.xls', '.mp4', '.zip', '.exe')):
        return []

    try:
        # 1. Скачивание через Firecrawl
        scrape_url = f"{FIRECRAWL_BASE_URL}/v1/scrape"
        headers = {
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "url": url,
            "formats": ["markdown"]
        }
        
        resp = requests.post(scrape_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("success"):
            logger.warning(f"Firecrawl failed to scrape {url}: {data.get('error')}")
            return []
            
        clean_text = data.get("data", {}).get("markdown", "")
        
        if not clean_text:
            return []

        # 2. Умная нарезка (LangChain)
        raw_chunks = text_splitter.split_text(clean_text)
        
        # 3. Логика "Smart Merge" (спасение маленьких чанков)
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
        logger.warning(f"Error processing {url} via Firecrawl: {e}")
        return []
