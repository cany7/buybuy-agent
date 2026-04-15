from __future__ import annotations

import importlib
from pathlib import Path

from src.store.document_store import DocumentStore


def _load_profile_provider_class():
    module = importlib.import_module("src.context.profile_provider")
    return getattr(module, "ProfileContextProvider")


def test_profile_provider_marks_new_user_for_onboarding(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    profile_provider_cls = _load_profile_provider_class()
    provider = profile_provider_cls(store=store)

    context = provider.build_context({"category": "户外装备"})

    assert "新用户，请先执行轻量 onboarding" in context


def test_profile_provider_marks_incomplete_demographics_for_onboarding(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_global_profile({"demographics": {"gender": "男", "location": "上海"}})
    profile_provider_cls = _load_profile_provider_class()
    provider = profile_provider_cls(store=store)

    context = provider.build_context({"category": "户外装备"})

    assert "新用户，请先执行轻量 onboarding" in context


def test_profile_provider_injects_global_profile_and_category_preferences(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_global_profile(
        {
            "demographics": {"gender": "男", "age_range": "25-34", "location": "上海"},
            "lifestyle_tags": ["徒步"],
        }
    )
    store.save_category_preferences(
        "户外装备",
        {
            "primary_scenarios": ["周末徒步"],
            "consumption_traits": {"preferred_brands": [{"brand": "Arc'teryx"}]},
        },
    )
    profile_provider_cls = _load_profile_provider_class()
    provider = profile_provider_cls(store=store)

    context = provider.build_context({"category": "户外装备"})

    assert "上海" in context
    assert "徒步" in context
    assert "周末徒步" in context
    assert "Arc'teryx" in context
