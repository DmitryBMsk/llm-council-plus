"""Web search helpers (DuckDuckGo / Brave / Keenable + full article fetch via Jina Reader).

This module is intentionally:
- Provider-agnostic (caller chooses provider; no implicit fallback).
- Safe for prompts: returns bounded text (truncation) to avoid giant contexts.
- Non-secret: API keys come from env/config only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx

from . import config

logger = logging.getLogger(__name__)


class WebSearchProvider(str, Enum):
    DUCKDUCKGO = "duckduckgo"
    BRAVE = "brave"
    TAVILY = "tavily"
    EXA = "exa"
    KEENABLE = "keenable"


SEARCH_TIMEOUT_BUDGET_S = 60.0
DEFAULT_MAX_RESULTS = 5
DEFAULT_FULL_CONTENT_RESULTS = 0
KEENABLE_SEARCH_URL = "https://api.keenable.ai/v1/search"
KEENABLE_MAX_RESULTS = 50  # API range for max_results is 1-50.


async def _fetch_with_jina(url: str, timeout: float = 25.0) -> Optional[str]:
    """Fetch article content via Jina Reader (markdown-ish plain text)."""
    if not url:
        return None
    jina_url = f"https://r.jina.ai/{url}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(jina_url, headers={"Accept": "text/plain"})
        if resp.status_code != 200:
            logger.info("[WEB_SEARCH] Jina returned %s for %s", resp.status_code, url)
            return None
        return resp.text
    except httpx.TimeoutException:
        logger.info("[WEB_SEARCH] Jina timeout for %s", url)
        return None
    except Exception as e:
        logger.info("[WEB_SEARCH] Jina fetch failed for %s: %s", url, e)
        return None


def _truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


async def _search_duckduckgo(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    full_content_results: int = DEFAULT_FULL_CONTENT_RESULTS,
) -> str:
    """DuckDuckGo search via ddgs (sync lib, run in thread)."""

    def _run_ddgs() -> List[Dict[str, Any]]:
        from ddgs import DDGS  # local import: optional at runtime

        with DDGS() as ddgs:
            # Use generic text search (not "news") to match broader queries.
            return list(ddgs.text(query, max_results=max_results))

    start = time.time()
    results_raw: List[Dict[str, Any]] = await asyncio.to_thread(_run_ddgs)
    if not results_raw:
        return "No web search results found."

    normalized = []
    urls_to_fetch: List[tuple[int, str]] = []
    for idx, r in enumerate(results_raw[:max_results], 1):
        title = r.get("title") or "No Title"
        url = r.get("url") or r.get("href") or ""
        summary = r.get("body") or r.get("excerpt") or "No description available."
        normalized.append(
            {
                "index": idx,
                "title": title,
                "url": url,
                "summary": summary,
                "content": None,
            }
        )
        if full_content_results > 0 and idx <= full_content_results and url:
            urls_to_fetch.append((idx - 1, url))

    # Fetch full content for top N results within a time budget.
    for idx0, url in urls_to_fetch:
        elapsed = time.time() - start
        remaining = SEARCH_TIMEOUT_BUDGET_S - elapsed
        if remaining <= 5:
            break
        content = await _fetch_with_jina(url, timeout=min(25.0, remaining))
        if content:
            if len(content) < 500:
                content += (
                    "\n\n[System Note: Full content fetch yielded limited text. "
                    "Appending original summary.]\n"
                    f"Original Summary: {normalized[idx0]['summary']}"
                )
            normalized[idx0]["content"] = content

    formatted = []
    for r in normalized:
        text = f"Result {r['index']}:\nTitle: {r['title']}\nURL: {r['url']}"
        if r["content"]:
            text += f"\nContent:\n{_truncate(r['content'], 2000)}"
        else:
            text += f"\nSummary: {_truncate(r['summary'], 800)}"
        formatted.append(text)
    return "\n\n".join(formatted)


async def _search_brave(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    full_content_results: int = DEFAULT_FULL_CONTENT_RESULTS,
) -> str:
    """Brave Search API. Requires ENABLE_BRAVE=true and BRAVE_API_KEY."""
    api_key = (config.BRAVE_API_KEY or "").strip()
    if not (config.ENABLE_BRAVE and api_key):
        return "[System Note: Brave search is not configured. Set ENABLE_BRAVE=true and BRAVE_API_KEY.]"

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        )
    if resp.status_code != 200:
        logger.warning("[WEB_SEARCH] Brave returned %s: %s", resp.status_code, resp.text[:300])
        return "[System Note: Brave search failed. Please check your API key.]"

    data = resp.json()
    web_results = (data.get("web") or {}).get("results") or []
    if not web_results:
        return "No web search results found."

    normalized = []
    urls_to_fetch: List[tuple[int, str]] = []
    for idx, r in enumerate(web_results[:max_results], 1):
        title = r.get("title") or "No Title"
        url = r.get("url") or ""
        summary = r.get("description") or "No description available."
        extra = r.get("extra_snippets") or []
        if extra:
            summary += "\n" + "\n".join(extra[:2])
        normalized.append(
            {
                "index": idx,
                "title": title,
                "url": url,
                "summary": summary,
                "content": None,
            }
        )
        if full_content_results > 0 and idx <= full_content_results and url:
            urls_to_fetch.append((idx - 1, url))

    for idx0, url in urls_to_fetch:
        elapsed = time.time() - start
        remaining = SEARCH_TIMEOUT_BUDGET_S - elapsed
        if remaining <= 5:
            break
        content = await _fetch_with_jina(url, timeout=min(25.0, remaining))
        if content:
            if len(content) < 500:
                content += (
                    "\n\n[System Note: Full content fetch yielded limited text. "
                    "Appending original summary.]\n"
                    f"Original Summary: {normalized[idx0]['summary']}"
                )
            normalized[idx0]["content"] = content

    formatted = []
    for r in normalized:
        text = f"Result {r['index']}:\nTitle: {r['title']}\nURL: {r['url']}"
        if r["content"]:
            text += f"\nContent:\n{_truncate(r['content'], 2000)}"
        else:
            text += f"\nSummary: {_truncate(r['summary'], 800)}"
        formatted.append(text)
    return "\n\n".join(formatted)


async def _search_keenable(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    full_content_results: int = DEFAULT_FULL_CONTENT_RESULTS,
) -> str:
    """Keenable Search API. Requires ENABLE_KEENABLE=true and KEENABLE_API_KEY."""
    api_key = (config.KEENABLE_API_KEY or "").strip()
    if not (config.ENABLE_KEENABLE and api_key):
        return "[System Note: Keenable search is not configured. Set ENABLE_KEENABLE=true and KEENABLE_API_KEY.]"

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            KEENABLE_SEARCH_URL,
            json={
                "query": query,
                "max_results": max(1, min(max_results, KEENABLE_MAX_RESULTS)),
                # Card results (cards.keenable.ai) expire after a day; keep citable pages only.
                "disable_cards": True,
            },
            headers={"Accept": "application/json", "X-API-Key": api_key},
        )
    if resp.status_code != 200:
        logger.warning("[WEB_SEARCH] Keenable returned %s: %s", resp.status_code, resp.text[:300])
        return "[System Note: Keenable search failed. Please check your API key.]"

    data = resp.json()
    web_results = [r for r in (data.get("results") or []) if isinstance(r, dict) and r.get("url")]
    if not web_results:
        return "No web search results found."

    normalized = []
    for idx, r in enumerate(web_results[:max_results], 1):
        normalized.append(
            {
                "index": idx,
                "title": r.get("title") or "No Title",
                "url": r["url"],
                "summary": r.get("description") or r.get("snippet") or "No description available.",
                "content": None,
            }
        )

    for item in normalized[: max(0, full_content_results)]:
        remaining = SEARCH_TIMEOUT_BUDGET_S - (time.time() - start)
        if remaining <= 5:
            break
        content = await _fetch_with_jina(item["url"], timeout=min(25.0, remaining))
        if content:
            if len(content) < 500:
                content += (
                    "\n\n[System Note: Full content fetch yielded limited text. "
                    "Appending original summary.]\n"
                    f"Original Summary: {item['summary']}"
                )
            item["content"] = content

    formatted = []
    for r in normalized:
        text = f"Result {r['index']}:\nTitle: {r['title']}\nURL: {r['url']}"
        if r["content"]:
            text += f"\nContent:\n{_truncate(r['content'], 2000)}"
        else:
            text += f"\nSummary: {_truncate(r['summary'], 800)}"
        formatted.append(text)
    return "\n\n".join(formatted)


def duckduckgo_available() -> bool:
    try:
        import ddgs  # noqa: F401
        return True
    except Exception:
        return False


async def perform_web_search(
    query: str,
    *,
    provider: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    full_content_results: int = DEFAULT_FULL_CONTENT_RESULTS,
) -> str:
    """Perform web search for a single provider (no fallback)."""
    p = (provider or "").strip().lower()
    if p == WebSearchProvider.DUCKDUCKGO.value:
        if not duckduckgo_available():
            return "[System Note: DuckDuckGo search is unavailable (missing ddgs dependency).]"
        return await _search_duckduckgo(query, max_results=max_results, full_content_results=full_content_results)
    if p == WebSearchProvider.BRAVE.value:
        return await _search_brave(query, max_results=max_results, full_content_results=full_content_results)
    if p == WebSearchProvider.KEENABLE.value:
        return await _search_keenable(query, max_results=max_results, full_content_results=full_content_results)
    if p in (WebSearchProvider.TAVILY.value, WebSearchProvider.EXA.value):
        raise ValueError("tavily/exa are handled via existing tools layer")
    raise ValueError(f"Unknown web search provider: {provider}")

