"""Research tools for web search."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from tavily import TavilyClient  # type: ignore[import-untyped]


def _default_env_path() -> str:
    return str(Path(__file__).resolve().parents[2] / ".env")


def search_web(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search the web and return Tavily results with raw content included."""

    load_dotenv(_default_env_path(), override=False)
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required for research search.")

    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=query,
        max_results=max_results,
        include_raw_content=True,
    )
    if not isinstance(response, dict):
        raise ValueError("Unexpected Tavily response type.")
    return response
