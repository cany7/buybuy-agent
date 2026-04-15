"""Phase 1 session context provider."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.store.document_store import DocumentStore
from src.utils.session import generate_session_id

SessionState = dict[str, Any]
STALE_SESSION_DAYS = 7


@dataclass(slots=True)
class SessionContextProvider:
    """Load and format the current session state for prompt injection."""

    store: DocumentStore

    def load_or_create_session(self) -> SessionState:
        """Load the current session or create a new minimal session."""

        session = self.store.load_session()
        if session is not None:
            return session

        created = {
            "session_id": generate_session_id(),
            "decision_progress": {"recommendation_round": "未开始"},
        }
        self.store.save_session(created)
        loaded = self.store.load_session()
        if loaded is None:
            raise ValueError("Failed to create current_session.json")
        return loaded

    def build_context(self, session: SessionState | None = None) -> str:
        """Format session state using the documented injection layout."""

        current_session = session or self.load_or_create_session()
        session_json = json.dumps(current_session, ensure_ascii=False, indent=2)
        parts = ["## 当前会话状态", session_json]
        staleness_note = self._build_staleness_note(current_session)
        if staleness_note:
            parts.extend(["", staleness_note])

        pending = current_session.get("pending_research_result")
        if isinstance(pending, dict):
            pending_type = pending.get("type", "unknown")
            pending_result = pending.get("result", {})
            pending_json = json.dumps(pending_result, ensure_ascii=False, indent=2)
            parts.extend(
                [
                    "",
                    "## 研究结果（待消费）",
                    f"类型：{pending_type}",
                    pending_json,
                ]
            )

        return "\n".join(parts)

    def _build_staleness_note(self, session: SessionState) -> str:
        last_updated = session.get("last_updated")
        if not isinstance(last_updated, str) or not last_updated.strip():
            return ""

        try:
            updated_at = datetime.fromisoformat(last_updated)
        except ValueError:
            return ""

        paused_days = (datetime.now() - updated_at).days
        if paused_days <= STALE_SESSION_DAYS:
            return ""

        lines = [f"## [系统标注] 会话已暂停 {paused_days} 天。"]
        if isinstance(session.get("pending_research_result"), dict):
            lines.append("产品搜索结果可能已过期（价格/库存可能变化）。")
        lines.append("请先向用户确认需求是否仍然一致。")
        return "\n".join(lines)
