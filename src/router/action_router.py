"""Action routing for application-layer next_action execution."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from inspect import isawaitable
from typing import Any, Awaitable, Callable

from src.models.research import CategoryResearchOutput, ProductSearchOutput
from src.store.document_store import DocumentStore

SessionState = dict[str, Any]
ResearchOutput = CategoryResearchOutput | ProductSearchOutput
ResearchExecutor = Callable[[str, dict[str, Any]], Awaitable[ResearchOutput]]
MessageEmitter = Callable[[str], object]

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
    user_message_delivered: bool = False


class ActionRouter:
    """Passive executor of system actions declared by the main agent."""

    def __init__(
        self,
        store: DocumentStore,
        research_executor: ResearchExecutor,
    ) -> None:
        self._store = store
        self._research_executor = research_executor

    async def route(
        self,
        decision: Any,
        session: SessionState,
        *,
        emit_user_message: MessageEmitter | None = None,
    ) -> RouteResult:
        """Execute one next_action and persist session-side effects."""

        original_session = deepcopy(session)
        working_session = deepcopy(session)

        session_updates = getattr(decision, "session_updates", None)
        self._apply_session_updates(working_session, session_updates)

        replaced_pending_research_result = False
        wait_for_user_input = False
        should_continue = False
        user_message_delivered = False
        next_action = getattr(decision, "next_action", None)
        user_message = self._get_user_message(decision)

        if next_action in {"ask_user", "recommend"}:
            wait_for_user_input = True
        elif next_action == "dispatch_product_search":
            action_payload = getattr(decision, "action_payload", None)
            if not isinstance(action_payload, dict):
                return self._handle_route_error(
                    working_session,
                    user_message=user_message,
                    error_message="dispatch_product_search requires action_payload.",
                )
            if emit_user_message is not None:
                await self._deliver_user_message(emit_user_message, user_message)
                user_message_delivered = True
            try:
                result = await self._research_executor("dispatch_product_search", action_payload)
            except ValueError as error:
                return self._handle_route_error(
                    working_session,
                    user_message=user_message,
                    error_message=str(error),
                )
            if not isinstance(result, ProductSearchOutput):
                return self._handle_route_error(
                    working_session,
                    user_message=user_message,
                    error_message="dispatch_product_search must return ProductSearchOutput.",
                )
            self._handle_product_search_result(working_session, result)
            replaced_pending_research_result = True
            should_continue = True
        elif next_action == "dispatch_category_research":
            action_payload = getattr(decision, "action_payload", None)
            if not isinstance(action_payload, dict):
                return self._handle_route_error(
                    working_session,
                    user_message=user_message,
                    error_message="dispatch_category_research requires action_payload.",
                )
            if emit_user_message is not None:
                await self._deliver_user_message(emit_user_message, user_message)
                user_message_delivered = True
            try:
                result = await self._research_executor("dispatch_category_research", action_payload)
            except ValueError as error:
                return self._handle_route_error(
                    working_session,
                    user_message=user_message,
                    error_message=str(error),
                )
            if not isinstance(result, CategoryResearchOutput):
                return self._handle_route_error(
                    working_session,
                    user_message=user_message,
                    error_message="dispatch_category_research must return CategoryResearchOutput.",
                )
            self._handle_category_research_result(working_session, result)
            replaced_pending_research_result = True
            should_continue = True
        elif next_action == "onboard_user":
            try:
                self._write_demographics(getattr(decision, "action_payload", None))
            except ValueError as error:
                return self._handle_route_error(
                    working_session,
                    user_message=user_message,
                    error_message=str(error),
                )
            wait_for_user_input = True
        else:
            return self._handle_route_error(
                working_session,
                user_message=user_message,
                error_message=f"Unsupported next_action: {next_action}",
            )

        self._run_common_post_actions(
            working_session=working_session,
            original_session=original_session,
            decision=decision,
        )
        self._store.save_session(working_session)

        return RouteResult(
            user_message=user_message,
            wait_for_user_input=wait_for_user_input,
            should_continue=should_continue,
            session=working_session,
            replaced_pending_research_result=replaced_pending_research_result,
            user_message_delivered=user_message_delivered,
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

    def _handle_category_research_result(
        self,
        session: SessionState,
        result: CategoryResearchOutput,
    ) -> None:
        payload = result.model_dump(mode="json")
        existing_knowledge = self._store.load_knowledge(result.category)
        if existing_knowledge is None:
            self._store.save_knowledge(
                result.category,
                {
                    "category_knowledge": payload["category_knowledge"],
                    "product_types": {
                        result.product_type_name: payload["product_type_knowledge"],
                    },
                },
            )
        else:
            self._store.merge_product_type(
                result.category,
                result.product_type_name,
                payload["product_type_knowledge"],
            )

        session["pending_research_result"] = {
            "type": "category_research",
            "result": payload,
        }

    def _run_common_post_actions(
        self,
        *,
        working_session: SessionState,
        original_session: SessionState,
        decision: Any,
    ) -> None:
        original_round = (original_session.get("decision_progress") or {}).get("recommendation_round")
        current_round = (working_session.get("decision_progress") or {}).get("recommendation_round")
        if current_round == "完成" and original_round != "完成":
            profile_updates = getattr(decision, "profile_updates", None)
            if not profile_updates:
                raise ValueError(
                    "profile_updates is required when recommendation_round becomes 完成."
                )
            working_session["pending_profile_updates"] = deepcopy(profile_updates)

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

    async def _deliver_user_message(
        self,
        emitter: MessageEmitter,
        user_message: str,
    ) -> None:
        delivered = emitter(user_message)
        if isawaitable(delivered):
            await delivered

    def _handle_route_error(
        self,
        session: SessionState,
        *,
        user_message: str,
        error_message: str,
    ) -> RouteResult:
        error_state = session.get("error_state")
        if not isinstance(error_state, dict):
            error_state = {}

        validation_warnings = error_state.get("validation_warnings")
        if not isinstance(validation_warnings, list):
            validation_warnings = []
        validation_warnings.append(error_message)
        error_state["validation_warnings"] = validation_warnings
        session["error_state"] = error_state
        self._store.save_session(session)

        return RouteResult(
            user_message=user_message,
            wait_for_user_input=True,
            should_continue=False,
            session=session,
        )

    def _get_user_message(self, decision: Any) -> str:
        user_message = getattr(decision, "user_message", None)
        if isinstance(user_message, str) and user_message.strip():
            return user_message
        return "系统暂时无法处理该请求，请补充信息后重试。"
