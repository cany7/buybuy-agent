from __future__ import annotations

import json
from datetime import date

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
        "candidate_products": {
            "products": [],
            "search_meta": {
                "retry_count": 0,
                "result_status": "ok",
                "search_expanded": False,
                "expansion_notes": None,
            },
            "notes": "none",
        },
        "error_state": {
            "constraint_conflicts": [],
            "search_retries": 0,
            "consecutive_negative_feedback": 0,
            "validation_warnings": [],
            "events": [{"type": "insufficient_results", "details": {"retry_count": 1}}],
        },
    }

    store.save_session(state)
    saved = store.load_session()

    assert saved is not None
    assert saved["session_id"] == "2026-04-14-101500"
    assert "last_updated" in saved
    assert saved["pending_research_result"]["type"] == "product_search"
    assert "global_profile" in saved["pending_profile_updates"]
    assert saved["candidate_products"]["notes"] == "none"
    assert saved["candidate_products"]["search_meta"]["result_status"] == "ok"
    assert saved["error_state"]["events"][0]["type"] == "insufficient_results"


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


def test_replace_active_session_preserves_previous_current_as_history(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-14-101500",
            "goal_summary": "旧会话",
            "decision_progress": {"recommendation_round": "完成"},
        }
    )

    store.replace_active_session(
        {
            "session_id": "2026-04-14-111500",
            "decision_progress": {"recommendation_round": "未开始"},
        },
        preserve_current=True,
    )

    current = store.load_session()
    historical = store.list_historical_sessions()

    assert current is not None
    assert current["session_id"] == "2026-04-14-111500"
    assert len(historical) == 1
    assert historical[0]["session_id"] == "2026-04-14-101500"
    assert historical[0]["goal_summary"] == "旧会话"
    assert historical[0]["decision_progress"]["recommendation_round"] == "完成"
    assert historical[0]["last_updated"]


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


def test_load_knowledge_returns_none_when_category_file_missing(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    assert store.load_knowledge("不存在的品类") is None


def test_load_knowledge_selects_only_requested_product_type(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_knowledge(
        "户外装备",
        {
            "category_knowledge": {"seasonality": "四季"},
            "product_types": {
                "冲锋衣": {"core_dimensions": ["防水", "透气"]},
                "登山鞋": {"core_dimensions": ["抓地力", "支撑"]},
            },
        },
    )

    loaded = store.load_knowledge("户外装备", "冲锋衣")

    assert loaded is not None
    assert loaded["category"] == "户外装备"
    assert loaded["category_knowledge"] == {"seasonality": "四季"}
    assert loaded["product_types"] == {"冲锋衣": {"core_dimensions": ["防水", "透气"]}}
    assert "登山鞋" not in loaded["product_types"]


def test_load_knowledge_without_product_type_returns_full_document(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_knowledge(
        "户外装备",
        {
            "category_knowledge": {"seasonality": "四季"},
            "product_types": {
                "冲锋衣": {"core_dimensions": ["防水", "透气"]},
                "登山鞋": {"core_dimensions": ["抓地力", "支撑"]},
            },
        },
    )

    loaded = store.load_knowledge("户外装备")

    assert loaded is not None
    assert loaded["category"] == "户外装备"
    assert set(loaded["product_types"]) == {"冲锋衣", "登山鞋"}


def test_merge_product_type_preserves_existing_sections(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_knowledge(
        "户外装备",
        {
            "category_knowledge": {"seasonality": "四季"},
            "product_types": {
                "冲锋衣": {"core_dimensions": ["防水", "透气"]},
            },
        },
    )

    store.merge_product_type(
        "户外装备",
        "登山鞋",
        {"core_dimensions": ["抓地力", "支撑"]},
    )

    loaded = store.load_knowledge("户外装备")

    assert loaded is not None
    assert loaded["product_types"]["冲锋衣"] == {"core_dimensions": ["防水", "透气"]}
    assert loaded["product_types"]["登山鞋"] == {"core_dimensions": ["抓地力", "支撑"]}


def test_merge_product_type_creates_knowledge_file_if_missing(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    store.merge_product_type(
        "户外装备",
        "冲锋衣",
        {"core_dimensions": ["防水", "透气"]},
    )

    loaded = store.load_knowledge("户外装备")

    assert loaded is not None
    assert loaded["category"] == "户外装备"
    assert loaded["category_knowledge"] == {}
    assert loaded["product_types"]["冲锋衣"] == {"core_dimensions": ["防水", "透气"]}


def test_save_global_profile_creates_file(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    store.save_global_profile(
        {
            "demographics": {"gender": "女", "age_range": "25-34", "location": "上海"},
        }
    )

    saved = store.load_global_profile()

    assert saved is not None
    assert saved["demographics"]["location"] == "上海"
    assert saved["last_updated"] == date.today().isoformat()


def test_load_global_profile_returns_none_when_missing(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    assert store.load_global_profile() is None


def test_save_global_profile_replaces_only_updated_sections(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_global_profile(
        {
            "demographics": {"gender": "男", "age_range": "25-34", "location": "上海"},
            "consumption_traits": {"budget_sensitivity": "中"},
        }
    )

    store.save_global_profile(
        {
            "consumption_traits": {"budget_sensitivity": "高"},
        }
    )

    saved = store.load_global_profile()

    assert saved is not None
    assert saved["demographics"] == {"gender": "男", "age_range": "25-34", "location": "上海"}
    assert saved["consumption_traits"] == {"budget_sensitivity": "高"}


def test_load_category_preferences_returns_none_when_missing(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    assert store.load_category_preferences("户外装备") is None


def test_save_category_preferences_creates_and_replaces_sections(tmp_path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_category_preferences(
        "户外装备",
        {
            "brand_preferences": {"preferred": ["Patagonia"]},
            "consumption_traits": {"fit_preference": "宽松"},
        },
    )

    store.save_category_preferences(
        "户外装备",
        {
            "consumption_traits": {"fit_preference": "合身"},
        },
    )

    saved = store.load_category_preferences("户外装备")

    assert saved is not None
    assert saved["category"] == "户外装备"
    assert saved["brand_preferences"] == {"preferred": ["Patagonia"]}
    assert saved["consumption_traits"] == {"fit_preference": "合身"}
    assert saved["last_updated"] == date.today().isoformat()
