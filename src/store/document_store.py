"""Core local JSON document store for Phase 1 session data."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DocumentStore:
    """Local JSON file CRUD rooted at the repository data directory."""

    base_dir: Path

    def __init__(self, base_dir: Path | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        self.base_dir = base_dir or repository_root / "data"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.user_profile_dir.mkdir(parents=True, exist_ok=True)
        self.category_preferences_dir.mkdir(parents=True, exist_ok=True)

    @property
    def sessions_dir(self) -> Path:
        return self.base_dir / "sessions"

    @property
    def knowledge_dir(self) -> Path:
        return self.base_dir / "knowledge"

    @property
    def user_profile_dir(self) -> Path:
        return self.base_dir / "user_profile"

    @property
    def category_preferences_dir(self) -> Path:
        return self.user_profile_dir / "category_preferences"

    @property
    def current_session_path(self) -> Path:
        return self.sessions_dir / "current_session.json"

    def load_session(self) -> dict[str, Any] | None:
        """Load the current active session if it exists."""

        return self._read_json(self.current_session_path)

    def save_session(self, state: dict[str, Any]) -> None:
        """Persist a complete session state and refresh last_updated."""

        payload = deepcopy(state)
        explicit_last_updated = payload.get("last_updated")
        if (
            not self.current_session_path.exists()
            and isinstance(explicit_last_updated, str)
            and explicit_last_updated.strip()
        ):
            payload["last_updated"] = explicit_last_updated
        else:
            payload["last_updated"] = datetime.now().isoformat(timespec="seconds")
        self._write_json(self.current_session_path, payload)

    def list_historical_sessions(self) -> list[dict[str, Any]]:
        """Return all historical session documents except current_session."""

        sessions: list[dict[str, Any]] = []
        for path in sorted(self.sessions_dir.glob("*.json")):
            if path.name == self.current_session_path.name:
                continue
            data = self._read_json(path)
            if data is not None:
                sessions.append(data)
        return sessions

    def apply_pending_profile_updates(self, session: dict[str, Any]) -> bool:
        """Apply or discard pending profile updates during startup recovery."""

        pending_updates = session.get("pending_profile_updates")
        if not isinstance(pending_updates, dict) or not pending_updates:
            return False

        should_apply = self._should_apply_pending_profile_updates(session)
        if not should_apply:
            updated_session = deepcopy(session)
            updated_session.pop("pending_profile_updates", None)
            self.save_session(updated_session)
            return False

        planned_writes = self._build_pending_profile_update_writes(session, pending_updates)
        original_payloads: dict[Path, dict[str, Any] | None] = {
            path: self._read_json(path)
            for path in planned_writes
            if path != self.current_session_path
        }

        updated_session = deepcopy(session)
        updated_session.pop("pending_profile_updates", None)

        try:
            for target_path, target_payload in planned_writes.items():
                if target_path == self.current_session_path:
                    continue
                self._write_json(target_path, target_payload)
            self.save_session(updated_session)
        except Exception:
            for rollback_path, rollback_payload in original_payloads.items():
                if rollback_payload is None:
                    if rollback_path.exists():
                        rollback_path.unlink()
                else:
                    self._write_json(rollback_path, rollback_payload)
            raise
        return should_apply

    def load_knowledge(self, category: str, product_type: str | None = None) -> dict[str, Any] | None:
        """Load category knowledge, optionally selecting a single product_type section."""

        path = self.knowledge_dir / f"{category}.json"
        data = self._read_json(path)
        if data is None:
            return None
        if product_type is None:
            return data

        selected: dict[str, Any] = {
            "category": data.get("category", category),
            "last_updated": data.get("last_updated"),
            "category_knowledge": deepcopy(data.get("category_knowledge", {})),
        }
        product_types = data.get("product_types")
        if isinstance(product_types, dict) and product_type in product_types:
            selected["product_types"] = {product_type: deepcopy(product_types[product_type])}
        return selected

    def save_knowledge(self, category: str, data: dict[str, Any]) -> None:
        """Create or replace one category knowledge document."""

        payload = deepcopy(data)
        payload["category"] = category
        payload["last_updated"] = self._current_date_string()
        self._write_json(self.knowledge_dir / f"{category}.json", payload)

    def merge_product_type(self, category: str, product_type: str, data: dict[str, Any]) -> None:
        """Merge one product_type section into an existing category knowledge file."""

        path = self.knowledge_dir / f"{category}.json"
        current = self._read_json(path) or {
            "category": category,
            "category_knowledge": {},
            "product_types": {},
        }
        product_types = current.get("product_types")
        if not isinstance(product_types, dict):
            product_types = {}
        product_types[product_type] = deepcopy(data)
        current["product_types"] = product_types
        current["category"] = category
        current["last_updated"] = self._current_date_string()
        self._write_json(path, current)

    def load_global_profile(self) -> dict[str, Any] | None:
        """Load the global user profile if it exists."""

        return self._read_json(self.user_profile_dir / "global_profile.json")

    def save_global_profile(self, updates: dict[str, Any]) -> None:
        """Apply section-level replacement updates to the global profile."""

        path = self.user_profile_dir / "global_profile.json"
        current = self._read_json(path) or {}
        merged = self._merge_sections(current, updates)
        merged["last_updated"] = self._current_date_string()
        self._write_json(path, merged)

    def load_category_preferences(self, category: str) -> dict[str, Any] | None:
        """Load one category preference document if it exists."""

        return self._read_json(self.category_preferences_dir / f"{category}.json")

    def save_category_preferences(self, category: str, updates: dict[str, Any]) -> None:
        """Apply section-level replacement updates to one category preference document."""

        path = self.category_preferences_dir / f"{category}.json"
        current = self._read_json(path) or {"category": category}
        merged = self._merge_sections(current, updates)
        merged["category"] = category
        merged["last_updated"] = self._current_date_string()
        self._write_json(path, merged)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError(f"Expected top-level JSON object in {path}")
        return data

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def _current_date_string(self) -> str:
        return datetime.now().date().isoformat()

    def _merge_sections(self, current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(current)
        for key, value in updates.items():
            merged[key] = deepcopy(value)
        return merged

    def _should_apply_pending_profile_updates(self, session: dict[str, Any]) -> bool:
        intent = session.get("intent")
        if intent not in {"自用选购", "复购/换代"}:
            return False

        recommendation_round = (session.get("decision_progress") or {}).get("recommendation_round")
        if recommendation_round != "完成":
            return False

        error_state = session.get("error_state") or {}
        if not isinstance(error_state, dict):
            return False

        if error_state.get("constraint_conflicts"):
            return False
        if error_state.get("validation_warnings"):
            return False
        if int(error_state.get("consecutive_negative_feedback", 0)) >= 2:
            return False

        return True

    def _build_pending_profile_update_writes(
        self,
        session: dict[str, Any],
        pending_updates: dict[str, Any],
    ) -> dict[Path, dict[str, Any]]:
        planned_writes: dict[Path, dict[str, Any]] = {}

        global_profile_updates = pending_updates.get("global_profile")
        if isinstance(global_profile_updates, dict) and global_profile_updates:
            path = self.user_profile_dir / "global_profile.json"
            current = self._read_json(path) or {}
            merged = self._merge_sections(current, global_profile_updates)
            merged["last_updated"] = self._current_date_string()
            planned_writes[path] = merged

        category_preferences_updates = pending_updates.get("category_preferences")
        if isinstance(category_preferences_updates, dict) and category_preferences_updates:
            category = session.get("category")
            if not isinstance(category, str) or not category.strip():
                raise ValueError(
                    "session.category is required when applying category_preferences updates."
                )
            path = self.category_preferences_dir / f"{category}.json"
            current = self._read_json(path) or {"category": category}
            merged = self._merge_sections(current, category_preferences_updates)
            merged["category"] = category
            merged["last_updated"] = self._current_date_string()
            planned_writes[path] = merged

        return planned_writes
