"""Prompt loading helpers backed by src/prompts resources."""

from __future__ import annotations

from pathlib import Path


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def _prompt_resource_path(filename: str) -> Path:
    return _prompts_dir() / filename


def _load_prompt_file(filename: str) -> str:
    return _prompt_resource_path(filename).read_text(encoding="utf-8").strip()


def load_main_agent_instructions() -> str:
    """Load the full main-agent system prompt from runtime resources."""

    return _load_prompt_file("main_agent_system.txt")


def load_category_research_template() -> str:
    """Load the category-research prompt template from runtime resources."""

    return _load_prompt_file("category_research.txt")


def load_product_search_template() -> str:
    """Load the product-search prompt template from runtime resources."""

    return _load_prompt_file("product_search.txt")
