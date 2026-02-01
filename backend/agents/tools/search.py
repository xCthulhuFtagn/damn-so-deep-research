"""
Intelligent web search tool with ML-based filtering.

Pipeline:
1. Firecrawl Search API for web search + scraping
2. Text chunking
3. Bi-encoder semantic filtering (top-20 candidates) - async batched
4. Cross-encoder reranking (top-3 final results) - async batched
"""

import logging
from typing import Optional

import httpx
import numpy as np
import torch
from sentence_transformers import util

from backend.core.config import config
from backend.ml.text_processing import (
    get_cross_encoder_batcher,
    get_embedding_batcher,
    get_model_manager,
)

logger = logging.getLogger(__name__)


async def intelligent_web_search(
    query: str,
    max_results: Optional[int] = None,
    max_chunks: Optional[int] = None,
) -> str:
    """
    Execute intelligent web search with ML-based content filtering.

    Args:
        query: Search query
        max_results: Max Firecrawl results (default from config)
        max_chunks: Max final chunks to return (default from config)

    Returns:
        Formatted string with search results or error message
    """
    max_results = max_results or config.search.max_search_results
    max_chunks = max_chunks or config.search.max_final_top_chunks

    # --- Step 1: Firecrawl Search ---
    try:
        search_url = f"{config.firecrawl.base_url}/v1/search"
        headers = {
            "Authorization": f"Bearer {config.firecrawl.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "limit": max_results,
            "scrapeOptions": {"formats": ["markdown"]},
        }

        async with httpx.AsyncClient(timeout=config.search.max_search_results * 10) as client:
            resp = await client.post(search_url, json=payload, headers=headers)

        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            error_msg = data.get("error", "Unknown Firecrawl error")
            logger.error(f"Firecrawl search failed: {error_msg}")
            return f"Search error: {error_msg}"

        raw_results = data.get("data", [])

        if not raw_results:
            logger.info(f"Search '{query}' returned 0 results")
            return "No relevant information found for this query."

        logger.info(f"Firecrawl returned {len(raw_results)} results for '{query}'")

    except httpx.TimeoutException:
        logger.error(f"Search timeout for query: {query}")
        return f"Search timeout for query: {query}"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error during search: {e}")
        return f"Search HTTP error: {e.response.status_code}"
    except Exception as e:
        logger.exception(f"Search error: {e}")
        return f"Search error: {e}"

    # --- Step 2: Text Chunking ---
    model_manager = get_model_manager()
    text_splitter = model_manager.get_text_splitter()

    all_chunks = []
    for res in raw_results:
        url = res.get("url", "")
        title = res.get("title", "No Title")
        markdown = res.get("markdown", "") or res.get("description", "")

        if not markdown:
            continue

        raw_chunks = text_splitter.split_text(markdown)
        for chunk in raw_chunks:
            chunk = chunk.strip()
            if len(chunk) < 10:
                continue
            all_chunks.append({"text": chunk, "title": title, "url": url})

    if not all_chunks:
        logger.warning(f"No content extracted for query '{query}'")
        return "Found pages but could not extract useful content."

    logger.info(f"Extracted {len(all_chunks)} chunks for '{query}'")

    # --- Step 3: Bi-Encoder Filtering (async batched) ---
    embedding_batcher = get_embedding_batcher()
    chunk_texts = [c["text"] for c in all_chunks]

    # Encode query and chunks via async batcher
    query_embed = await embedding_batcher.encode([query])
    corpus_embeds = await embedding_batcher.encode(chunk_texts)

    # Convert to tensors for similarity computation
    query_tensor = torch.from_numpy(query_embed[0]).unsqueeze(0)
    corpus_tensor = torch.from_numpy(np.array(corpus_embeds))

    top_k = min(20, len(all_chunks))
    cos_scores = util.cos_sim(query_tensor, corpus_tensor)[0]
    top_results = torch.topk(cos_scores, k=top_k)

    candidates = []
    for score, idx in zip(top_results.values, top_results.indices):
        idx = idx.item()
        if score.item() < config.search.bi_encoder_threshold:
            continue
        candidates.append(all_chunks[idx])

    if not candidates:
        logger.info(f"Bi-encoder filtered out all chunks for '{query}'")
        return "Found content but it doesn't match the query context (filtered)."

    logger.info(f"Bi-encoder selected {len(candidates)} candidates for '{query}'")

    # --- Step 4: Cross-Encoder Reranking (async batched) ---
    cross_encoder_batcher = get_cross_encoder_batcher()
    cross_inp = [[query, item["text"]] for item in candidates]
    cross_scores = await cross_encoder_batcher.predict(cross_inp)

    scored = [
        {"item": item, "score": cross_scores[i]}
        for i, item in enumerate(candidates)
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)

    # --- Step 5: Format Results ---
    final_top = scored[:max_chunks]
    if not final_top:
        return "Information found but filtered as not precise enough."

    # Group by URL
    grouped = {}
    for entry in final_top:
        score = entry["score"]
        item = entry["item"]
        url = item["url"]

        if score < config.search.cross_encoder_threshold:
            continue

        if url not in grouped:
            grouped[url] = {
                "title": item["title"],
                "snippets": [],
                "max_score": float("-inf"),
            }

        grouped[url]["snippets"].append({"text": item["text"], "score": score})
        grouped[url]["max_score"] = max(grouped[url]["max_score"], score)

    if not grouped:
        return "Information found but filtered as not precise enough."

    # Sort by relevance
    sorted_urls = sorted(
        grouped.keys(), key=lambda u: grouped[u]["max_score"], reverse=True
    )

    # Build report
    lines = []
    for url in sorted_urls:
        source = grouped[url]
        lines.append(f"\n=== Source: {source['title']} ({url}) ===")

        sorted_snippets = sorted(
            source["snippets"], key=lambda s: s["score"], reverse=True
        )
        for snippet in sorted_snippets:
            clean = snippet["text"].replace("\n", " ").strip()
            lines.append(clean)

    logger.info(
        f"Search '{query}': {len(final_top)} snippets from {len(sorted_urls)} sources"
    )
    return "\n".join(lines)
