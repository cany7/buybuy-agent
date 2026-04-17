"""Application-layer outer loop for Phase 1."""

from __future__ import annotations

from copy import deepcopy
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from src.agents.main_agent import create_main_agent
from src.context.knowledge_provider import KnowledgeContextProvider
from src.context.profile_provider import ProfileContextProvider
from src.context.session_provider import SessionContextProvider
from src.agents.research_agent import execute_research
from src.models.decision import DecisionOutput
from src.router.action_router import ActionRouter, RouteResult
from src.store.document_store import DocumentStore
from src.utils.logger import SessionActivity, SessionLogger
from src.utils.session import generate_session_id

SessionState = dict[str, Any]
ContextBuilder = Callable[[SessionState], str]
MessageEmitter = Callable[[str], object]


class MainAgentProtocol(Protocol):
    """Protocol for the main agent runner."""

    async def run(self, context: str, user_message: str) -> DecisionOutput:
        """Run one reasoning turn."""


@dataclass(slots=True)
class AppTurnResult:
    """Result of one outer-loop turn."""

    user_message: str
    wait_for_user_input: bool
    should_continue: bool
    session: SessionState
    decision: DecisionOutput
    user_message_delivered: bool = False


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    """Thresholds for application-layer boundary protection."""

    max_session_turns: int = 30
    max_requirement_mining_turns: int = 8
    max_distinct_category_researches: int = 2
    recommended_product_search_limit: int = 6


def build_minimal_context(session: SessionState) -> str:
    """Fallback context builder until SessionContextProvider is implemented."""

    lines = ["## 当前会话状态", json.dumps(session, ensure_ascii=False, indent=2)]
    pending = session.get("pending_research_result")
    if pending is not None:
        lines.extend(
            [
                "",
                "## 研究结果（待消费）",
                json.dumps(pending, ensure_ascii=False, indent=2),
            ]
        )
    return "\n".join(lines)


def build_phase_one_context(
    session: SessionState,
    *,
    session_provider: SessionContextProvider,
    profile_provider: ProfileContextProvider,
    knowledge_provider: KnowledgeContextProvider,
) -> str:
    """Combine session and Phase 1 knowledge context blocks."""

    blocks = [session_provider.build_context(session)]
    profile_context = profile_provider.build_context(session)
    if profile_context:
        blocks.extend(["", profile_context])
    knowledge_context = knowledge_provider.build_context(session)
    if knowledge_context:
        blocks.extend(["", knowledge_context])
    return "\n".join(blocks)


class ShoppingApplication:
    """Phase 1 application loop without CLI concerns."""

    def __init__(
        self,
        *,
        store: DocumentStore | None = None,
        main_agent: MainAgentProtocol | None = None,
        action_router: ActionRouter | None = None,
        context_builder: ContextBuilder | None = None,
        session_logger: SessionLogger | None = None,
        boundary_config: BoundaryConfig | None = None,
    ) -> None:
        self.store = store or DocumentStore()
        self.main_agent = main_agent or create_main_agent()
        self.action_router = action_router or ActionRouter(
            store=self.store,
            research_executor=execute_research,
        )
        self.session_provider = SessionContextProvider(store=self.store)
        self.profile_provider = ProfileContextProvider(store=self.store)
        self.knowledge_provider = KnowledgeContextProvider(store=self.store)
        self.session_logger = session_logger or SessionLogger(base_dir=self.store.base_dir)
        self.boundary_config = boundary_config or BoundaryConfig()
        self.context_builder = context_builder or (
            lambda session: build_phase_one_context(
                session,
                session_provider=self.session_provider,
                profile_provider=self.profile_provider,
                knowledge_provider=self.knowledge_provider,
            )
        )

    def load_or_create_active_session(self) -> SessionState:
        """Load the current session or create a new minimal one."""

        return self.session_provider.load_or_create_session()

    def create_new_active_session(self) -> SessionState:
        """Create a new active session while preserving the current one as history."""

        current_session = self.store.load_session()
        new_session = self._build_new_session(existing_session=current_session)
        self.store.replace_active_session(
            new_session,
            preserve_current=current_session is not None,
        )
        loaded = self.store.load_session()
        if loaded is None:
            raise ValueError("Failed to create a new active session.")
        return loaded

    def run_recovery_check_if_needed(self, session: SessionState) -> bool:
        """Run startup-only recovery check for pending profile updates."""

        if "pending_profile_updates" not in session:
            return False
        return self.store.apply_pending_profile_updates(session)

    async def initialize_session(self, *, start_new_session: bool = False) -> SessionState:
        """Load/create the active session and run startup-only recovery checks."""

        session = self.load_or_create_active_session()
        self.run_recovery_check_if_needed(session)
        if start_new_session:
            return self.create_new_active_session()
        return self.load_or_create_active_session()

    async def run_turn(
        self,
        user_input: str | None = None,
        *,
        emit_user_message: MessageEmitter | None = None,
    ) -> AppTurnResult:
        """Execute one outer-loop turn."""

        session = self.load_or_create_active_session()
        activity = self.session_logger.get_session_activity(session.get("session_id"))
        preempted = self._maybe_preempt_for_max_turns(
            session=session,
            user_input=user_input,
            activity=activity,
        )
        if preempted is not None:
            return preempted

        had_pending_research_result = "pending_research_result" in session
        context = self._build_context_with_boundaries(session, activity)
        try:
            decision_or_fallback = await self._run_main_agent_with_retry(
                session=session,
                context=context,
                user_input=user_input,
            )
            if isinstance(decision_or_fallback, AppTurnResult):
                return decision_or_fallback
            decision = decision_or_fallback
            route_result = self._maybe_block_category_research(
                decision=decision,
                session=session,
            )
            if route_result is None:
                route_result = await self.action_router.route(
                    decision,
                    session,
                    emit_user_message=emit_user_message,
                )
                final_session = self._run_post_checks(
                    route_result=route_result,
                    had_pending_research_result=had_pending_research_result,
                )
            else:
                final_session = route_result.session
            final_session, route_result = self._apply_post_turn_boundaries(
                session_after=final_session,
                route_result=route_result,
                activity=activity,
            )
        except Exception as error:
            self.session_logger.log_turn_exception(
                session=session,
                context=context,
                user_input=user_input,
                error=error,
            )
            raise

        self.session_logger.log_turn(
            session_before=session,
            session_after=final_session,
            context=context,
            user_input=user_input,
            decision=decision,
            route_result=route_result,
        )

        return AppTurnResult(
            user_message=route_result.user_message,
            wait_for_user_input=route_result.wait_for_user_input,
            should_continue=route_result.should_continue,
            session=final_session,
            decision=decision,
            user_message_delivered=route_result.user_message_delivered,
        )

    def _run_post_checks(
        self,
        *,
        route_result: RouteResult,
        had_pending_research_result: bool,
    ) -> SessionState:
        session = dict(route_result.session)
        if had_pending_research_result and not route_result.replaced_pending_research_result:
            session.pop("pending_research_result", None)
            self.store.save_session(session)
        return session

    def _build_new_session(self, existing_session: SessionState | None = None) -> SessionState:
        existing_session_id = existing_session.get("session_id") if existing_session else None
        return {
            "session_id": self._generate_unique_session_id(existing_session_id),
            "decision_progress": {"recommendation_round": "未开始"},
        }

    def _build_context_with_boundaries(
        self,
        session: SessionState,
        activity: SessionActivity,
    ) -> str:
        context = self.context_builder(session)
        sections = [context]
        boundary_notes = self._build_boundary_notes(activity)
        if boundary_notes:
            sections.extend(
                [
                    "## [系统标注] 边界保护提示",
                    "\n".join(boundary_notes),
                ]
            )
        negative_feedback_note = self._build_negative_feedback_note(session)
        if negative_feedback_note:
            sections.extend(
                [
                    "## [系统标注] 推荐反馈提示",
                    negative_feedback_note,
                ]
            )
        return "\n\n".join(sections)

    async def _run_main_agent_with_retry(
        self,
        *,
        session: SessionState,
        context: str,
        user_input: str | None,
    ) -> DecisionOutput | AppTurnResult:
        last_error: Exception | None = None
        failure_kind = "main_agent_api_failed"

        for attempt in range(2):
            try:
                return await self.main_agent.run(context, user_input or "")
            except ValueError as error:
                last_error = error
                failure_kind = "decision_parse_failed"
            except Exception as error:  # pragma: no cover - exercised in app tests
                last_error = error
                failure_kind = "main_agent_api_failed"

            if attempt == 0:
                continue

        return self._build_main_agent_failure_result(
            session=session,
            context=context,
            user_input=user_input,
            failure_kind=failure_kind,
            error=last_error or RuntimeError("Unknown main agent failure."),
        )

    def _build_boundary_notes(self, activity: SessionActivity) -> list[str]:
        notes: list[str] = []
        if (
            activity.requirement_mining_turn_count
            >= self.boundary_config.max_requirement_mining_turns
        ):
            notes.append(
                "需求挖掘阶段已达到 "
                f"{activity.requirement_mining_turn_count} 轮。当前轮必须推进到下一步，"
                "或明确说明为什么仍然无法推进。"
            )
        if activity.product_search_count >= self.boundary_config.recommended_product_search_limit:
            notes.append(
                "本 session 已执行 "
                f"{activity.product_search_count} 次产品搜索。请优先复用已有 candidate_products；"
                "如必须再次搜索，请在 internal_reasoning 中说明新增搜索的必要性与限制。"
            )
        return notes

    def _build_negative_feedback_note(self, session: SessionState) -> str:
        error_state = session.get("error_state")
        if not isinstance(error_state, dict):
            return ""

        count = error_state.get("consecutive_negative_feedback")
        if not isinstance(count, int) or count < 2:
            return ""

        return (
            f"连续负面反馈已达到 {count} 轮。"
            "请在 internal_reasoning 中反思当前推荐策略，并主动请用户说明不满意的具体原因，"
            "重新锚定核心需求。"
        )

    def _build_main_agent_failure_result(
        self,
        *,
        session: SessionState,
        context: str,
        user_input: str | None,
        failure_kind: str,
        error: Exception,
    ) -> AppTurnResult:
        failed_session = deepcopy(session)
        if failure_kind == "decision_parse_failed":
            user_message = (
                "这轮我暂时没能稳定理解你的请求。"
                "你可以直接告诉我这次最关键的 1-2 个约束，我会重新整理。"
            )
            state_summary = "主 Agent 的结构化决策解析连续失败，已切换到保守降级回复。"
        else:
            user_message = (
                "服务暂时不可用。"
                "你可以稍后再试，或先告诉我当前最关键的需求，我恢复后继续帮你推进。"
            )
            state_summary = "主 Agent 调用连续失败，已切换到服务不可用降级回复。"

        self._append_system_error_event(
            failed_session,
            event_type=failure_kind,
            details={
                "message": str(error),
                "attempts": 2,
            },
        )
        self.store.save_session(failed_session)

        decision = DecisionOutput.model_validate(
            {
                "user_message": user_message,
                "internal_reasoning": {
                    "state_summary": state_summary,
                    "stage_assessment": "错误降级",
                },
                "next_action": "ask_user",
            }
        )
        route_result = RouteResult(
            user_message=user_message,
            wait_for_user_input=True,
            should_continue=False,
            session=failed_session,
            action_metrics={
                "result_type": failure_kind,
                "error": str(error),
                "attempts": 2,
            },
        )
        self.session_logger.log_turn(
            session_before=session,
            session_after=failed_session,
            context=context,
            user_input=user_input,
            decision=decision,
            route_result=route_result,
        )
        return AppTurnResult(
            user_message=user_message,
            wait_for_user_input=True,
            should_continue=False,
            session=failed_session,
            decision=decision,
            user_message_delivered=False,
        )

    def _maybe_preempt_for_max_turns(
        self,
        *,
        session: SessionState,
        user_input: str | None,
        activity: SessionActivity,
    ) -> AppTurnResult | None:
        if activity.turn_count < self.boundary_config.max_session_turns:
            return None

        blocked_session = deepcopy(session)
        message = self._build_max_turns_message(activity.turn_count)
        self._append_boundary_event(
            blocked_session,
            boundary="max_session_turns",
            message=message,
            limit=self.boundary_config.max_session_turns,
            observed=activity.turn_count,
            event_type="boundary_triggered",
        )
        self.store.save_session(blocked_session)

        decision = self._build_boundary_decision(message)
        route_result = RouteResult(
            user_message=message,
            wait_for_user_input=True,
            should_continue=False,
            session=blocked_session,
            action_metrics={
                "result_type": "boundary_blocked",
                "boundary": "max_session_turns",
                "completed_turns": activity.turn_count,
            },
        )
        context = self._build_context_with_boundaries(session, activity)
        self.session_logger.log_turn(
            session_before=session,
            session_after=blocked_session,
            context=context,
            user_input=user_input,
            decision=decision,
            route_result=route_result,
        )
        return AppTurnResult(
            user_message=message,
            wait_for_user_input=True,
            should_continue=False,
            session=blocked_session,
            decision=decision,
            user_message_delivered=False,
        )

    def _maybe_block_category_research(
        self,
        *,
        decision: DecisionOutput,
        session: SessionState,
    ) -> RouteResult | None:
        if decision.next_action != "dispatch_category_research":
            return None

        action_payload = decision.action_payload
        if not isinstance(action_payload, dict):
            return None

        requested_category = action_payload.get("category")
        if not isinstance(requested_category, str) or not requested_category.strip():
            return None

        normalized_category = requested_category.strip()
        researched_categories = self._extract_researched_categories(session)
        if normalized_category in researched_categories:
            return None
        if len(researched_categories) < self.boundary_config.max_distinct_category_researches:
            return None

        blocked_session = deepcopy(session)
        message = (
            "本 session 已调研 "
            f"{len(researched_categories)} 个不同品类，已达到建议上限。"
            f"请优先复用已有 knowledge；如确实需要继续调研 {normalized_category}，"
            "请先向用户说明必要性。"
        )
        self._append_boundary_event(
            blocked_session,
            boundary="category_research_limit",
            message=message,
            limit=self.boundary_config.max_distinct_category_researches,
            observed=len(researched_categories),
            event_type="boundary_blocked",
            requested_category=normalized_category,
        )
        self.store.save_session(blocked_session)
        return RouteResult(
            user_message=message,
            wait_for_user_input=True,
            should_continue=False,
            session=blocked_session,
            action_metrics={
                "result_type": "boundary_blocked",
                "boundary": "category_research_limit",
                "distinct_categories": len(researched_categories),
                "requested_category": normalized_category,
            },
        )

    def _apply_post_turn_boundaries(
        self,
        *,
        session_after: SessionState,
        route_result: RouteResult,
        activity: SessionActivity,
    ) -> tuple[SessionState, RouteResult]:
        completed_turns = activity.turn_count + 1
        if completed_turns < self.boundary_config.max_session_turns:
            return session_after, route_result

        bounded_session = deepcopy(session_after)
        message = self._build_max_turns_message(completed_turns)
        self._append_boundary_event(
            bounded_session,
            boundary="max_session_turns",
            message=message,
            limit=self.boundary_config.max_session_turns,
            observed=completed_turns,
            event_type="boundary_triggered",
        )
        self.store.save_session(bounded_session)

        action_metrics = dict(route_result.action_metrics or {})
        action_metrics.update(
            {
                "boundary": "max_session_turns",
                "completed_turns": completed_turns,
            }
        )
        return bounded_session, RouteResult(
            user_message=message,
            wait_for_user_input=True,
            should_continue=False,
            session=bounded_session,
            replaced_pending_research_result=route_result.replaced_pending_research_result,
            user_message_delivered=False,
            action_metrics=action_metrics,
        )

    def _build_max_turns_message(self, completed_turns: int) -> str:
        return (
            "本 session 已达到 "
            f"{completed_turns} 轮。请先保存当前结论并结束本次对话；"
            "当前 session 会保留，之后仍可继续恢复。"
        )

    def _build_boundary_decision(self, user_message: str) -> DecisionOutput:
        return DecisionOutput.model_validate(
            {
                "user_message": user_message,
                "internal_reasoning": {
                    "state_summary": "系统触发边界保护，暂停继续推进。",
                    "stage_assessment": "边界保护",
                },
                "next_action": "ask_user",
            }
        )

    def _append_boundary_event(
        self,
        session: SessionState,
        *,
        boundary: str,
        message: str,
        limit: int,
        observed: int,
        event_type: str,
        requested_category: str | None = None,
    ) -> None:
        error_state = session.get("error_state")
        if not isinstance(error_state, dict):
            error_state = {}

        events = error_state.get("events")
        if not isinstance(events, list):
            events = []

        details: dict[str, Any] = {
            "boundary": boundary,
            "message": message,
            "limit": limit,
            "observed": observed,
        }
        if requested_category is not None:
            details["requested_category"] = requested_category

        events.append({"type": event_type, "details": details})
        error_state["events"] = events

        if not isinstance(error_state.get("constraint_conflicts"), list):
            error_state["constraint_conflicts"] = []
        if not isinstance(error_state.get("validation_warnings"), list):
            error_state["validation_warnings"] = []
        if not isinstance(error_state.get("search_retries"), int):
            error_state["search_retries"] = 0
        if not isinstance(error_state.get("consecutive_negative_feedback"), int):
            error_state["consecutive_negative_feedback"] = 0

        session["error_state"] = error_state

    def _append_system_error_event(
        self,
        session: SessionState,
        *,
        event_type: str,
        details: dict[str, Any],
    ) -> None:
        error_state = session.get("error_state")
        if not isinstance(error_state, dict):
            error_state = {}

        events = error_state.get("events")
        if not isinstance(events, list):
            events = []
        events.append(
            {
                "type": event_type,
                "details": details,
            }
        )
        error_state["events"] = events

        if not isinstance(error_state.get("constraint_conflicts"), list):
            error_state["constraint_conflicts"] = []
        if not isinstance(error_state.get("validation_warnings"), list):
            error_state["validation_warnings"] = []
        if not isinstance(error_state.get("search_retries"), int):
            error_state["search_retries"] = 0
        if not isinstance(error_state.get("consecutive_negative_feedback"), int):
            error_state["consecutive_negative_feedback"] = 0

        session["error_state"] = error_state

    def _extract_researched_categories(self, session: SessionState) -> set[str]:
        error_state = session.get("error_state")
        if not isinstance(error_state, dict):
            return set()

        events = error_state.get("events")
        if not isinstance(events, list):
            return set()

        categories: set[str] = set()
        for event in events:
            if not isinstance(event, dict) or event.get("type") != "dispatch_category_research":
                continue
            details = event.get("details")
            if not isinstance(details, dict):
                continue
            category = details.get("category")
            if not isinstance(category, str):
                continue
            normalized = category.strip()
            if normalized:
                categories.add(normalized)
        return categories

    def _generate_unique_session_id(self, existing_session_id: object | None) -> str:
        for offset in range(60):
            candidate = generate_session_id(datetime.now() + timedelta(seconds=offset))
            if candidate == existing_session_id:
                continue
            history_path = self.store.sessions_dir / f"{candidate}.json"
            if history_path.exists():
                continue
            return candidate
        raise ValueError("Failed to generate a unique session_id for the new active session.")
