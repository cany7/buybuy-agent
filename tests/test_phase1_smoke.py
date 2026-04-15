from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.app import ShoppingApplication
from src.cli import run_cli
from src.models.decision import DecisionOutput
from src.models.research import ProductSearchOutput
from src.router.action_router import ActionRouter
from src.store.document_store import DocumentStore


class RecordingDocumentStore(DocumentStore):
    """DocumentStore that records every session snapshot written during the smoke flow."""

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__(base_dir=base_dir)
        self.saved_sessions: list[dict[str, Any]] = []

    def save_session(self, state: dict[str, Any]) -> None:
        super().save_session(state)
        saved = self.load_session()
        if saved is None:
            raise ValueError("Expected current session to exist after save.")
        self.saved_sessions.append(saved)


@dataclass
class ScriptedMainAgent:
    """Deterministic main-agent script for the Phase 1 CLI smoke test."""

    decisions: list[DecisionOutput]
    contexts: list[str]

    async def run(self, context: str, user_message: str) -> DecisionOutput:
        self.contexts.append(context)
        if not self.decisions:
            raise AssertionError("No scripted decisions left for smoke test.")
        return self.decisions.pop(0)


def _decision(**overrides: object) -> DecisionOutput:
    payload: dict[str, object] = {
        "user_message": "继续。",
        "internal_reasoning": {
            "state_summary": "smoke test step",
            "stage_assessment": "需求挖掘",
        },
        "next_action": "ask_user",
    }
    payload.update(overrides)
    return DecisionOutput.model_validate(payload)


@pytest.mark.asyncio
async def test_phase1_cli_smoke_flow(tmp_path: Path, monkeypatch, capsys) -> None:
    store = RecordingDocumentStore(base_dir=tmp_path / "data")

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "户外装备.json"
    runtime_knowledge = store.knowledge_dir / "户外装备.json"
    runtime_knowledge.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture_path, runtime_knowledge)

    profile_path = store.user_profile_dir / "global_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        '{\n  "demographics": {"gender": "男", "age_range": "25-34", "location": "上海"}\n}\n',
        encoding="utf-8",
    )

    contexts: list[str] = []
    main_agent = ScriptedMainAgent(
        decisions=[
            _decision(
                user_message="你主要在什么场景穿？预算大概多少？",
                session_updates={
                    "category": "户外装备",
                    "product_type": "冲锋衣",
                    "decision_progress": {
                        "stage": "需求挖掘",
                        "recommendation_round": "未开始",
                    },
                    "goal_summary": "选一件适合徒步的冲锋衣",
                },
            ),
            _decision(
                user_message="好的，我先按你的场景去搜索几款候选。",
                next_action="dispatch_product_search",
                action_payload={
                    "product_type": "冲锋衣",
                    "search_goal": "适合周末徒步和4000m级高海拔的冲锋衣",
                    "constraints": {
                        "budget": "2500-3500",
                        "gender": "男款",
                        "key_requirements": ["高防水", "兼顾透气"],
                        "scenario": "周末徒步+4000m",
                        "exclusions": [],
                    },
                },
                session_updates={
                    "decision_progress": {
                        "stage": "产品搜索",
                        "recommendation_round": "第一轮",
                    },
                    "requirement_profile": {
                        "basic_info": [
                            {
                                "dimension": "预算",
                                "value": "3000左右",
                                "priority": 4,
                                "confidence": 1,
                                "urgency": 4,
                                "source": "用户明确表示",
                            }
                        ],
                        "dimension_weights": [
                            {
                                "dimension": "防水",
                                "priority": 4,
                                "confidence": 1,
                                "urgency": 4,
                                "source": "用户明确表达",
                            }
                        ],
                    },
                },
            ),
            _decision(
                user_message=(
                    "先给你三类方向：1）综合均衡；2）更耐用；3）更轻量。"
                    " 你先看看更偏向哪一类？"
                ),
                next_action="recommend",
                session_updates={
                    "decision_progress": {
                        "stage": "推荐",
                        "recommendation_round": "第一轮",
                    }
                },
            ),
            _decision(
                user_message="如果更看重耐用和恶劣天气稳定性，我建议优先看 Beta LT。",
                next_action="recommend",
                session_updates={
                    "decision_progress": {
                        "stage": "推荐",
                        "recommendation_round": "完成",
                    },
                    "error_state": {
                        "constraint_conflicts": [],
                        "search_retries": 0,
                        "consecutive_negative_feedback": 0,
                        "validation_warnings": [],
                        "events": [],
                    },
                },
                profile_updates={
                    "global_profile": {"lifestyle_tags": ["徒步", "周末户外"]},
                    "category_preferences": {
                        "consumption_traits": {
                            "anti_preferences": [{"value": "国产品牌"}]
                        },
                        "primary_scenarios": ["周末徒步", "4000m级高海拔"],
                    },
                },
            ),
        ],
        contexts=contexts,
    )

    async def fake_research(task_type: str, payload: dict[str, Any]) -> ProductSearchOutput:
        assert task_type == "dispatch_product_search"
        assert payload["product_type"] == "冲锋衣"
        return ProductSearchOutput.model_validate(
            {
                "products": [
                    {
                        "name": "Beta LT",
                        "brand": "Arc'teryx",
                        "price": {"display": "¥3800", "currency": "CNY", "amount": 3800},
                        "specs": {"weight": "395g"},
                        "features": ["GORE-TEX ePE 硬壳", "适合恶劣天气外层防护"],
                        "pros": ["防护强", "做工稳定"],
                        "cons": ["价格较高"],
                        "sources": ["https://example.com/beta-lt-review"],
                        "source_consistency": "high",
                    },
                    {
                        "name": "Granite Crest",
                        "brand": "Patagonia",
                        "price": {"display": "¥2600", "currency": "CNY", "amount": 2600},
                        "specs": {"weight": "400g"},
                        "features": ["轻量徒步外层", "兼顾防水与透气"],
                        "pros": ["更均衡", "价格相对友好"],
                        "cons": ["极端场景防护不如重型硬壳"],
                        "sources": ["https://example.com/granite-crest-review"],
                        "source_consistency": "high",
                    },
                ],
                "notes": "smoke search ok",
                "suggested_followup": "关注耐用与重量的 tradeoff",
            }
        )

    app = ShoppingApplication(
        store=store,
        main_agent=main_agent,
        action_router=ActionRouter(store=store, research_executor=fake_research),
    )

    inputs = iter(
        [
            "想买一件冲锋衣",
            "周末经常徒步，预算3000左右，之前淋过雨所以防水要好些。",
            "1和2感兴趣，我更看重耐不耐用。",
            "/quit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    await run_cli(app)

    output = capsys.readouterr().out
    current_session = store.load_session()

    assert "Shopping Agent CLI 已启动" in output
    assert "你主要在什么场景穿？预算大概多少？" in output
    assert "好的，我先按你的场景去搜索几款候选。" in output
    assert "先给你三类方向" in output
    assert "如果更看重耐用和恶劣天气稳定性" in output
    assert "已退出，当前 session 已保留。" in output

    assert len(store.saved_sessions) >= 4
    assert current_session is not None
    assert current_session["session_id"]
    assert current_session["candidate_products"]["notes"] == "smoke search ok"
    assert current_session["pending_profile_updates"]["global_profile"]["lifestyle_tags"] == [
        "徒步",
        "周末户外",
    ]
    assert current_session["decision_progress"]["recommendation_round"] == "完成"
    assert current_session["last_updated"]

    assert any("## 研究结果（待消费）" in context for context in contexts)
    assert any("## 品类知识：户外装备" in context for context in contexts)
    assert any("GORE-TEX" in context for context in contexts)
