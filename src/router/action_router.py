"""Action routing for application-layer next_action execution."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from inspect import isawaitable
from time import monotonic
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from src.agents.research_agent import (
    validate_category_research_output,
    validate_product_search_output,
)
from src.models.research import CategoryResearchOutput, ProductSearchOutput, SearchMeta
from src.store.document_store import DocumentStore

SessionState = dict[str, Any]
ResearchOutput = CategoryResearchOutput | ProductSearchOutput
ResearchExecutor = Callable[[str, dict[str, Any]], Awaitable[ResearchOutput]]
MessageEmitter = Callable[[str], object]
REQUIRED_DEMOGRAPHICS_FIELDS = ("gender", "age_range", "location")

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
    action_metrics: dict[str, Any] | None = None


@dataclass(slots=True)
class ResearchExecutionResult:
    """Result of running one research task with application-layer retry metadata."""

    result: ResearchOutput | None
    retry_count: int
    failure_kind: str | None = None
    error_message: str | None = None


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
            action_metrics = {"result_type": next_action}
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
            started_at = monotonic()
            execution = await self._execute_research_with_retry(
                "dispatch_product_search",
                action_payload,
            )
            research_duration_ms = int((monotonic() - started_at) * 1000)
            if execution.failure_kind == "invalid_payload":
                return self._handle_route_error(
                    working_session,
                    user_message=user_message,
                    error_message=execution.error_message or "dispatch_product_search payload is invalid.",
                )
            product_degradation_error: str | None = None
            if execution.result is None:
                product_degradation_error = execution.error_message or "Product search failed."
                product_result = self._build_failed_product_search_output(
                    action_payload=action_payload,
                    retry_count=execution.retry_count,
                    reason=execution.failure_kind or "api_failure",
                    error_message=product_degradation_error,
                )
            elif not isinstance(execution.result, ProductSearchOutput):
                product_degradation_error = "ResearchOutput 结构化结果解析失败。"
                product_result = self._build_failed_product_search_output(
                    action_payload=action_payload,
                    retry_count=execution.retry_count,
                    reason="parse_failure",
                    error_message=product_degradation_error,
                )
            else:
                product_result = self._apply_product_search_retry_count(
                    execution.result,
                    execution.retry_count,
                )
            product_result, warnings = validate_product_search_output(product_result)
            self._append_validation_warnings(working_session, warnings)
            self._handle_product_search_result(working_session, product_result)
            replaced_pending_research_result = True
            should_continue = True
            action_metrics = {
                "result_type": "product_search",
                "research_duration_ms": research_duration_ms,
                "product_count": len(product_result.products),
                "search_meta": product_result.search_meta.model_dump(mode="json"),
                "executor_retry_count": execution.retry_count,
                "degraded": product_degradation_error is not None,
                "degradation_reason": execution.failure_kind,
                "validation_warning_count": len(warnings),
            }
            if product_degradation_error is not None:
                action_metrics["error"] = product_degradation_error
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
            started_at = monotonic()
            execution = await self._execute_research_with_retry(
                "dispatch_category_research",
                action_payload,
            )
            research_duration_ms = int((monotonic() - started_at) * 1000)
            if execution.failure_kind == "invalid_payload":
                return self._handle_route_error(
                    working_session,
                    user_message=user_message,
                    error_message=execution.error_message or "dispatch_category_research payload is invalid.",
                )
            category_degradation_error: str | None = None
            if execution.result is None:
                category_degradation_error = execution.error_message or "Category research failed."
                category_result = self._build_failed_category_research_output(
                    action_payload=action_payload,
                    reason=execution.failure_kind or "api_failure",
                    error_message=category_degradation_error,
                )
            elif not isinstance(execution.result, CategoryResearchOutput):
                category_degradation_error = "ResearchOutput 结构化结果解析失败。"
                category_result = self._build_failed_category_research_output(
                    action_payload=action_payload,
                    reason="parse_failure",
                    error_message=category_degradation_error,
                )
            else:
                category_result = execution.result
            category_result, warnings = validate_category_research_output(category_result)
            self._append_validation_warnings(working_session, warnings)
            if category_degradation_error is None:
                self._handle_category_research_result(working_session, category_result)
            else:
                self._handle_failed_category_research_result(working_session, category_result)
            replaced_pending_research_result = True
            should_continue = True
            action_metrics = {
                "result_type": "category_research",
                "research_duration_ms": research_duration_ms,
                "category": category_result.category,
                "product_type": category_result.product_type_name,
                "executor_retry_count": execution.retry_count,
                "degraded": category_degradation_error is not None,
                "degradation_reason": execution.failure_kind,
                "validation_warning_count": len(warnings),
            }
            if category_degradation_error is not None:
                action_metrics["error"] = category_degradation_error
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
            action_metrics = {"result_type": "onboard_user"}
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
            action_metrics=action_metrics,
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

    async def _execute_research_with_retry(
        self,
        task_type: str,
        action_payload: dict[str, Any],
    ) -> ResearchExecutionResult:
        last_error: Exception | None = None
        for attempt in range(2):
            payload = (
                deepcopy(action_payload)
                if attempt == 0
                else self._build_research_retry_payload(task_type, action_payload)
            )
            try:
                result = await self._research_executor(task_type, payload)
                return ResearchExecutionResult(result=result, retry_count=attempt)
            except ValidationError as error:
                return ResearchExecutionResult(
                    result=None,
                    retry_count=attempt,
                    failure_kind="parse_failure",
                    error_message=str(error),
                )
            except ValueError as error:
                return ResearchExecutionResult(
                    result=None,
                    retry_count=attempt,
                    failure_kind="invalid_payload",
                    error_message=str(error),
                )
            except Exception as error:  # pragma: no cover - exercised in router tests
                last_error = error
                if attempt == 1:
                    break

        return ResearchExecutionResult(
            result=None,
            retry_count=1,
            failure_kind="api_failure",
            error_message=str(last_error) if last_error is not None else "Research execution failed.",
        )

    def _build_research_retry_payload(
        self,
        task_type: str,
        action_payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload = deepcopy(action_payload)
        retry_note = (
            "这是一次失败后的重试。请更换搜索关键词组合，并扩大来源覆盖范围；"
            "在保持核心约束不变的前提下，优先返回更稳妥、可验证的结构化结果。"
        )
        existing_brief = payload.get("research_brief")
        if isinstance(existing_brief, str) and existing_brief.strip():
            payload["research_brief"] = f"{existing_brief.rstrip()}\n{retry_note}"
        else:
            payload["research_brief"] = retry_note

        if task_type == "dispatch_product_search":
            payload["search_goal"] = f"{payload.get('search_goal', '')}".strip()
        return payload

    def _apply_product_search_retry_count(
        self,
        result: ProductSearchOutput,
        retry_count: int,
    ) -> ProductSearchOutput:
        if retry_count <= result.search_meta.retry_count:
            return result
        updated_meta = result.search_meta.model_copy(update={"retry_count": retry_count})
        return result.model_copy(update={"search_meta": updated_meta})

    def _build_failed_product_search_output(
        self,
        *,
        action_payload: dict[str, Any],
        retry_count: int,
        reason: str,
        error_message: str,
    ) -> ProductSearchOutput:
        product_type = action_payload.get("product_type")
        product_label = product_type if isinstance(product_type, str) and product_type.strip() else "当前产品"
        if reason == "parse_failure":
            notes = (
                f"{product_label} 的研究结果结构化结果解析失败。"
                "这轮我先不把不可靠的数据当作候选，建议你稍后重试，或先告诉我哪些约束可以放宽。"
            )
        else:
            notes = (
                f"{product_label} 暂时无法完成联网搜索。"
                "这轮我先返回空结果，建议你稍后重试，或先告诉我哪些约束可以放宽。"
            )
        return ProductSearchOutput(
            products=[],
            search_meta=SearchMeta(
                retry_count=retry_count,
                result_status="failed",
                search_expanded=False,
                expansion_notes=error_message,
            ),
            notes=notes,
            suggested_followup="可以稍后重试，或先调整预算、场景和硬约束后再搜。",
        )

    def _build_failed_category_research_output(
        self,
        *,
        action_payload: dict[str, Any],
        reason: str,
        error_message: str,
    ) -> CategoryResearchOutput:
        category = action_payload.get("category")
        product_type = action_payload.get("product_type")
        category_name = category if isinstance(category, str) and category.strip() else "未知品类"
        product_type_name = (
            product_type
            if isinstance(product_type, str) and product_type.strip()
            else "未知产品类型"
        )
        if reason == "parse_failure":
            notes = (
                f"{category_name}/{product_type_name} 的研究结果结构化结果解析失败。"
                "这轮我先保留空结果，并建议稍后重试。"
            )
        else:
            notes = (
                f"{category_name}/{product_type_name} 暂时无法完成品类调研。"
                "这轮我先保留空结果，并建议稍后重试。"
            )
        return CategoryResearchOutput.model_validate(
            {
                "category": category_name,
                "category_knowledge": {
                    "data_sources": [],
                    "product_type_overview": [],
                    "shared_concepts": [],
                    "brand_landscape": [],
                },
                "product_type_name": product_type_name,
                "product_type_knowledge": {
                    "subtypes": {},
                    "decision_dimensions": [],
                    "tradeoffs": [],
                    "price_tiers": [],
                    "scenario_mapping": [],
                    "common_misconceptions": [],
                },
                "notes": notes,
            }
        )

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
        self._update_error_state_from_search_meta(session, result.search_meta, result.notes)

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
        self._append_error_event(
            session,
            "dispatch_category_research",
            {
                "category": result.category,
                "product_type": result.product_type_name,
            },
        )

    def _handle_failed_category_research_result(
        self,
        session: SessionState,
        result: CategoryResearchOutput,
    ) -> None:
        session["pending_research_result"] = {
            "type": "category_research",
            "result": result.model_dump(mode="json"),
        }
        self._append_error_event(
            session,
            "category_research_failed",
            {
                "category": result.category,
                "product_type": result.product_type_name,
                "notes": result.notes,
            },
        )

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
        normalized_demographics = self._normalize_demographics(demographics)

        existing_profile = self._store.load_global_profile() or {}
        existing_demographics = existing_profile.get("demographics")
        merged_demographics = (
            dict(existing_demographics)
            if isinstance(existing_demographics, dict)
            else {}
        )
        merged_demographics.update(normalized_demographics)

        self._store.save_global_profile({"demographics": merged_demographics})

    def _normalize_demographics(self, demographics: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        missing_fields: list[str] = []
        invalid_fields: list[str] = []

        for field in REQUIRED_DEMOGRAPHICS_FIELDS:
            value = demographics.get(field)
            if value is None:
                missing_fields.append(field)
                continue
            if not isinstance(value, str) or not value.strip():
                invalid_fields.append(field)
                continue
            normalized[field] = value.strip()

        if missing_fields:
            missing = ", ".join(missing_fields)
            raise ValueError(f"onboard_user demographics missing required fields: {missing}.")
        if invalid_fields:
            invalid = ", ".join(invalid_fields)
            raise ValueError(
                f"onboard_user demographics fields must be non-empty strings: {invalid}."
            )

        return normalized

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
        self._append_validation_warnings(session, [error_message])
        self._store.save_session(session)

        return RouteResult(
            user_message=user_message,
            wait_for_user_input=True,
            should_continue=False,
            session=session,
            action_metrics={"result_type": "error", "error": error_message},
        )

    def _append_validation_warnings(self, session: SessionState, warnings: list[str]) -> None:
        if not warnings:
            return

        error_state = self._ensure_error_state(session)
        validation_warnings = error_state["validation_warnings"]
        validation_warnings.extend(warnings)

    def _update_error_state_from_search_meta(
        self,
        session: SessionState,
        search_meta: SearchMeta,
        notes: str,
    ) -> None:
        error_state = self._ensure_error_state(session)
        error_state["search_retries"] = search_meta.retry_count

        event_type = {
            "insufficient_results": "insufficient_results",
            "partial_results": "partial_search_result",
            "failed": "search_failed",
        }.get(search_meta.result_status)
        if event_type is None:
            return

        self._append_error_event(
            session,
            event_type,
            {
                "retry_count": search_meta.retry_count,
                "search_expanded": search_meta.search_expanded,
                "expansion_notes": search_meta.expansion_notes,
                "notes": notes,
            },
        )

    def _append_error_event(
        self,
        session: SessionState,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        error_state = self._ensure_error_state(session)
        events = error_state["events"]
        events.append(
            {
                "type": event_type,
                "details": details or {},
            }
        )

    def _ensure_error_state(self, session: SessionState) -> dict[str, Any]:
        error_state = session.get("error_state")
        if not isinstance(error_state, dict):
            error_state = {}

        if not isinstance(error_state.get("constraint_conflicts"), list):
            error_state["constraint_conflicts"] = []
        if not isinstance(error_state.get("validation_warnings"), list):
            error_state["validation_warnings"] = []
        if not isinstance(error_state.get("events"), list):
            error_state["events"] = []

        search_retries = error_state.get("search_retries")
        if not isinstance(search_retries, int):
            error_state["search_retries"] = 0

        consecutive_negative_feedback = error_state.get("consecutive_negative_feedback")
        if not isinstance(consecutive_negative_feedback, int):
            error_state["consecutive_negative_feedback"] = 0

        session["error_state"] = error_state
        return error_state

    def _get_user_message(self, decision: Any) -> str:
        user_message = getattr(decision, "user_message", None)
        if isinstance(user_message, str) and user_message.strip():
            return user_message
        return "系统暂时无法处理该请求，请补充信息后重试。"
