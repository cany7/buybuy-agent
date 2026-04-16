"""Application-layer outer loop for Phase 1."""

from __future__ import annotations

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
        had_pending_research_result = "pending_research_result" in session
        context = self.context_builder(session)
        decision = await self.main_agent.run(context, user_input or "")
        route_result = await self.action_router.route(
            decision,
            session,
            emit_user_message=emit_user_message,
        )
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
