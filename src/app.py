"""Application-layer outer loop for Phase 1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol

from src.agents.main_agent import create_main_agent
from src.agents.research_agent import execute_research
from src.models.decision import DecisionOutput
from src.router.action_router import ActionRouter, RouteResult
from src.store.document_store import DocumentStore

SessionState = dict[str, Any]
ContextBuilder = Callable[[SessionState], str]


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


def generate_session_id(now: datetime | None = None) -> str:
    """Generate a session id in the documented format."""

    current = now or datetime.now()
    return current.strftime("%Y-%m-%d-%H%M%S")


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


class ShoppingApplication:
    """Phase 1 application loop without CLI concerns."""

    def __init__(
        self,
        *,
        store: DocumentStore | None = None,
        main_agent: MainAgentProtocol | None = None,
        action_router: ActionRouter | None = None,
        context_builder: ContextBuilder = build_minimal_context,
    ) -> None:
        self.store = store or DocumentStore()
        self.main_agent = main_agent or create_main_agent()
        self.action_router = action_router or ActionRouter(
            store=self.store,
            research_executor=execute_research,
        )
        self.context_builder = context_builder

    def load_or_create_active_session(self) -> SessionState:
        """Load the current session or create a new minimal one."""

        session = self.store.load_session()
        if session is not None:
            return session

        created = {
            "session_id": generate_session_id(),
            "decision_progress": {"recommendation_round": "未开始"},
        }
        self.store.save_session(created)
        return self.store.load_session() or created

    def run_recovery_check_if_needed(self, session: SessionState) -> bool:
        """Run startup-only recovery check for pending profile updates."""

        if "pending_profile_updates" not in session:
            return False
        return self.store.apply_pending_profile_updates(session)

    async def run_turn(self, user_input: str | None = None) -> AppTurnResult:
        """Execute one outer-loop turn."""

        session = self.load_or_create_active_session()
        self.run_recovery_check_if_needed(session)

        had_pending_research_result = "pending_research_result" in session
        context = self.context_builder(session)
        decision = await self.main_agent.run(context, user_input or "")
        route_result = await self.action_router.route(decision, session)
        final_session = self._run_post_checks(
            route_result=route_result,
            had_pending_research_result=had_pending_research_result,
        )

        return AppTurnResult(
            user_message=route_result.user_message,
            wait_for_user_input=route_result.wait_for_user_input,
            should_continue=route_result.should_continue,
            session=final_session,
            decision=decision,
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
