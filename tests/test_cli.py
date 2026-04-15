from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.cli import run_cli


@dataclass
class FakeTurnResult:
    user_message: str
    should_continue: bool = False
    user_message_delivered: bool = False


@dataclass
class FakeApp:
    recovery_called: bool = False
    run_turn_calls: list[str | None] | None = None
    initialized: bool = False
    emitters: list[object] | None = None

    def __post_init__(self) -> None:
        self.run_turn_calls = []
        self.emitters = []

    def load_or_create_active_session(self) -> dict[str, str]:
        return {"session_id": "2026-04-14-100000"}

    def run_recovery_check_if_needed(self, session: dict[str, str]) -> bool:
        self.recovery_called = True
        return False

    async def initialize_session(self) -> dict[str, str]:
        self.initialized = True
        session = self.load_or_create_active_session()
        self.run_recovery_check_if_needed(session)
        return session

    async def run_turn(self, user_input: str | None, emit_user_message=None) -> FakeTurnResult:
        assert self.run_turn_calls is not None
        assert self.emitters is not None
        self.run_turn_calls.append(user_input)
        self.emitters.append(emit_user_message)
        return FakeTurnResult(user_message="测试回复", should_continue=False)


@pytest.mark.asyncio
async def test_cli_quit_preserves_session(monkeypatch, capsys) -> None:
    app = FakeApp()
    inputs = iter(["/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    await run_cli(app)

    output = capsys.readouterr().out
    assert "已退出，当前 session 已保留。" in output
    assert app.recovery_called is True
    assert app.initialized is True
    assert app.run_turn_calls == []


@pytest.mark.asyncio
async def test_cli_runs_single_turn(monkeypatch, capsys) -> None:
    app = FakeApp()
    inputs = iter(["想买一件冲锋衣", "/end"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    await run_cli(app)

    output = capsys.readouterr().out
    assert "Shopping Agent CLI 已启动" in output
    assert "测试回复" in output
    assert app.initialized is True
    assert app.run_turn_calls == ["想买一件冲锋衣"]
    assert app.emitters == [print]


@pytest.mark.asyncio
async def test_cli_does_not_double_print_pre_delivered_message(monkeypatch, capsys) -> None:
    app = FakeApp()

    async def run_turn(user_input: str | None, emit_user_message=None) -> FakeTurnResult:
        if emit_user_message is not None:
            emit_user_message("搜索中...")
        return FakeTurnResult(
            user_message="搜索中...",
            should_continue=False,
            user_message_delivered=True,
        )

    app.run_turn = run_turn  # type: ignore[method-assign]
    inputs = iter(["想买一件冲锋衣", "/end"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    await run_cli(app)

    output = capsys.readouterr().out
    assert output.count("搜索中...") == 1
