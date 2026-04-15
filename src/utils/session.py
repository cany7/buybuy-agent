"""Session-related shared helpers."""

from __future__ import annotations

from datetime import datetime


def generate_session_id(now: datetime | None = None) -> str:
    """Generate a session id in the documented format."""

    current = now or datetime.now()
    return current.strftime("%Y-%m-%d-%H%M%S")
