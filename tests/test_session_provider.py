from __future__ import annotations

from datetime import datetime, timedelta
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


def test_session_provider_adds_staleness_note_for_expired_session(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    stale_time = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
    store.save_session(
        {
            "session_id": "2026-04-14-100000",
            "last_updated": stale_time,
        }
    )
    provider = SessionContextProvider(store=store)

    context = provider.build_context()

    assert "## [系统标注] 会话已暂停" in context
    assert "8 天" in context


def test_session_provider_adds_pending_research_expiry_note_when_stale(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    stale_time = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
    store.save_session(
        {
            "session_id": "2026-04-14-100000",
            "last_updated": stale_time,
            "pending_research_result": {
                "type": "product_search",
                "result": {"products": [], "notes": "旧搜索结果"},
            },
        }
    )
    provider = SessionContextProvider(store=store)

    context = provider.build_context()

    assert "## [系统标注] 会话已暂停" in context
    assert "产品搜索结果可能已过期" in context


def test_session_provider_does_not_trigger_recovery_check_during_regular_context_build(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class RecordingDocumentStore(DocumentStore):
        def apply_pending_profile_updates(self, session: dict[str, object]) -> bool:
            calls.append(session)
            return super().apply_pending_profile_updates(session)

    store = RecordingDocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-100000",
            "pending_profile_updates": {"global_profile": {"lifestyle_tags": ["徒步"]}},
        }
    )
    provider = SessionContextProvider(store=store)

    context = provider.build_context()

    assert "pending_profile_updates" in context
    assert calls == []


def test_session_provider_adds_soft_note_before_third_distinct_category_research(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-100000",
            "error_state": {
                "events": [
                    {"type": "dispatch_category_research", "details": {"category": "户外装备"}},
                    {"type": "dispatch_category_research", "details": {"category": "数码产品"}},
                ]
            },
        }
    )
    provider = SessionContextProvider(store=store)

    context = provider.build_context()

    assert "[系统标注] 本 session 已调研 2 个品类" in context


def test_session_provider_deduplicates_repeated_category_research_events(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-100000",
            "error_state": {
                "events": [
                    {"type": "dispatch_category_research", "details": {"category": " 户外装备 "}},
                    {"type": "dispatch_category_research", "details": {"category": "户外装备"}},
                    {"type": "dispatch_category_research", "details": {"category": "数码产品"}},
                ]
            },
        }
    )
    provider = SessionContextProvider(store=store)

    context = provider.build_context()

    assert "[系统标注] 本 session 已调研 2 个品类" in context


def test_session_provider_keeps_soft_note_after_third_distinct_category_research(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-100000",
            "error_state": {
                "events": [
                    {"type": "dispatch_category_research", "details": {"category": "户外装备"}},
                    {"type": "dispatch_category_research", "details": {"category": "数码产品"}},
                    {"type": "dispatch_category_research", "details": {"category": "智能家居"}},
                ]
            },
        }
    )
    provider = SessionContextProvider(store=store)

    context = provider.build_context()

    assert "[系统标注] 本 session 已调研 3 个品类" in context
