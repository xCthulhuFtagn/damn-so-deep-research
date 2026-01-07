import requests
import trafilatura
import logging
from urllib.parse import urlparse
from typing import List, Dict, Any

from config import MIN_CHUNK_LEN_TO_MERGE

logger = logging.getLogger(__name__)

def fetch_and_process_url(url: str, title: str, text_splitter) -> List[Dict[str, Any]]:
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
        # 1. Скачивание (requests with timeout to avoid hanging)
        try:
            resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0 (compatible; ResearchBot/1.0)'})
            resp.raise_for_status()
            
            # Check content type to avoid downloading binaries
            content_type = resp.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type and 'text/plain' not in content_type:
                return []
                
            downloaded = resp.text
        except Exception as e:
            logger.debug(f"Failed to fetch {url}: {e}")
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
