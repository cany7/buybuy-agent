from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.agents.research_agent import (
    DEFAULT_RESEARCH_BRIEF,
    build_category_research_instructions,
    build_product_search_instructions,
    create_research_agent,
    execute_research,
    validate_category_research_payload,
    validate_product_search_payload,
)
from src.models.research import CategoryResearchOutput, ProductSearchOutput, SearchMeta


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


def _category_payload() -> dict[str, Any]:
    return {
        "category": "户外装备",
        "product_type": "冲锋衣",
        "user_context": "男性用户，28岁，上海，想买一件适合徒步的冲锋衣。",
    }


def _search_meta() -> SearchMeta:
    return SearchMeta(
        retry_count=0,
        result_status="ok",
        search_expanded=False,
        expansion_notes=None,
    )


def test_validate_product_search_payload_accepts_unspecified_budget() -> None:
    validate_product_search_payload(_payload())


def test_validate_product_search_payload_rejects_missing_fields() -> None:
    with pytest.raises(ValueError):
        validate_product_search_payload({"product_type": "", "search_goal": "", "constraints": {}})


def test_validate_category_research_payload_accepts_required_fields() -> None:
    validate_category_research_payload(_category_payload())


def test_validate_category_research_payload_rejects_missing_fields() -> None:
    with pytest.raises(ValueError):
        validate_category_research_payload({"category": "", "product_type": "", "user_context": ""})


def test_build_product_search_instructions_renders_template() -> None:
    instructions = build_product_search_instructions(_payload())

    assert "搜索适合周末徒步的冲锋衣" in instructions
    assert DEFAULT_RESEARCH_BRIEF in instructions
    assert "预算范围：unspecified" in instructions


def test_build_product_search_instructions_uses_custom_research_brief() -> None:
    payload = _payload()
    payload["research_brief"] = "优先看英文权威评测，再补中文用户经验。"
    instructions = build_product_search_instructions(payload)

    assert "优先看英文权威评测" in instructions
    assert DEFAULT_RESEARCH_BRIEF not in instructions


def test_build_category_research_instructions_renders_template() -> None:
    instructions = build_category_research_instructions(_category_payload())

    assert "调研 户外装备 品类下的 冲锋衣 产品类型" in instructions
    assert "男性用户，28岁，上海" in instructions
    assert DEFAULT_RESEARCH_BRIEF in instructions


def test_build_category_research_instructions_uses_custom_research_brief() -> None:
    payload = _category_payload()
    payload["research_brief"] = "以中文搜索为主，英文搜索为辅。"
    instructions = build_category_research_instructions(payload)

    assert "以中文搜索为主" in instructions
    assert DEFAULT_RESEARCH_BRIEF not in instructions


def test_create_research_agent_registers_search_tool() -> None:
    runner = create_research_agent("test instructions", client=DummyClient())

    assert len(runner.agent.default_options["tools"]) == 1


@pytest.mark.asyncio
async def test_execute_research_creates_new_agent_each_call(monkeypatch, tmp_path: Path) -> None:
    from src.agents import research_agent as module

    created_runners: list[str] = []

    class FakeRunner:
        def __init__(self, instructions: str) -> None:
            self.instructions = instructions

        async def run_structured(self, task_prompt: str, response_format: type[Any]) -> ProductSearchOutput:
            assert response_format is ProductSearchOutput
            created_runners.append(self.instructions)
            return ProductSearchOutput(
                products=[],
                search_meta=_search_meta(),
                notes=f"called with {task_prompt}",
                suggested_followup="关注透气性",
            )

    monkeypatch.setattr(
        module,
        "create_research_agent",
        lambda instructions, client=None: FakeRunner(instructions),
    )

    first = await execute_research("dispatch_product_search", _payload(), client=DummyClient())
    second = await execute_research("dispatch_product_search", _payload(), client=DummyClient())

    assert isinstance(first, ProductSearchOutput)
    assert isinstance(second, ProductSearchOutput)
    assert first.notes.startswith("called with")
    assert second.suggested_followup == "关注透气性"
    assert len(created_runners) == 2
    assert created_runners[0] == created_runners[1]


@pytest.mark.asyncio
async def test_execute_research_supports_category_research(monkeypatch, tmp_path: Path) -> None:
    from src.agents import research_agent as module

    class FakeRunner:
        def __init__(self, instructions: str) -> None:
            self.instructions = instructions

        async def run_structured(self, task_prompt: str, response_format: type[Any]) -> Any:
            assert "品类调研任务" in self.instructions
            assert response_format is CategoryResearchOutput
            return CategoryResearchOutput.model_validate(
                {
                    "category": "户外装备",
                    "category_knowledge": {
                        "data_sources": ["https://example.com/guide"],
                        "product_type_overview": [
                            {
                                "product_type": "冲锋衣",
                                "subtypes": ["硬壳"],
                                "description": "防水外层",
                            }
                        ],
                        "shared_concepts": [
                            {
                                "name": "GORE-TEX",
                                "description": "常见防水透气面料",
                                "relevant_product_types": ["冲锋衣"],
                            }
                        ],
                        "brand_landscape": [
                            {
                                "brand": "Arc'teryx",
                                "positioning": "高端",
                                "known_for": "硬壳",
                            }
                        ],
                    },
                    "product_type_name": "冲锋衣",
                    "product_type_knowledge": {
                        "subtypes": {"硬壳": "强调防护"},
                        "decision_dimensions": [
                            {
                                "name": "防水",
                                "objectivity": "可量化",
                                "importance": "高",
                                "ambiguity_risk": "中",
                            }
                        ],
                        "tradeoffs": [
                            {
                                "dimensions": ["防水", "透气"],
                                "explanation": "通常需要平衡",
                            }
                        ],
                        "price_tiers": [
                            {
                                "range": "2000-3000",
                                "typical": "中高端",
                                "features": "更完整的面料和做工",
                            }
                        ],
                        "scenario_mapping": [
                            {
                                "scenario": "周末徒步",
                                "key_needs": ["防水", "透气"],
                                "can_compromise": ["轻量"],
                            }
                        ],
                        "common_misconceptions": [
                            {
                                "misconception": "越贵越适合所有人",
                                "reality": "要看场景",
                                "anchor_suggestion": "先确认路线和天气",
                            }
                        ],
                    },
                }
            )

    monkeypatch.setattr(
        module,
        "create_research_agent",
        lambda instructions, client=None: FakeRunner(instructions),
    )

    result = await execute_research("dispatch_category_research", _category_payload(), client=DummyClient())

    assert isinstance(result, CategoryResearchOutput)
    assert result.product_type_name == "冲锋衣"


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
                search_meta=_search_meta(),
                notes="搜索完成",
                suggested_followup="补看重量",
            )
        )

    monkeypatch.setattr(runner.agent, "run", fake_run)
    result = await runner.run("执行搜索")

    assert result.notes == "搜索完成"
    assert captured["messages"] == "执行搜索"
    assert captured["options"]["response_format"] is ProductSearchOutput


def test_product_search_output_schema_includes_search_meta() -> None:
    schema = ProductSearchOutput.model_json_schema()

    assert "search_meta" in schema["properties"]
    assert "search_meta" in schema["required"]
