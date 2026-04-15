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
        """Phase 1 stub. Recovery-time profile writes are implemented in Phase 2."""

        pending_updates = session.get("pending_profile_updates")
        if not pending_updates:
            return False
        return False

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
