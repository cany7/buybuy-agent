from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest

from src.app import ShoppingApplication
from src.models.decision import DecisionOutput
from src.models.research import SearchMeta
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


def _search_meta(
    *,
    retry_count: int = 0,
    result_status: Literal["ok", "insufficient_results", "partial_results", "failed"] = "ok",
    search_expanded: bool = False,
    expansion_notes: str | None = None,
) -> SearchMeta:
    return SearchMeta(
        retry_count=retry_count,
        result_status=result_status,
        search_expanded=search_expanded,
        expansion_notes=expansion_notes,
    )


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

        return ProductSearchOutput(
            products=[],
            search_meta=_search_meta(),
            notes="new",
            suggested_followup=None,
        )

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
async def test_app_dispatch_flow_sets_pending_result_refreshes_candidates_and_consumes_it(
    tmp_path: Path,
) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, object]):
        from src.models.research import ProductSearchOutput

        assert task_type == "dispatch_product_search"
        assert payload["product_type"] == "冲锋衣"
        return ProductSearchOutput(
            products=[],
            search_meta=_search_meta(),
            notes="dispatch flow search",
            suggested_followup="继续比较耐用性",
        )

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent(
            [
                _decision(
                    user_message="先确认一下预算。",
                    next_action="ask_user",
                    session_updates={
                        "category": "户外装备",
                        "product_type": "冲锋衣",
                        "goal_summary": "买一件徒步外层",
                    },
                ),
                _decision(
                    user_message="我先去搜几款。",
                    next_action="dispatch_product_search",
                    action_payload={
                        "product_type": "冲锋衣",
                        "search_goal": "找几款适合徒步的冲锋衣",
                        "constraints": {
                            "budget": "unspecified",
                            "key_requirements": ["防水"],
                            "exclusions": [],
                        },
                    },
                    session_updates={
                        "goal_summary": "买一件徒步外层",
                        "decision_progress": {"recommendation_round": "第一轮"},
                    },
                ),
                _decision(
                    user_message="给你三款方向，先看整体差异。",
                    next_action="recommend",
                    session_updates={
                        "goal_summary": "买一件徒步外层",
                        "decision_progress": {"recommendation_round": "第一轮"},
                    },
                ),
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    first = await app.run_turn("想买冲锋衣")
    second = await app.run_turn("预算3000左右")
    saved_after_dispatch = store.load_session()
    third = await app.run_turn(None)
    saved_after_consume = store.load_session()

    assert first.user_message == "先确认一下预算。"
    assert second.should_continue is True
    assert second.session["pending_research_result"]["result"]["notes"] == "dispatch flow search"
    assert second.session["candidate_products"]["notes"] == "dispatch flow search"
    assert saved_after_dispatch is not None
    assert saved_after_dispatch["pending_research_result"]["type"] == "product_search"
    assert saved_after_dispatch["candidate_products"]["suggested_followup"] == "继续比较耐用性"
    assert third.user_message == "给你三款方向，先看整体差异。"
    assert "pending_research_result" not in third.session
    assert saved_after_consume is not None
    assert "pending_research_result" not in saved_after_consume
    assert saved_after_consume["candidate_products"]["notes"] == "dispatch flow search"


@pytest.mark.asyncio
async def test_app_multi_goal_flow_keeps_goal_context_and_refreshes_candidates(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    search_notes: list[str] = []

    async def fake_research(task_type: str, payload: dict[str, object]):
        from src.models.research import ProductSearchOutput

        product_type = payload["product_type"]
        note = f"{product_type} search"
        search_notes.append(note)
        return ProductSearchOutput(
            products=[],
            search_meta=_search_meta(),
            notes=note,
            suggested_followup=None,
        )

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
async def test_app_recommendation_completion_writes_pending_profile_updates_draft(
    tmp_path: Path,
) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-15-100000",
            "intent": "自用选购",
            "category": "户外装备",
            "decision_progress": {"recommendation_round": "第二轮"},
        }
    )

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent(
            [
                _decision(
                    user_message="这轮就收敛到这三款里。",
                    next_action="recommend",
                    session_updates={
                        "decision_progress": {"recommendation_round": "完成"},
                    },
                    profile_updates={
                        "global_profile": {"lifestyle_tags": ["徒步"]},
                        "category_preferences": {"primary_scenarios": ["周末徒步"]},
                    },
                )
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    result = await app.run_turn("我决定好了")
    saved_session = store.load_session()

    assert result.user_message == "这轮就收敛到这三款里。"
    assert result.session["pending_profile_updates"]["global_profile"]["lifestyle_tags"] == ["徒步"]
    assert saved_session is not None
    assert saved_session["pending_profile_updates"]["category_preferences"]["primary_scenarios"] == [
        "周末徒步"
    ]


@pytest.mark.asyncio
async def test_app_injects_soft_note_before_third_distinct_category_research(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    captured_contexts: list[str] = []

    @dataclass
    class RecordingMainAgent:
        decisions: list[DecisionOutput]

        async def run(self, context: str, user_message: str) -> DecisionOutput:
            captured_contexts.append(context)
            return self.decisions.pop(0)

    async def fake_research(task_type: str, payload: dict[str, object]):
        from src.models.research import CategoryResearchOutput

        return CategoryResearchOutput.model_validate(
            {
                "category": payload["category"],
                "category_knowledge": {
                    "data_sources": ["https://example.com/guide"],
                    "product_type_overview": [],
                    "shared_concepts": [],
                    "brand_landscape": [],
                },
                "product_type_name": payload["product_type"],
                "product_type_knowledge": {
                    "subtypes": {},
                    "decision_dimensions": [],
                    "tradeoffs": [],
                    "price_tiers": [],
                    "scenario_mapping": [],
                    "common_misconceptions": [],
                },
            }
        )

    app = ShoppingApplication(
        store=store,
        main_agent=RecordingMainAgent(
            [
                _decision(
                    next_action="dispatch_category_research",
                    action_payload={
                        "category": "户外装备",
                        "product_type": "冲锋衣",
                        "user_context": "第一次调研",
                    },
                ),
                _decision(
                    next_action="dispatch_category_research",
                    action_payload={
                        "category": "数码产品",
                        "product_type": "耳机",
                        "user_context": "第二次调研",
                    },
                ),
                _decision(
                    next_action="dispatch_category_research",
                    action_payload={
                        "category": "智能家居",
                        "product_type": "扫地机器人",
                        "user_context": "第三次调研",
                    },
                ),
                _decision(user_message="继续推进"),
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    await app.run_turn("第一次")
    await app.run_turn("第二次")
    await app.run_turn("第三次")
    await app.run_turn(None)

    assert len(captured_contexts) == 4
    assert "[系统标注] 本 session 已调研" not in captured_contexts[0]
    assert "[系统标注] 本 session 已调研" not in captured_contexts[1]
    assert "[系统标注] 本 session 已调研 2 个品类" in captured_contexts[2]
    assert "[系统标注] 本 session 已调研 3 个品类" in captured_contexts[3]


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


@pytest.mark.asyncio
async def test_app_initialize_creates_fresh_session_without_injecting_history(
    tmp_path: Path,
) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    (store.sessions_dir / "2026-04-13-090000.json").write_text(
        '{"session_id": "2026-04-13-090000", "goal_summary": "旧历史", "product_type": "冲锋衣"}\n',
        encoding="utf-8",
    )

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent([_decision(user_message="继续描述需求")]),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    session = await app.initialize_session()
    historical_sessions = store.list_historical_sessions()

    assert session["session_id"] != "2026-04-13-090000"
    assert session["decision_progress"]["recommendation_round"] == "未开始"
    assert "goal_summary" not in session
    assert len(historical_sessions) == 1
    assert historical_sessions[0]["session_id"] == "2026-04-13-090000"
    assert historical_sessions[0]["goal_summary"] == "旧历史"


@pytest.mark.asyncio
async def test_app_initialize_can_start_new_session_while_preserving_previous_one(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-15-100000",
            "intent": "自用选购",
            "category": "户外装备",
            "goal_summary": "继续上次选购",
            "decision_progress": {"recommendation_round": "完成"},
            "error_state": {
                "constraint_conflicts": [],
                "consecutive_negative_feedback": 0,
                "validation_warnings": [],
            },
            "pending_profile_updates": {
                "global_profile": {"lifestyle_tags": ["徒步"]},
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

    new_session = await app.initialize_session(start_new_session=True)
    historical_sessions = store.list_historical_sessions()
    global_profile = store.load_global_profile()

    assert new_session["session_id"] != "2026-04-15-100000"
    assert new_session["decision_progress"]["recommendation_round"] == "未开始"
    assert "goal_summary" not in new_session
    assert len(historical_sessions) == 1
    assert historical_sessions[0]["session_id"] == "2026-04-15-100000"
    assert "pending_profile_updates" not in historical_sessions[0]
    assert global_profile is not None
    assert global_profile["lifestyle_tags"] == ["徒步"]


@pytest.mark.asyncio
async def test_app_category_research_post_processing_creates_then_merges_knowledge(
    tmp_path: Path,
) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, object]):
        from src.models.research import CategoryResearchOutput

        assert task_type == "dispatch_category_research"
        category = payload["category"]
        product_type = payload["product_type"]
        return CategoryResearchOutput.model_validate(
            {
                "category": category,
                "category_knowledge": {
                    "data_sources": ["https://example.com/guide"],
                    "product_type_overview": [],
                    "shared_concepts": [
                        {
                            "name": "GORE-TEX",
                            "description": "常见防水透气面料",
                            "relevant_product_types": [product_type],
                        }
                    ],
                    "brand_landscape": [],
                },
                "product_type_name": product_type,
                "product_type_knowledge": {
                    "subtypes": {},
                    "decision_dimensions": [
                        {
                            "name": f"{product_type} 维度",
                            "objectivity": "可量化",
                            "importance": "高",
                            "ambiguity_risk": "低",
                        }
                    ],
                    "tradeoffs": [],
                    "price_tiers": [],
                    "scenario_mapping": [],
                    "common_misconceptions": [],
                },
            }
        )

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent(
            [
                _decision(
                    user_message="先补品类知识。",
                    next_action="dispatch_category_research",
                    action_payload={
                        "category": "户外装备",
                        "product_type": "冲锋衣",
                        "user_context": "第一次调研",
                    },
                    session_updates={"category": "户外装备", "product_type": "冲锋衣"},
                ),
                _decision(
                    user_message="继续补另一类产品类型。",
                    next_action="dispatch_category_research",
                    action_payload={
                        "category": "户外装备",
                        "product_type": "登山鞋",
                        "user_context": "第二次调研",
                    },
                    session_updates={"category": "户外装备", "product_type": "登山鞋"},
                ),
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    first = await app.run_turn("想买户外装备")
    second = await app.run_turn(None)
    knowledge = store.load_knowledge("户外装备")

    assert first.should_continue is True
    assert second.should_continue is True
    assert second.session["pending_research_result"]["type"] == "category_research"
    assert knowledge is not None
    assert knowledge["product_types"]["冲锋衣"]["decision_dimensions"][0]["name"] == "冲锋衣 维度"
    assert knowledge["product_types"]["登山鞋"]["decision_dimensions"][0]["name"] == "登山鞋 维度"
    assert knowledge["category_knowledge"]["shared_concepts"][0]["name"] == "GORE-TEX"


@pytest.mark.asyncio
async def test_app_product_search_empty_results_do_not_crash_and_are_kept_for_consumption(
    tmp_path: Path,
) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, object]):
        from src.models.research import ProductSearchOutput

        return ProductSearchOutput(
            products=[],
            search_meta=_search_meta(
                retry_count=1,
                result_status="insufficient_results",
                search_expanded=True,
                expansion_notes="已扩搜但仍无高匹配结果",
            ),
            notes="empty result search",
            suggested_followup="建议放宽预算或场景限制",
        )

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent(
            [
                _decision(
                    user_message="我先去搜一下。",
                    next_action="dispatch_product_search",
                    action_payload={
                        "product_type": "冲锋衣",
                        "search_goal": "测试空结果",
                        "constraints": {
                            "budget": None,
                            "key_requirements": ["超轻量"],
                            "exclusions": [],
                        },
                    },
                )
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    result = await app.run_turn("想看超轻量冲锋衣")
    saved_session = store.load_session()

    assert result.should_continue is True
    assert result.session["pending_research_result"]["result"]["products"] == []
    assert result.session["pending_research_result"]["result"]["notes"] == "empty result search"
    assert saved_session is not None
    assert saved_session["candidate_products"]["products"] == []
    assert saved_session["candidate_products"]["suggested_followup"] == "建议放宽预算或场景限制"
    assert saved_session["error_state"]["events"][0]["type"] == "insufficient_results"


@pytest.mark.asyncio
async def test_app_invalid_dispatch_payload_from_executor_is_recorded_without_crash(
    tmp_path: Path,
) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    async def fake_research(task_type: str, payload: dict[str, object]):
        from src.agents.research_agent import validate_product_search_payload

        assert task_type == "dispatch_product_search"
        validate_product_search_payload(payload)
        raise AssertionError("invalid payload should have been rejected before execution")

    app = ShoppingApplication(
        store=store,
        main_agent=FakeMainAgent(
            [
                _decision(
                    user_message="这次搜索条件还不完整。",
                    next_action="dispatch_product_search",
                    action_payload={"product_type": "冲锋衣"},
                )
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    result = await app.run_turn("想买冲锋衣")
    saved_session = store.load_session()

    assert result.wait_for_user_input is True
    assert result.should_continue is False
    assert saved_session is not None
    assert (
        saved_session["error_state"]["validation_warnings"][0]
        == "action_payload.search_goal is required and must be a non-empty string."
    )


@pytest.mark.asyncio
async def test_app_onboarding_flow_writes_demographics_and_then_resumes_normal_dialogue(
    tmp_path: Path,
) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    captured_contexts: list[str] = []

    @dataclass
    class RecordingMainAgent:
        decisions: list[DecisionOutput]

        async def run(self, context: str, user_message: str) -> DecisionOutput:
            captured_contexts.append(context)
            return self.decisions.pop(0)

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=RecordingMainAgent(
            [
                _decision(
                    user_message="先补充一下基础信息。",
                    next_action="onboard_user",
                    action_payload={
                        "demographics": {
                            "gender": "男",
                            "age_range": "25-34",
                            "location": "上海",
                        }
                    },
                ),
                _decision(
                    user_message="现在可以继续说说你的使用场景了。",
                    next_action="ask_user",
                    session_updates={"category": "户外装备", "product_type": "冲锋衣"},
                ),
            ]
        ),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    first = await app.run_turn("想买冲锋衣")
    global_profile = store.load_global_profile()
    second = await app.run_turn("想买冲锋衣")

    assert "新用户，请先执行轻量 onboarding" in captured_contexts[0]
    assert global_profile is not None
    assert global_profile["demographics"] == {
        "gender": "男",
        "age_range": "25-34",
        "location": "上海",
    }
    assert first.wait_for_user_input is True
    assert "新用户，请先执行轻量 onboarding" not in captured_contexts[1]
    assert "## 用户画像" in captured_contexts[1]
    assert "上海" in captured_contexts[1]
    assert second.user_message == "现在可以继续说说你的使用场景了。"
    assert second.wait_for_user_input is True


@pytest.mark.asyncio
async def test_app_existing_user_context_does_not_include_onboarding_note(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_global_profile(
        {
            "demographics": {
                "gender": "男",
                "age_range": "25-34",
                "location": "上海",
            },
            "lifestyle_tags": ["徒步"],
        }
    )
    captured_contexts: list[str] = []

    @dataclass
    class RecordingMainAgent:
        decisions: list[DecisionOutput]

        async def run(self, context: str, user_message: str) -> DecisionOutput:
            captured_contexts.append(context)
            return self.decisions.pop(0)

    async def fake_research(task_type: str, payload: dict[str, object]):
        raise AssertionError("research should not run")

    app = ShoppingApplication(
        store=store,
        main_agent=RecordingMainAgent([_decision(user_message="请说说这次想买什么。")]),
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    result = await app.run_turn("想买新鞋")

    assert "新用户，请先执行轻量 onboarding" not in captured_contexts[0]
    assert "## 用户画像" in captured_contexts[0]
    assert "上海" in captured_contexts[0]
    assert result.user_message == "请说说这次想买什么。"


def test_generate_session_id_matches_documented_format() -> None:
    session_id = generate_session_id()

    assert len(session_id) == 17
    assert session_id[4] == "-"
    assert session_id[7] == "-"
    assert session_id[10] == "-"
