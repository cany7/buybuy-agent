from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from src.models.decision import DecisionOutput, DimensionUpdate, InternalReasoning
from src.models.research import (
    CategoryResearchOutput,
    PriceInfo,
    ProductInfo,
    ProductSearchOutput,
    SearchMeta,
)


@pytest.mark.parametrize("priority", [0, 5])
def test_dimension_update_rejects_out_of_range_priority(priority: int) -> None:
    with pytest.raises(ValidationError):
        DimensionUpdate(
            dimension="预算",
            priority=priority,
            confidence=1,
            urgency=4,
            update_reason="invalid priority",
        )


@pytest.mark.parametrize("confidence", [0, 5])
def test_dimension_update_rejects_out_of_range_confidence(confidence: int) -> None:
    with pytest.raises(ValidationError):
        DimensionUpdate(
            dimension="预算",
            priority=1,
            confidence=confidence,
            urgency=4,
            update_reason="invalid confidence",
        )


@pytest.mark.parametrize("urgency", [0, 17])
def test_dimension_update_rejects_out_of_range_urgency(urgency: int) -> None:
    with pytest.raises(ValidationError):
        DimensionUpdate(
            dimension="预算",
            priority=1,
            confidence=1,
            urgency=urgency,
            update_reason="invalid urgency",
        )


def test_decision_output_serializes_to_json() -> None:
    decision = DecisionOutput(
        user_message="请继续说说你的预算。",
        internal_reasoning=InternalReasoning(
            state_summary="预算未知，需要继续澄清。",
            stage_assessment="需求挖掘",
        ),
        next_action="ask_user",
        session_updates={"intent": "自用选购"},
    )

    payload = decision.model_dump(mode="json")

    assert payload["next_action"] == "ask_user"
    assert payload["session_updates"] == {"intent": "自用选购"}


def test_decision_output_rejects_invalid_next_action() -> None:
    with pytest.raises(ValidationError):
        DecisionOutput.model_validate(
            {
                "user_message": "test",
                "internal_reasoning": {
                    "state_summary": "test",
                    "stage_assessment": "test",
                },
                "next_action": "dispatch_unknown",
            }
        )


@pytest.mark.parametrize("missing_field", ["user_message", "next_action"])
def test_decision_output_requires_required_fields(missing_field: str) -> None:
    payload = {
        "user_message": "test",
        "internal_reasoning": {
            "state_summary": "test",
            "stage_assessment": "test",
        },
        "next_action": "ask_user",
    }
    payload.pop(missing_field)

    with pytest.raises(ValidationError):
        DecisionOutput.model_validate(payload)


def test_decision_output_optional_fields_default_to_none() -> None:
    decision = DecisionOutput.model_validate(
        {
            "user_message": "继续。",
            "internal_reasoning": {
                "state_summary": "test",
                "stage_assessment": "需求挖掘",
            },
            "next_action": "ask_user",
        }
    )

    assert decision.action_payload is None
    assert decision.session_updates is None
    assert decision.profile_updates is None


def test_dimension_update_constraints_are_enforced() -> None:
    with pytest.raises(ValidationError):
        InternalReasoning(
            state_summary="test",
            stage_assessment="test",
            updated_dimensions=cast(
                list[Any],
                [
                    {
                        "dimension": "预算",
                        "priority": 5,
                        "confidence": 1,
                        "urgency": 4,
                        "update_reason": "invalid priority",
                    }
                ],
            ),
        )


def test_price_info_supports_minimal_instantiation() -> None:
    price = PriceInfo(display="¥2999")

    assert price.display == "¥2999"
    assert price.currency is None
    assert price.amount is None


def test_price_info_supports_extended_instantiation() -> None:
    price = PriceInfo(display="¥2999", currency="CNY", amount=2999)

    assert price.currency == "CNY"
    assert price.amount == 2999


def test_product_info_supports_complete_instantiation() -> None:
    product = ProductInfo.model_validate(
        {
            "name": "Beta LT",
            "brand": "Arc'teryx",
            "price": {
                "display": "¥4500",
                "currency": "CNY",
                "amount": 4500,
            },
            "specs": {"weight": "395g"},
            "features": ["GORE-TEX ePE", "头盔兼容帽兜"],
            "pros": ["防护强"],
            "cons": ["价格高"],
            "sources": ["https://example.com/review"],
            "source_consistency": "high",
        }
    )

    assert product.price.amount == 4500
    assert product.features == ["GORE-TEX ePE", "头盔兼容帽兜"]


def test_category_research_output_serializes() -> None:
    output = CategoryResearchOutput.model_validate(
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

    assert output.model_dump(mode="json")["product_type_name"] == "冲锋衣"


def test_product_search_output_allows_empty_products() -> None:
    output = ProductSearchOutput.model_validate(
        {
            "products": [],
            "search_meta": {
                "retry_count": 1,
                "result_status": "insufficient_results",
                "search_expanded": True,
                "expansion_notes": "放宽预算后仍结果较少",
            },
            "notes": "暂无合适结果",
            "suggested_followup": "放宽预算",
        }
    )

    assert output.products == []
    assert output.notes == "暂无合适结果"


def test_product_search_output_serializes() -> None:
    output = ProductSearchOutput.model_validate(
        {
            "products": [
                {
                    "name": "Beta LT",
                    "brand": "Arc'teryx",
                    "price": {
                        "display": "¥4500",
                        "currency": "CNY",
                        "amount": 4500,
                    },
                    "specs": {"weight": "395g"},
                    "features": ["GORE-TEX ePE", "头盔兼容帽兜"],
                    "pros": ["防护强"],
                    "cons": ["价格高"],
                    "sources": ["https://example.com/review"],
                    "source_consistency": "high",
                }
            ],
            "search_meta": {
                "retry_count": 0,
                "result_status": "ok",
                "search_expanded": False,
                "expansion_notes": None,
            },
            "notes": "样例搜索输出",
            "suggested_followup": "对比透气性",
        }
    )

    assert output.model_dump(mode="json")["products"][0]["brand"] == "Arc'teryx"
    assert output.model_dump(mode="json")["search_meta"]["result_status"] == "ok"


def test_search_meta_supports_documented_fields() -> None:
    search_meta = SearchMeta.model_validate(
        {
            "retry_count": 2,
            "result_status": "partial_results",
            "search_expanded": True,
            "expansion_notes": "补搜了英文评测源",
        }
    )

    assert search_meta.retry_count == 2
    assert search_meta.result_status == "partial_results"
