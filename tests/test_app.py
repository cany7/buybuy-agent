from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.app import ShoppingApplication
from src.models.decision import DecisionOutput
from src.router.action_router import ActionRouter
from src.store.document_store import DocumentStore
from src.utils.session import generate_session_id


@dataclass
class FakeMainAgent:
    decisions: list[DecisionOutput]

    async def run(self, context: str, user_message: str) -> DecisionOutput:
        assert "## 当前会话状态" in context
        return self.decisions.pop(0)


def _decision(**overrides: object) -> DecisionOutput:
    payload: dict[str, object] = {
        "user_message": "消息",
        "internal_reasoning": {
            "state_summary": "test",
            "stage_assessment": "需求挖掘",
        },
        "next_action": "ask_user",
    }
    payload.update(overrides)
    return DecisionOutput.model_validate(payload)


@dataclass
class FakeRouteResult:
    user_message: str
    wait_for_user_input: bool
    should_continue: bool
    session: dict[str, Any]
    replaced_pending_research_result: bool = False
    user_message_delivered: bool = False


@pytest.mark.asyncio
async def test_app_creates_session_and_waits_for_user_input(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent([_decision(user_message="请说明预算")]),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    result = await app.run_turn("我想买冲锋衣")
    saved_session = store.load_session()

    assert result.user_message == "请说明预算"
    assert result.wait_for_user_input is True
    assert saved_session is not None
    assert "session_id" in saved_session


@pytest.mark.asyncio
async def test_app_clears_consumed_pending_research_result(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-120000",
            "pending_research_result": {"type": "product_search", "result": {"notes": "x"}},
        }
    )

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent([_decision(user_message="给你推荐")]),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    result = await app.run_turn(None)
    saved_session = store.load_session()

    assert result.session.get("pending_research_result") is None
    assert saved_session is not None
    assert saved_session.get("pending_research_result") is None


@pytest.mark.asyncio
async def test_app_keeps_new_pending_research_result_after_dispatch(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-120000",
            "pending_research_result": {"type": "product_search", "result": {"notes": "old"}},
        }
    )

    async def fake_research(task_type: str, payload: dict[str, object]):
        from src.models.research import ProductSearchOutput

        return ProductSearchOutput(products=[], notes="new", suggested_followup=None)

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent(
            [
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
                )
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    result = await app.run_turn(None)

    assert result.should_continue is True
    assert result.session["pending_research_result"]["result"]["notes"] == "new"


@pytest.mark.asyncio
async def test_app_initialize_runs_recovery_check_once(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class RecordingDocumentStore(DocumentStore):
        def apply_pending_profile_updates(self, session: dict[str, object]) -> bool:
            calls.append(session)
            return super().apply_pending_profile_updates(session)

    store = RecordingDocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-120000",
            "pending_profile_updates": {"global_profile": {"lifestyle_tags": ["徒步"]}},
        }
    )

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent([_decision(user_message="继续描述需求")]),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    session = await app.initialize_session()

    assert len(calls) == 1
    assert calls[0]["session_id"] == "2026-04-14-120000"
    assert "pending_profile_updates" not in session


@pytest.mark.asyncio
async def test_app_run_turn_does_not_repeat_recovery_check(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class RecordingDocumentStore(DocumentStore):
        def apply_pending_profile_updates(self, session: dict[str, object]) -> bool:
            calls.append(session)
            return super().apply_pending_profile_updates(session)

    store = RecordingDocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-120000",
            "pending_profile_updates": {"global_profile": {"lifestyle_tags": ["徒步"]}},
        }
    )

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent([_decision(user_message="继续描述需求")]),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    await app.run_turn("我想买徒步鞋")

    assert calls == []


@pytest.mark.asyncio
async def test_app_run_turn_passes_message_emitter_to_router(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    emitted: list[str] = []

    class FakeRouter:
        async def route(
            self,
            decision: DecisionOutput,
            session: dict[str, Any],
            *,
            emit_user_message=None,
        ) -> FakeRouteResult:
            assert emit_user_message is not None
            emit_user_message("搜索前消息")
            return FakeRouteResult(
                user_message="搜索前消息",
                wait_for_user_input=False,
                should_continue=True,
                session=session,
                user_message_delivered=True,
            )

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent([_decision(next_action="dispatch_product_search")]),
        action_router=FakeRouter(),  # type: ignore[arg-type]
    )

    result = await app.run_turn(None, emit_user_message=emitted.append)

    assert emitted == ["搜索前消息"]
    assert result.user_message_delivered is True


@pytest.mark.asyncio
async def test_app_ignores_historical_sessions_when_current_session_missing(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    (store.sessions_dir / "2026-04-13-090000.json").write_text(
        '{"session_id": "2026-04-13-090000", "goal_summary": "旧历史"}\n',
        encoding="utf-8",
    )

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent([_decision(user_message="请先说说用途")]),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    result = await app.run_turn("想买新包")

    assert result.session["session_id"] != "2026-04-13-090000"
    assert "goal_summary" not in result.session


@pytest.mark.asyncio
async def test_app_supports_basic_three_turn_ask_user_loop(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent(
            [
                _decision(user_message="先说说用途", session_updates={"category": "户外装备"}),
                _decision(user_message="预算大概多少", session_updates={"product_type": "冲锋衣"}),
                _decision(
                    user_message="还有其他偏好吗",
                    session_updates={"goal_summary": "补齐徒步外层"},
                ),
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    first = await app.run_turn("想买冲锋衣")
    second = await app.run_turn("周末徒步")
    third = await app.run_turn("预算3000")
    saved_session = store.load_session()

    assert first.user_message == "先说说用途"
    assert second.user_message == "预算大概多少"
    assert third.user_message == "还有其他偏好吗"
    assert saved_session is not None
    assert saved_session["category"] == "户外装备"
    assert saved_session["product_type"] == "冲锋衣"
    assert saved_session["goal_summary"] == "补齐徒步外层"


@pytest.mark.asyncio
async def test_app_multi_goal_flow_keeps_goal_context_and_refreshes_candidates(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    search_notes: list[str] = []

    async def fake_research(task_type: str, payload: dict[str, object]):
        from src.models.research import ProductSearchOutput

        product_type = payload["product_type"]
        note = f"{product_type} search"
        search_notes.append(note)
        return ProductSearchOutput(products=[], notes=note, suggested_followup=None)

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent(
            [
                _decision(
                    user_message="先看外层。",
                    next_action="dispatch_product_search",
                    action_payload={
                        "product_type": "冲锋衣",
                        "search_goal": "外层搜索",
                        "constraints": {
                            "budget": "unspecified",
                            "key_requirements": ["防水"],
                            "exclusions": [],
                        },
                    },
                    session_updates={
                        "goal_summary": "补齐周末徒步装备",
                        "existing_items": ["登山鞋"],
                        "missing_items": ["冲锋衣", "背包"],
                        "product_type": "冲锋衣",
                    },
                ),
                _decision(
                    user_message="外层先这样，接着看背包。",
                    next_action="recommend",
                    session_updates={
                        "goal_summary": "补齐周末徒步装备",
                        "existing_items": ["登山鞋"],
                        "missing_items": ["冲锋衣", "背包"],
                    },
                ),
                _decision(
                    user_message="现在切到背包搜索。",
                    next_action="dispatch_product_search",
                    action_payload={
                        "product_type": "背包",
                        "search_goal": "背包搜索",
                        "constraints": {
                            "budget": None,
                            "key_requirements": ["轻量"],
                            "exclusions": [],
                        },
                    },
                    session_updates={
                        "goal_summary": "补齐周末徒步装备",
                        "existing_items": ["登山鞋"],
                        "missing_items": ["冲锋衣", "背包"],
                        "product_type": "背包",
                    },
                ),
                _decision(
                    user_message="给出当前购买优先级。",
                    next_action="recommend",
                    session_updates={
                        "goal_summary": "补齐周末徒步装备",
                        "existing_items": ["登山鞋"],
                        "missing_items": ["冲锋衣", "背包"],
                    },
                ),
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    await app.run_turn("帮我补齐周末徒步装备")
    second = await app.run_turn(None)
    third = await app.run_turn("那背包呢")
    fourth = await app.run_turn(None)
    saved_session = store.load_session()

    assert second.user_message == "外层先这样，接着看背包。"
    assert third.session["pending_research_result"]["result"]["notes"] == "背包 search"
    assert fourth.user_message == "给出当前购买优先级。"
    assert search_notes == ["冲锋衣 search", "背包 search"]
    assert saved_session is not None
    assert saved_session["goal_summary"] == "补齐周末徒步装备"
    assert saved_session["existing_items"] == ["登山鞋"]
    assert saved_session["missing_items"] == ["冲锋衣", "背包"]
    assert saved_session["candidate_products"]["notes"] == "背包 search"
    assert saved_session["product_type"] == "背包"


@pytest.mark.asyncio
async def test_app_initialize_applies_pending_profile_updates_to_long_term_store(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-15-100000",
            "intent": "自用选购",
            "category": "户外装备",
            "decision_progress": {"recommendation_round": "完成"},
            "error_state": {
                "constraint_conflicts": [],
                "consecutive_negative_feedback": 0,
                "validation_warnings": [],
            },
            "pending_profile_updates": {
                "global_profile": {"lifestyle_tags": ["徒步"]},
                "category_preferences": {"primary_scenarios": ["周末徒步"]},
            },
        }
    )

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent([_decision(user_message="继续描述需求")]),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    session = await app.initialize_session()
    global_profile = store.load_global_profile()
    category_preferences = store.load_category_preferences("户外装备")

    assert "pending_profile_updates" not in session
    assert global_profile is not None
    assert global_profile["lifestyle_tags"] == ["徒步"]
    assert category_preferences is not None
    assert category_preferences["primary_scenarios"] == ["周末徒步"]


def test_generate_session_id_matches_documented_format() -> None:
    session_id = generate_session_id()

    assert len(session_id) == 17
    assert session_id[4] == "-"
    assert session_id[7] == "-"
    assert session_id[10] == "-"
