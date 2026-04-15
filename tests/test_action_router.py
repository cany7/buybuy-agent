from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.models.decision import DecisionOutput
from src.router.action_router import ActionRouter
from src.store.document_store import DocumentStore


def _decision(**overrides: Any) -> DecisionOutput:
    payload = {
        "user_message": "继续补充信息。",
        "internal_reasoning": {
            "state_summary": "需要继续推进。",
            "stage_assessment": "需求挖掘",
        },
        "next_action": "ask_user",
    }
    payload.update(overrides)
    return DecisionOutput.model_validate(payload)


@pytest.mark.asyncio
async def test_router_ask_user_applies_session_updates(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, Any]) -> Any:
        raise AssertionError("research should not run")

    router = ActionRouter(store=store, research_executor=fake_research)
    result = await router.route(
        _decision(session_updates={"intent": "自用选购"}),
        {"session_id": "2026-04-14-100000"},
    )
    saved_session = store.load_session()

    assert result.wait_for_user_input is True
    assert result.should_continue is False
    assert result.session["intent"] == "自用选购"
    assert saved_session is not None
    assert saved_session["intent"] == "自用选购"


@pytest.mark.asyncio
async def test_router_recommend_waits_for_user_input(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, Any]) -> Any:
        raise AssertionError("research should not run")

    router = ActionRouter(store=store, research_executor=fake_research)
    result = await router.route(
        _decision(
            next_action="recommend",
            user_message="先给你两个方向。",
            session_updates={"goal_summary": "春夏通勤鞋"},
        ),
        {"session_id": "2026-04-14-100000"},
    )

    assert result.user_message == "先给你两个方向。"
    assert result.wait_for_user_input is True
    assert result.should_continue is False
    assert result.session["goal_summary"] == "春夏通勤鞋"


@pytest.mark.asyncio
async def test_router_rejects_unknown_session_update_keys(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, Any]) -> Any:
        raise AssertionError("research should not run")

    router = ActionRouter(store=store, research_executor=fake_research)

    with pytest.raises(ValueError, match="Unsupported session_updates keys"):
        await router.route(
            _decision(session_updates={"pending_research_result": {"x": 1}}),
            {"session_id": "2026-04-14-100000"},
        )


@pytest.mark.asyncio
async def test_router_dispatch_product_search_writes_pending_result_and_candidates(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    events: list[str] = []

    async def fake_research(task_type: str, payload: dict[str, Any]) -> Any:
        from src.models.research import ProductSearchOutput

        events.append("research")
        assert task_type == "dispatch_product_search"
        return ProductSearchOutput(
            products=[],
            notes="搜索完成",
            suggested_followup="比较重量",
        )

    router = ActionRouter(store=store, research_executor=fake_research)
    result = await router.route(
        _decision(
            next_action="dispatch_product_search",
            action_payload={
                "product_type": "冲锋衣",
                "search_goal": "测试搜索",
                "constraints": {
                    "budget": "unspecified",
                    "key_requirements": ["防水"],
                    "exclusions": [],
                },
            },
            session_updates={"decision_progress": {"recommendation_round": "第一轮"}},
        ),
        {"session_id": "2026-04-14-100000"},
        emit_user_message=lambda message: events.append(f"message:{message}"),
    )

    assert result.wait_for_user_input is False
    assert result.should_continue is True
    assert result.replaced_pending_research_result is True
    assert result.user_message_delivered is True
    assert events == ["message:继续补充信息。", "research"]
    assert result.session["pending_research_result"]["type"] == "product_search"
    assert result.session["candidate_products"]["notes"] == "搜索完成"
    assert result.session["decision_progress"]["recommendation_round"] == "未开始"


@pytest.mark.asyncio
async def test_router_dispatch_product_search_accepts_null_budget(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, Any]) -> Any:
        from src.models.research import ProductSearchOutput

        assert task_type == "dispatch_product_search"
        assert payload["constraints"]["budget"] is None
        return ProductSearchOutput(products=[], notes="搜索完成", suggested_followup=None)

    router = ActionRouter(store=store, research_executor=fake_research)
    result = await router.route(
        _decision(
            next_action="dispatch_product_search",
            action_payload={
                "product_type": "跑鞋",
                "search_goal": "测试空预算",
                "constraints": {
                    "budget": None,
                    "key_requirements": ["缓震"],
                    "exclusions": [],
                },
            },
        ),
        {"session_id": "2026-04-14-100000"},
    )

    assert result.should_continue is True
    assert result.session["pending_research_result"]["result"]["notes"] == "搜索完成"


@pytest.mark.asyncio
async def test_router_saves_pending_profile_updates_when_round_completes(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, Any]) -> Any:
        raise AssertionError("research should not run")

    router = ActionRouter(store=store, research_executor=fake_research)
    result = await router.route(
        _decision(
            session_updates={"decision_progress": {"recommendation_round": "完成"}},
            profile_updates={"global_profile": {"lifestyle_tags": ["徒步"]}},
        ),
        {
            "session_id": "2026-04-14-100000",
            "decision_progress": {"recommendation_round": "第二轮"},
        },
    )

    assert result.session["pending_profile_updates"]["global_profile"]["lifestyle_tags"] == ["徒步"]


@pytest.mark.asyncio
async def test_router_raises_when_round_completes_without_profile_updates(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, Any]) -> Any:
        raise AssertionError("research should not run")

    router = ActionRouter(store=store, research_executor=fake_research)

    with pytest.raises(ValueError, match="profile_updates is required"):
        await router.route(
            _decision(session_updates={"decision_progress": {"recommendation_round": "完成"}}),
            {
                "session_id": "2026-04-14-100000",
                "decision_progress": {"recommendation_round": "第二轮"},
            },
        )


@pytest.mark.asyncio
async def test_router_onboard_user_writes_global_profile(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, Any]) -> Any:
        raise AssertionError("research should not run")

    router = ActionRouter(store=store, research_executor=fake_research)
    await router.route(
        _decision(
            next_action="onboard_user",
            action_payload={"demographics": {"gender": "男", "age_range": "25-34", "location": "上海"}},
        ),
        {"session_id": "2026-04-14-100000"},
    )

    profile_path = tmp_path / "data" / "user_profile" / "global_profile.json"
    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    assert saved["demographics"]["location"] == "上海"
