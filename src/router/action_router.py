"""Action routing for application-layer next_action execution."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from src.models.decision import DecisionOutput
from src.models.research import ProductSearchOutput
from src.store.document_store import DocumentStore

SessionState = dict[str, Any]
ResearchExecutor = Callable[[str, dict[str, Any]], Awaitable[ProductSearchOutput]]

SESSION_UPDATE_WHITELIST = {
    "intent",
    "product_type",
    "category",
    "decision_progress",
    "requirement_profile",
    "jtbd_signals",
    "error_state",
    "goal_summary",
    "existing_items",
    "missing_items",
}


@dataclass(slots=True)
class RouteResult:
    """Result of routing one DecisionOutput."""

    user_message: str
    wait_for_user_input: bool
    should_continue: bool
    session: SessionState
    replaced_pending_research_result: bool = False


class ActionRouter:
    """Passive executor of system actions declared by the main agent."""

    def __init__(
        self,
        store: DocumentStore,
        research_executor: ResearchExecutor,
    ) -> None:
        self._store = store
        self._research_executor = research_executor

    async def route(self, decision: DecisionOutput, session: SessionState) -> RouteResult:
        """Execute one next_action and persist session-side effects."""

        original_session = deepcopy(session)
        working_session = deepcopy(session)

        self._apply_session_updates(working_session, decision.session_updates)

        replaced_pending_research_result = False
        wait_for_user_input = False
        should_continue = False

        if decision.next_action in {"ask_user", "recommend"}:
            wait_for_user_input = True
        elif decision.next_action == "dispatch_product_search":
            if decision.action_payload is None:
                raise ValueError("dispatch_product_search requires action_payload.")
            result = await self._research_executor(
                "dispatch_product_search",
                decision.action_payload,
            )
            self._handle_product_search_result(working_session, result)
            replaced_pending_research_result = True
            should_continue = True
        elif decision.next_action == "dispatch_category_research":
            if decision.action_payload is None:
                raise ValueError("dispatch_category_research requires action_payload.")
            raise NotImplementedError("dispatch_category_research will be added in P2.2.")
        elif decision.next_action == "onboard_user":
            self._write_demographics(decision.action_payload)
            wait_for_user_input = True
        else:
            raise ValueError(f"Unsupported next_action: {decision.next_action}")

        self._run_common_post_actions(
            working_session=working_session,
            original_session=original_session,
            decision=decision,
        )
        self._store.save_session(working_session)

        return RouteResult(
            user_message=decision.user_message,
            wait_for_user_input=wait_for_user_input,
            should_continue=should_continue,
            session=working_session,
            replaced_pending_research_result=replaced_pending_research_result,
        )

    def _apply_session_updates(
        self,
        session: SessionState,
        session_updates: dict[str, Any] | None,
    ) -> None:
        if not session_updates:
            return

        unknown_keys = set(session_updates) - SESSION_UPDATE_WHITELIST
        if unknown_keys:
            invalid = ", ".join(sorted(unknown_keys))
            raise ValueError(f"Unsupported session_updates keys: {invalid}")

        for key, value in session_updates.items():
            session[key] = value

    def _handle_product_search_result(
        self,
        session: SessionState,
        result: ProductSearchOutput,
    ) -> None:
        payload = result.model_dump(mode="json")
        session["pending_research_result"] = {
            "type": "product_search",
            "result": payload,
        }
        session["candidate_products"] = {
            **payload,
            "last_refreshed": datetime.now().isoformat(timespec="seconds"),
        }
        decision_progress = dict(session.get("decision_progress") or {})
        decision_progress["recommendation_round"] = "未开始"
        session["decision_progress"] = decision_progress

    def _run_common_post_actions(
        self,
        *,
        working_session: SessionState,
        original_session: SessionState,
        decision: DecisionOutput,
    ) -> None:
        original_round = (original_session.get("decision_progress") or {}).get("recommendation_round")
        current_round = (working_session.get("decision_progress") or {}).get("recommendation_round")
        if current_round == "完成" and original_round != "完成" and decision.profile_updates:
            working_session["pending_profile_updates"] = deepcopy(decision.profile_updates)

    def _write_demographics(self, action_payload: dict[str, Any] | None) -> None:
        if not isinstance(action_payload, dict):
            raise ValueError("onboard_user requires demographics payload.")
        demographics = action_payload.get("demographics")
        if not isinstance(demographics, dict):
            raise ValueError("onboard_user requires a demographics object.")

        profile_path = self._store.user_profile_dir / "global_profile.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if profile_path.exists():
            with profile_path.open("r", encoding="utf-8") as file:
                loaded = json.load(file)
            if isinstance(loaded, dict):
                existing = loaded

        existing["demographics"] = demographics
        with profile_path.open("w", encoding="utf-8") as file:
            json.dump(existing, file, ensure_ascii=False, indent=2)
            file.write("\n")
