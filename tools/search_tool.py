"""Search utilities for JARVIS with graceful dependency fallback."""

from __future__ import annotations

import logging
from importlib.util import find_spec
from typing import Dict, List

logger = logging.getLogger(__name__)


def duckduckgo_search_results(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Return normalized DuckDuckGo results or an empty list if unavailable."""
    if find_spec("duckduckgo_search") is None:
        logger.info("duckduckgo-search is not installed; returning no search results")
        return []

    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            raw_results = list(ddgs.text(query, max_results=max_results))
    except Exception as exc:
        logger.warning("DuckDuckGo search failed for %r: %s", query, exc)
        return []

    return [
        {
            "title": item.get("title", "Untitled"),
            "url": item.get("href", ""),
            "snippet": item.get("body", ""),
        }
        for item in raw_results
    ]


def duckduckgo_search(query: str, max_results: int = 5) -> str:
    """Return formatted web search results from DuckDuckGo."""
    results = duckduckgo_search_results(query=query, max_results=max_results)
    if not results:
        return "DuckDuckGo search unavailable or no results found."

    lines = []
    for idx, item in enumerate(results, start=1):
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        snippet = item.get("snippet", "")
        lines.append(f"{idx}. {title}\nURL: {url}\nSnippet: {snippet}\n")

    return "\n".join(lines)
