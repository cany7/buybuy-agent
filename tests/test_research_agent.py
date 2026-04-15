from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.agents.research_agent import (
    SEARCH_INSTRUCTION_FOR_CHINA,
    SEARCH_INSTRUCTION_FOR_NON_CHINA,
    build_product_search_instructions,
    create_research_agent,
    execute_research,
    get_search_language_instruction,
    validate_product_search_payload,
)
from src.models.research import ProductSearchOutput


class DummyClient:
    async def get_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def _payload() -> dict[str, Any]:
    return {
        "product_type": "冲锋衣",
        "search_goal": "搜索适合周末徒步的冲锋衣",
        "constraints": {
            "budget": "unspecified",
            "gender": "男款",
            "key_requirements": ["防水", "透气"],
            "scenario": "周末徒步",
            "exclusions": ["国产品牌"],
        },
    }


def test_validate_product_search_payload_accepts_unspecified_budget() -> None:
    validate_product_search_payload(_payload())


def test_validate_product_search_payload_rejects_missing_fields() -> None:
    with pytest.raises(ValueError):
        validate_product_search_payload({"product_type": "", "search_goal": "", "constraints": {}})


def test_search_language_instruction_switches_by_location() -> None:
    assert get_search_language_instruction("上海") == SEARCH_INSTRUCTION_FOR_CHINA
    assert get_search_language_instruction("Chicago, IL") == SEARCH_INSTRUCTION_FOR_NON_CHINA


def test_build_product_search_instructions_renders_template() -> None:
    instructions = build_product_search_instructions(_payload(), "上海")

    assert "搜索适合周末徒步的冲锋衣" in instructions
    assert SEARCH_INSTRUCTION_FOR_CHINA in instructions
    assert "预算范围：unspecified" in instructions


def test_create_research_agent_registers_search_tool() -> None:
    runner = create_research_agent("test instructions", client=DummyClient())

    assert len(runner.agent.default_options["tools"]) == 1


@pytest.mark.asyncio
async def test_execute_research_creates_new_agent_each_call(monkeypatch, tmp_path: Path) -> None:
    profile_path = tmp_path / "data" / "user_profile" / "global_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps({"demographics": {"location": "上海"}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    from src.agents import research_agent as module

    created_runners: list[str] = []

    class FakeRunner:
        def __init__(self, instructions: str) -> None:
            self.instructions = instructions

        async def run(self, task_prompt: str) -> ProductSearchOutput:
            created_runners.append(self.instructions)
            return ProductSearchOutput(
                products=[],
                notes=f"called with {task_prompt}",
                suggested_followup="关注透气性",
            )

    monkeypatch.setattr(module, "_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(
        module,
        "create_research_agent",
        lambda instructions, client=None: FakeRunner(instructions),
    )

    first = await execute_research("dispatch_product_search", _payload(), client=DummyClient())
    second = await execute_research("dispatch_product_search", _payload(), client=DummyClient())

    assert first.notes.startswith("called with")
    assert second.suggested_followup == "关注透气性"
    assert len(created_runners) == 2
    assert created_runners[0] == created_runners[1]


@pytest.mark.asyncio
async def test_research_agent_runner_uses_product_search_output(monkeypatch) -> None:
    runner = create_research_agent("test instructions", client=DummyClient())
    captured: dict[str, Any] = {}

    async def fake_run(messages: str, **kwargs: Any) -> Any:
        captured["messages"] = messages
        captured["options"] = kwargs["options"]
        return SimpleNamespace(
            value=ProductSearchOutput(
                products=[],
                notes="搜索完成",
                suggested_followup="补看重量",
            )
        )

    monkeypatch.setattr(runner.agent, "run", fake_run)
    result = await runner.run("执行搜索")

    assert result.notes == "搜索完成"
    assert captured["messages"] == "执行搜索"
    assert captured["options"]["response_format"] is ProductSearchOutput
