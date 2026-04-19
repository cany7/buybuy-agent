"""Research tools for web search."""

from __future__ import annotations

import os
from typing import Any

from tavily import TavilyClient  # type: ignore[import-untyped]
from urllib.parse import urlparse

from src.utils.runtime_config import load_runtime_env

MAX_TAVILY_RESULTS_PER_CALL = 10
MIN_TAVILY_RESULTS_PER_CALL = 1
MAX_RAW_CONTENT_CHARS = 20_000
RAW_CONTENT_TRUNCATION_NOTE = "\n[raw_content truncated by system]"


def _normalize_max_results(max_results: int) -> int:
    return max(MIN_TAVILY_RESULTS_PER_CALL, min(max_results, MAX_TAVILY_RESULTS_PER_CALL))


def _dedupe_key(result: dict[str, Any]) -> tuple[str, str]:
    url = result.get("url")
    if isinstance(url, str) and url.strip():
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return ("url", url.strip().lower())

    title = result.get("title")
    content = result.get("content")
    title_part = title.strip().lower() if isinstance(title, str) else ""
    content_part = content.strip().lower() if isinstance(content, str) else ""
    return ("text", f"{title_part}|{content_part}")


def _protect_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    raw_content = normalized.get("raw_content")
    if isinstance(raw_content, str) and len(raw_content) > MAX_RAW_CONTENT_CHARS:
        normalized["raw_content"] = (
            raw_content[:MAX_RAW_CONTENT_CHARS] + RAW_CONTENT_TRUNCATION_NOTE
        )
    return normalized


def _normalize_results(results: list[Any]) -> list[Any]:
    deduped_results: list[Any] = []
    seen_keys: set[tuple[str, str]] = set()
    for result in results:
        if not isinstance(result, dict):
            deduped_results.append(result)
            continue
        key = _dedupe_key(result)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_results.append(_protect_result_payload(result))
    return deduped_results


def search_web(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search the web and return Tavily results with raw content included."""

    load_runtime_env()
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required for research search.")

    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=query,
        max_results=_normalize_max_results(max_results),
        include_raw_content=True,
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected Tavily response type.")
    results = response.get("results")
    if isinstance(results, list):
        normalized = dict(response)
        normalized["results"] = _normalize_results(results)
        return normalized
    return response
