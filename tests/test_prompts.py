from __future__ import annotations

from pathlib import Path

from src.agents import prompts as prompts_module


def test_load_main_agent_instructions_reads_runtime_prompt_file() -> None:
    instructions = prompts_module.load_main_agent_instructions()

    assert instructions.startswith("# 你是一个通用购物选品推荐 Agent")
    assert "你的每一轮输出必须是 DecisionOutput 结构化格式。" in instructions


def test_load_category_research_template_reads_runtime_prompt_file() -> None:
    template = prompts_module.load_category_research_template()

    assert template.startswith("# 品类调研任务")
    assert "调研 {category} 品类下的 {product_type} 产品类型" in template


def test_load_product_search_template_reads_runtime_prompt_file() -> None:
    template = prompts_module.load_product_search_template()

    assert template.startswith("# 产品搜索任务")
    assert "搜索并筛选符合以下条件的 {product_type} 产品。" in template


def test_prompt_loaders_do_not_cache_stale_file_content(
    monkeypatch,
    tmp_path: Path,
) -> None:
    prompt_file = tmp_path / "main_agent_system.txt"
    prompt_file.write_text("first version", encoding="utf-8")

    monkeypatch.setattr(
        prompts_module,
        "_prompt_resource_path",
        lambda name: prompt_file,
    )

    assert prompts_module.load_main_agent_instructions() == "first version"

    prompt_file.write_text("second version", encoding="utf-8")

    assert prompts_module.load_main_agent_instructions() == "second version"
