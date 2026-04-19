from __future__ import annotations

from pathlib import Path


def test_env_example_includes_llm_and_tavily_variables() -> None:
    content = Path(".env.example").read_text(encoding="utf-8")

    for variable in [
        "LLM_BASE_URL=",
        "LLM_API_KEY=",
        "MAIN_AGENT_MODEL=",
        "RESEARCH_AGENT_MODEL=",
        "MAIN_AGENT_BASE_URL=",
        "MAIN_AGENT_API_KEY=",
        "RESEARCH_AGENT_BASE_URL=",
        "RESEARCH_AGENT_API_KEY=",
        "TAVILY_API_KEY=",
    ]:
        assert variable in content
