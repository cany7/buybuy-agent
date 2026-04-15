"""Profile context provider for global and category-scoped user memory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.store.document_store import DocumentStore

SessionState = dict[str, Any]
REQUIRED_DEMOGRAPHICS = {"gender", "age_range", "location"}


@dataclass(slots=True)
class ProfileContextProvider:
    """Load deterministic profile context or inject onboarding guidance."""

    store: DocumentStore

    def build_context(self, session: SessionState) -> str:
        """Return profile context for the active session."""

        global_profile = self.store.load_global_profile()
        demographics = global_profile.get("demographics") if isinstance(global_profile, dict) else None
        if not isinstance(global_profile, dict) or not self._has_complete_demographics(demographics):
            return "## [系统标注] 新用户，请先执行轻量 onboarding（性别、年龄段、城市）。"

        parts = [
            "## 用户画像",
            json.dumps(global_profile, ensure_ascii=False, indent=2),
        ]

        category = session.get("category")
        if isinstance(category, str) and category.strip():
            category_preferences = self.store.load_category_preferences(category)
            if isinstance(category_preferences, dict):
                parts.extend(
                    [
                        "",
                        f"## 品类偏好：{category}",
                        json.dumps(category_preferences, ensure_ascii=False, indent=2),
                    ]
                )

        return "\n".join(parts)

    def _has_complete_demographics(self, demographics: Any) -> bool:
        if not isinstance(demographics, dict):
            return False
        return all(
            isinstance(demographics.get(field), str) and demographics[field].strip()
            for field in REQUIRED_DEMOGRAPHICS
        )
