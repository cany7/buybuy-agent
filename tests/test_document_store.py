from __future__ import annotations

import json

from src.store.document_store import DocumentStore


def test_document_store_initializes_phase_two_directories(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    assert store.sessions_dir.is_dir()
    assert store.knowledge_dir.is_dir()
    assert store.user_profile_dir.is_dir()
    assert store.category_preferences_dir.is_dir()


def test_load_session_returns_none_when_file_is_missing(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    assert store.load_session() is None


def test_save_session_updates_last_updated_and_preserves_system_fields(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    state = {
        "session_id": "2026-04-14-101500",
        "intent": "自用选购",
        "pending_research_result": {"type": "product_search", "result": {"notes": "x"}},
        "pending_profile_updates": {"global_profile": {"lifestyle_tags": ["徒步"]}},
        "candidate_products": {"products": [], "notes": "none"},
    }

    store.save_session(state)
    saved = store.load_session()

    assert saved is not None
    assert saved["session_id"] == "2026-04-14-101500"
    assert "last_updated" in saved
    assert saved["pending_research_result"]["type"] == "product_search"
    assert "global_profile" in saved["pending_profile_updates"]
    assert saved["candidate_products"]["notes"] == "none"


def test_save_session_writes_utf8_json(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    state = {"session_id": "2026-04-14-101500", "goal_summary": "补齐一套徒步装备"}

    store.save_session(state)

    raw = store.current_session_path.read_text(encoding="utf-8")
    assert "补齐一套徒步装备" in raw


def test_list_historical_sessions_ignores_current_session(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session({"session_id": "2026-04-14-101500"})

    history_path = store.sessions_dir / "2026-04-13-090000.json"
    history_path.write_text(
        json.dumps({"session_id": "2026-04-13-090000"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sessions = store.list_historical_sessions()

    assert sessions == [{"session_id": "2026-04-13-090000"}]


def test_save_session_updates_current_session_without_touching_history(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    history_path = store.sessions_dir / "2026-04-13-090000.json"
    history_path.write_text(
        json.dumps(
            {"session_id": "2026-04-13-090000", "goal_summary": "旧会话"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    store.save_session({"session_id": "2026-04-14-101500", "intent": "自用选购"})
    store.save_session({"session_id": "2026-04-14-101500", "intent": "送礼"})

    current = store.load_session()
    historical = store.list_historical_sessions()

    assert current is not None
    assert current["intent"] == "送礼"
    assert historical == [{"session_id": "2026-04-13-090000", "goal_summary": "旧会话"}]


def test_apply_pending_profile_updates_returns_false_without_draft(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    assert store.apply_pending_profile_updates({"session_id": "2026-04-14-101500"}) is False


def test_apply_pending_profile_updates_is_stub_in_phase_one(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    applied = store.apply_pending_profile_updates(
        {
            "session_id": "2026-04-14-101500",
            "pending_profile_updates": {"global_profile": {"gender": "男"}},
        }
    )

    assert applied is False
    assert not (store.user_profile_dir / "global_profile.json").exists()
