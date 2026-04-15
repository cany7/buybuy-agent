from __future__ import annotations

from pathlib import Path

from src.context.session_provider import SessionContextProvider
from src.store.document_store import DocumentStore


def test_session_provider_creates_new_session_with_documented_id_format(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    provider = SessionContextProvider(store=store)

    session = provider.load_or_create_session()

    assert len(session["session_id"]) == 17
    assert session["session_id"][4] == "-"
    assert session["session_id"][7] == "-"
    assert session["session_id"][10] == "-"


def test_session_provider_builds_context_with_pending_research_result(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-100000",
            "goal_summary": "补齐徒步外层",
            "existing_items": ["登山鞋"],
            "missing_items": ["冲锋衣"],
            "pending_research_result": {
                "type": "product_search",
                "result": {"products": [], "notes": "搜索完成"},
            },
        }
    )
    provider = SessionContextProvider(store=store)

    context = provider.build_context()

    assert "## 当前会话状态" in context
    assert "补齐徒步外层" in context
    assert "登山鞋" in context
    assert "missing_items" in context
    assert "## 研究结果（待消费）" in context
    assert "类型：product_search" in context
    assert "搜索完成" in context
