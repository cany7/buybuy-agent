from __future__ import annotations

from pathlib import Path

import pytest

from src.store.document_store import DocumentStore


def test_load_knowledge_returns_none_when_missing(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    assert store.load_knowledge("户外装备") is None


def test_save_and_selective_load_knowledge(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_knowledge(
        "户外装备",
        {
            "category_knowledge": {"shared_concepts": [{"name": "GORE-TEX"}]},
            "product_types": {
                "冲锋衣": {"tradeoffs": [{"dimensions": ["防水", "透气"]}]},
                "登山鞋": {"tradeoffs": [{"dimensions": ["支撑", "重量"]}]},
            },
        },
    )

    selected = store.load_knowledge("户外装备", "冲锋衣")

    assert selected is not None
    assert selected["category"] == "户外装备"
    assert selected["category_knowledge"]["shared_concepts"][0]["name"] == "GORE-TEX"
    assert selected["product_types"] == {
        "冲锋衣": {"tradeoffs": [{"dimensions": ["防水", "透气"]}]}
    }


def test_selective_load_knowledge_omits_other_product_types(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_knowledge(
        "户外装备",
        {
            "category_knowledge": {"brand_landscape": [{"brand": "Arc'teryx"}]},
            "product_types": {
                "冲锋衣": {"decision_dimensions": [{"name": "防水"}]},
                "登山鞋": {"decision_dimensions": [{"name": "支撑"}]},
            },
        },
    )

    selected = store.load_knowledge("户外装备", "不存在的类型")

    assert selected is not None
    assert "product_types" not in selected


def test_merge_product_type_preserves_existing_sections(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_knowledge(
        "户外装备",
        {
            "category_knowledge": {"shared_concepts": [{"name": "GORE-TEX"}]},
            "product_types": {"冲锋衣": {"decision_dimensions": [{"name": "防水"}]}},
        },
    )

    store.merge_product_type("户外装备", "登山鞋", {"decision_dimensions": [{"name": "支撑"}]})
    knowledge = store.load_knowledge("户外装备")

    assert knowledge is not None
    assert knowledge["product_types"]["冲锋衣"]["decision_dimensions"][0]["name"] == "防水"
    assert knowledge["product_types"]["登山鞋"]["decision_dimensions"][0]["name"] == "支撑"


def test_merge_product_type_creates_file_when_missing(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    store.merge_product_type("数码电子", "手机", {"decision_dimensions": [{"name": "续航"}]})
    knowledge = store.load_knowledge("数码电子")

    assert knowledge is not None
    assert knowledge["category"] == "数码电子"
    assert knowledge["product_types"]["手机"]["decision_dimensions"][0]["name"] == "续航"


def test_profile_loaders_return_none_when_missing(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")

    assert store.load_global_profile() is None
    assert store.load_category_preferences("户外装备") is None


def test_save_global_profile_replaces_sections(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_global_profile(
        {
            "demographics": {"gender": "男", "age_range": "25-34", "location": "上海"},
            "notes": ["初始记录"],
        }
    )

    store.save_global_profile(
        {
            "consumption_traits": {"decision_style": "深度研究型"},
            "notes": ["新记录"],
        }
    )
    profile = store.load_global_profile()

    assert profile is not None
    assert profile["demographics"]["location"] == "上海"
    assert profile["consumption_traits"]["decision_style"] == "深度研究型"
    assert profile["notes"] == ["新记录"]
    assert profile["last_updated"]


def test_save_category_preferences_replaces_sections(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_category_preferences(
        "户外装备",
        {
            "consumption_traits": {
                "preferred_brands": [{"brand": "Arc'teryx"}],
                "anti_preferences": [{"item": "某品牌X"}],
            },
            "primary_scenarios": ["周末徒步"],
        },
    )
    store.save_category_preferences(
        "户外装备",
        {
            "consumption_traits": {"preferred_brands": [{"brand": "Patagonia"}]},
            "purchase_history": [{"product_type": "冲锋衣", "chosen_product": "Beta LT"}],
        },
    )
    preferences = store.load_category_preferences("户外装备")

    assert preferences is not None
    assert preferences["category"] == "户外装备"
    assert preferences["consumption_traits"] == {
        "preferred_brands": [{"brand": "Patagonia"}]
    }
    assert preferences["primary_scenarios"] == ["周末徒步"]
    assert preferences["purchase_history"][0]["chosen_product"] == "Beta LT"
    assert preferences["last_updated"]


def test_apply_pending_profile_updates_writes_long_term_profiles(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    session = {
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
            "category_preferences": {
                "primary_scenarios": ["周末徒步"],
                "consumption_traits": {"preferred_brands": [{"brand": "Arc'teryx"}]},
            },
        },
    }
    store.save_session(session)

    applied = store.apply_pending_profile_updates(store.load_session() or {})
    current_session = store.load_session()
    global_profile = store.load_global_profile()
    category_preferences = store.load_category_preferences("户外装备")

    assert applied is True
    assert current_session is not None
    assert "pending_profile_updates" not in current_session
    assert global_profile is not None
    assert global_profile["lifestyle_tags"] == ["徒步"]
    assert category_preferences is not None
    assert category_preferences["primary_scenarios"] == ["周末徒步"]
    assert category_preferences["consumption_traits"]["preferred_brands"] == [
        {"brand": "Arc'teryx"}
    ]


def test_apply_pending_profile_updates_writes_long_term_profiles_for_repurchase_intent(
    tmp_path: Path,
) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-15-100000",
            "intent": "复购/换代",
            "category": "户外装备",
            "decision_progress": {"recommendation_round": "完成"},
            "error_state": {
                "constraint_conflicts": [],
                "consecutive_negative_feedback": 0,
                "validation_warnings": [],
            },
            "pending_profile_updates": {
                "global_profile": {"lifestyle_tags": ["通勤", "徒步"]},
                "category_preferences": {
                    "primary_scenarios": ["旧装备换代"],
                    "purchase_history": [
                        {"product_type": "冲锋衣", "chosen_product": "Beta LT"}
                    ],
                },
            },
        }
    )

    applied = store.apply_pending_profile_updates(store.load_session() or {})
    current_session = store.load_session()
    global_profile = store.load_global_profile()
    category_preferences = store.load_category_preferences("户外装备")

    assert applied is True
    assert current_session is not None
    assert "pending_profile_updates" not in current_session
    assert global_profile is not None
    assert global_profile["lifestyle_tags"] == ["通勤", "徒步"]
    assert category_preferences is not None
    assert category_preferences["primary_scenarios"] == ["旧装备换代"]
    assert category_preferences["purchase_history"] == [
        {"product_type": "冲锋衣", "chosen_product": "Beta LT"}
    ]


def test_apply_pending_profile_updates_skips_gift_and_clears_draft(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-15-100000",
            "intent": "送礼",
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

    applied = store.apply_pending_profile_updates(store.load_session() or {})
    current_session = store.load_session()

    assert applied is False
    assert current_session is not None
    assert "pending_profile_updates" not in current_session
    assert store.load_global_profile() is None
    assert store.load_category_preferences("户外装备") is None


def test_apply_pending_profile_updates_skips_consulting_intent_and_clears_draft(
    tmp_path: Path,
) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-15-100000",
            "intent": "纯咨询",
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

    applied = store.apply_pending_profile_updates(store.load_session() or {})
    current_session = store.load_session()

    assert applied is False
    assert current_session is not None
    assert "pending_profile_updates" not in current_session
    assert store.load_global_profile() is None
    assert store.load_category_preferences("户外装备") is None


def test_apply_pending_profile_updates_skips_when_error_state_is_unstable(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-15-100000",
            "intent": "自用选购",
            "category": "户外装备",
            "decision_progress": {"recommendation_round": "完成"},
            "error_state": {
                "constraint_conflicts": [],
                "consecutive_negative_feedback": 2,
                "validation_warnings": [],
            },
            "pending_profile_updates": {"global_profile": {"lifestyle_tags": ["徒步"]}},
        }
    )

    applied = store.apply_pending_profile_updates(store.load_session() or {})
    current_session = store.load_session()

    assert applied is False
    assert current_session is not None
    assert "pending_profile_updates" not in current_session
    assert store.load_global_profile() is None


def test_apply_pending_profile_updates_requires_category_for_category_preferences(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-15-100000",
            "intent": "自用选购",
            "decision_progress": {"recommendation_round": "完成"},
            "error_state": {
                "constraint_conflicts": [],
                "consecutive_negative_feedback": 0,
                "validation_warnings": [],
            },
            "pending_profile_updates": {
                "category_preferences": {"primary_scenarios": ["周末徒步"]}
            },
        }
    )

    with pytest.raises(ValueError, match="session.category is required"):
        store.apply_pending_profile_updates(store.load_session() or {})

    current_session = store.load_session()

    assert current_session is not None
    assert "pending_profile_updates" in current_session
    assert store.load_global_profile() is None


def test_apply_pending_profile_updates_is_atomic_when_validation_fails(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_session(
        {
            "session_id": "2026-04-15-100000",
            "intent": "自用选购",
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

    with pytest.raises(ValueError, match="session.category is required"):
        store.apply_pending_profile_updates(store.load_session() or {})

    current_session = store.load_session()

    assert current_session is not None
    assert "pending_profile_updates" in current_session
    assert store.load_global_profile() is None
