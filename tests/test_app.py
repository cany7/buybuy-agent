from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.app import ShoppingApplication, generate_session_id
from src.models.decision import DecisionOutput
from src.router.action_router import ActionRouter
from src.store.document_store import DocumentStore


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
async def test_app_runs_recovery_check_when_pending_profile_updates_exist(tmp_path: Path) -> None:
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

    assert len(calls) == 1
    assert calls[0]["session_id"] == "2026-04-14-120000"


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


def test_generate_session_id_matches_documented_format() -> None:
    session_id = generate_session_id()

    assert len(session_id) == 17
    assert session_id[4] == "-"
    assert session_id[7] == "-"
    assert session_id[10] == "-"
