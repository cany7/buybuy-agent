"""Prompt loading helpers backed by docs/PROMPTS.md."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


def _prompts_doc_path() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "PROMPTS.md"


@lru_cache(maxsize=1)
def _prompts_doc_text() -> str:
    return _prompts_doc_path().read_text(encoding="utf-8")


def _extract_markdown_code_block(heading: str) -> str:
    pattern = rf"{re.escape(heading)}.*?```markdown\n(.*?)\n```"
    match = re.search(pattern, _prompts_doc_text(), re.DOTALL)
    if match is None:
        raise ValueError(f"Could not find markdown code block for heading: {heading}")
    return match.group(1).strip()


def load_main_agent_instructions() -> str:
    """Load the full main-agent system prompt from docs."""

    return _extract_markdown_code_block("### 1.2 完整 System Prompt 模板")


def load_product_search_template() -> str:
    """Load the product-search prompt template from docs."""

    return _extract_markdown_code_block("### 2.2 产品搜索模板（Product Search Template）")
