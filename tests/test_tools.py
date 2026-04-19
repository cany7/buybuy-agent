from __future__ import annotations

from typing import Any

import pytest

from src.agents import tools as tools_module


def test_search_web_clamps_max_results_and_deduplicates_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeTavilyClient:
        def __init__(self, *, api_key: str) -> None:
            captured["api_key"] = api_key

        def search(self, *, query: str, max_results: int, include_raw_content: bool) -> dict[str, Any]:
            captured["query"] = query
            captured["max_results"] = max_results
            captured["include_raw_content"] = include_raw_content
            return {
                "query": query,
                "results": [
                    {
                        "title": "Review A",
                        "url": "https://example.com/a",
                        "content": "summary a",
                        "raw_content": "A" * 50,
                    },
                    {
                        "title": "Review A duplicate",
                        "url": "https://example.com/a",
                        "content": "duplicate",
                        "raw_content": "B" * 50,
                    },
                    {
                        "title": "Review B",
                        "url": "https://example.com/b",
                        "content": "summary b",
                        "raw_content": "C" * 50,
                    },
                ],
            }

    monkeypatch.setattr(tools_module, "TavilyClient", FakeTavilyClient)
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")

    result = tools_module.search_web("best shell jacket", max_results=99)

    assert captured["api_key"] == "tavily-key"
    assert captured["query"] == "best shell jacket"
    assert captured["max_results"] == 10
    assert captured["include_raw_content"] is True
    assert [entry["url"] for entry in result["results"]] == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_search_web_protects_extremely_long_raw_content(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTavilyClient:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key

        def search(self, *, query: str, max_results: int, include_raw_content: bool) -> dict[str, Any]:
            return {
                "results": [
                    {
                        "title": "Long Review",
                        "url": "https://example.com/long",
                        "content": "summary",
                        "raw_content": "X" * 25_000,
                    }
                ]
            }

    monkeypatch.setattr(tools_module, "TavilyClient", FakeTavilyClient)
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")

    result = tools_module.search_web("best shell jacket", max_results=0)
    raw_content = result["results"][0]["raw_content"]

    assert len(raw_content) > 20_000
    assert len(raw_content) < 21_000
    assert raw_content.endswith("\n[raw_content truncated by system]")
