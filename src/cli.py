"""CLI entrypoint for the shopping agent."""

from __future__ import annotations

import asyncio
from typing import Protocol

from src.app import ShoppingApplication

EXIT_COMMANDS = {"/quit", "/end"}


class CliAppProtocol(Protocol):
    """Protocol for the minimal application surface used by the CLI."""

    def load_or_create_active_session(self) -> dict[str, str]:
        """Load or create the active session."""

    def run_recovery_check_if_needed(self, session: dict[str, str]) -> bool:
        """Run startup recovery logic."""

    async def initialize_session(self) -> dict[str, str]:
        """Initialize startup-only session state."""

    async def run_turn(  # type: ignore[no-untyped-def]
        self,
        user_input: str | None,
        *,
        emit_user_message=None,
    ):
        """Run one application turn."""


async def run_cli(app: CliAppProtocol | None = None) -> None:
    """Run the Phase 1 CLI loop."""

    application = app or ShoppingApplication()
    await application.initialize_session()

    print("Shopping Agent CLI 已启动。输入购物需求开始对话，输入 /quit 或 /end 退出。")

    while True:
        try:
            user_input = input("> ").strip()
        except EOFError:
            print("\n输入结束，已退出。")
            return

        if user_input in EXIT_COMMANDS:
            print("已退出，当前 session 已保留。")
            return

        if not user_input:
            print("请输入你的购物需求或问题。")
            continue

        turn_result = await application.run_turn(user_input, emit_user_message=print)
        if not getattr(turn_result, "user_message_delivered", False):
            print(turn_result.user_message)

        while turn_result.should_continue:
            turn_result = await application.run_turn(None, emit_user_message=print)
            if not getattr(turn_result, "user_message_delivered", False):
                print(turn_result.user_message)


def main() -> None:
    """Synchronous CLI entrypoint."""

    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        print("\n已中断，当前 session 已保留。")


if __name__ == "__main__":
    main()
