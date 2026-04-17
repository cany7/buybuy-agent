"""JSONL session logger for turn-level analysis."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models.decision import DecisionOutput
from src.router.action_router import RouteResult

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionActivity:
    """Derived counters for one session based on the JSONL audit log."""

    turn_count: int = 0
    product_search_count: int = 0
    requirement_mining_turn_count: int = 0


class SessionLogger:
    """Append one JSON object per turn to the session log."""

    def __init__(self, base_dir: Path | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        data_dir = base_dir or repository_root / "data"
        self.log_path = data_dir / "sessions" / "session_log.jsonl"

    def log_turn(
        self,
        *,
        session_before: dict[str, Any],
        session_after: dict[str, Any],
        context: str,
        user_input: str | None,
        decision: DecisionOutput,
        route_result: RouteResult,
    ) -> None:
        """Persist one completed turn as a JSONL record."""

        warnings = self._collect_warnings(session_before, session_after, context)
        errors = self._collect_errors(decision, route_result, warnings)
        level = "ERROR" if errors else "WARNING" if warnings else "INFO"
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "level": level,
            "session_id": session_after.get("session_id") or session_before.get("session_id"),
            "user_input": user_input,
            "decision": decision.model_dump(mode="json"),
            "stage": {
                "before": self._extract_stage(session_before),
                "after": self._extract_stage(session_after),
                "assessment": decision.internal_reasoning.stage_assessment,
            },
            "next_action_result": {
                "next_action": decision.next_action,
                "wait_for_user_input": route_result.wait_for_user_input,
                "should_continue": route_result.should_continue,
                "user_message_delivered": route_result.user_message_delivered,
                "details": route_result.action_metrics or {},
            },
            "warnings": warnings,
            "errors": errors,
        }
        self._append_record(record)
        self._emit_standard_log(level, record)

    def log_turn_exception(
        self,
        *,
        session: dict[str, Any],
        context: str,
        user_input: str | None,
        error: Exception,
    ) -> None:
        """Persist a turn record when the outer loop fails before RouteResult is available."""

        warnings = self._extract_staleness_warnings(context)
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "level": "ERROR",
            "session_id": session.get("session_id"),
            "user_input": user_input,
            "decision": None,
            "stage": {
                "before": self._extract_stage(session),
                "after": self._extract_stage(session),
                "assessment": None,
            },
            "next_action_result": None,
            "warnings": warnings,
            "errors": [str(error)],
        }
        self._append_record(record)
        LOGGER.error("Turn execution failed for session %s: %s", session.get("session_id"), error)

    def get_session_activity(self, session_id: str | None) -> SessionActivity:
        """Return lightweight counters for one session from the JSONL log."""

        if not isinstance(session_id, str) or not session_id.strip():
            return SessionActivity()

        turn_count = 0
        product_search_count = 0
        requirement_mining_turn_count = 0

        for record in self._iter_session_records(session_id.strip()):
            turn_count += 1
            details = ((record.get("next_action_result") or {}).get("details") or {})
            if details.get("result_type") == "product_search":
                product_search_count += 1
            assessment = (record.get("stage") or {}).get("assessment")
            if assessment == "需求挖掘":
                requirement_mining_turn_count += 1

        return SessionActivity(
            turn_count=turn_count,
            product_search_count=product_search_count,
            requirement_mining_turn_count=requirement_mining_turn_count,
        )

    def _append_record(self, record: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")

    def _emit_standard_log(self, level: str, record: dict[str, Any]) -> None:
        message = (
            "Session turn logged: session=%s next_action=%s level=%s"
            % (
                record.get("session_id"),
                (record.get("next_action_result") or {}).get("next_action"),
                level,
            )
        )
        if level == "ERROR":
            LOGGER.error(message)
        elif level == "WARNING":
            LOGGER.warning(message)
        else:
            LOGGER.info(message)

    def _collect_warnings(
        self,
        session_before: dict[str, Any],
        session_after: dict[str, Any],
        context: str,
    ) -> list[str]:
        warnings = self._extract_new_validation_warnings(session_before, session_after)
        warnings.extend(self._extract_new_boundary_warnings(session_before, session_after))
        warnings.extend(self._extract_staleness_warnings(context))
        return warnings

    def _collect_errors(
        self,
        decision: DecisionOutput,
        route_result: RouteResult,
        warnings: list[str],
    ) -> list[str]:
        details = route_result.action_metrics or {}
        explicit_error = details.get("error")
        if isinstance(explicit_error, str) and explicit_error.strip():
            return [explicit_error.strip()]
        if decision.next_action in {"ask_user", "recommend"}:
            return []
        if route_result.should_continue or decision.next_action == "onboard_user":
            return []
        return warnings

    def _extract_new_validation_warnings(
        self,
        session_before: dict[str, Any],
        session_after: dict[str, Any],
    ) -> list[str]:
        before = self._extract_validation_warnings(session_before)
        after = self._extract_validation_warnings(session_after)
        return after[len(before) :]

    def _extract_validation_warnings(self, session: dict[str, Any]) -> list[str]:
        error_state = session.get("error_state")
        if not isinstance(error_state, dict):
            return []
        validation_warnings = error_state.get("validation_warnings")
        if not isinstance(validation_warnings, list):
            return []
        return [warning for warning in validation_warnings if isinstance(warning, str)]

    def _extract_new_boundary_warnings(
        self,
        session_before: dict[str, Any],
        session_after: dict[str, Any],
    ) -> list[str]:
        before = self._extract_boundary_warnings(session_before)
        after = self._extract_boundary_warnings(session_after)
        return after[len(before) :]

    def _extract_boundary_warnings(self, session: dict[str, Any]) -> list[str]:
        error_state = session.get("error_state")
        if not isinstance(error_state, dict):
            return []

        events = error_state.get("events")
        if not isinstance(events, list):
            return []

        warnings: list[str] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("type") not in {"boundary_triggered", "boundary_blocked"}:
                continue
            details = event.get("details")
            if not isinstance(details, dict):
                continue
            message = details.get("message")
            if isinstance(message, str) and message.strip():
                warnings.append(message.strip())
        return warnings

    def _extract_staleness_warnings(self, context: str) -> list[str]:
        lines = context.splitlines()
        staleness_lines: list[str] = []
        collecting = False
        for line in lines:
            if line.startswith("## [系统标注] 会话已暂停"):
                collecting = True
            elif collecting and line.startswith("## "):
                break
            if collecting and line.strip():
                staleness_lines.append(line.strip())
        if not staleness_lines:
            return []
        return [" ".join(staleness_lines)]

    def _iter_session_records(self, session_id: str) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []

        records: list[dict[str, Any]] = []
        with self.log_path.open("r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("session_id") != session_id:
                    continue
                records.append(record)
        return records

    def _extract_stage(self, session: dict[str, Any]) -> str | None:
        decision_progress = session.get("decision_progress")
        if not isinstance(decision_progress, dict):
            return None
        stage = decision_progress.get("stage")
        return stage if isinstance(stage, str) and stage.strip() else None
