from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.agents import main_agent as main_agent_module
from src.agents.main_agent import MainAgentRunner, create_main_agent
from src.models.decision import DecisionOutput


class DummyClient:
    async def get_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_main_agent_runner_uses_decision_output_response_format(monkeypatch) -> None:
    runner = create_main_agent(client=DummyClient())
    captured: dict[str, Any] = {}

    async def fake_run(messages: str, **kwargs: Any) -> Any:
        captured["messages"] = messages
        captured["options"] = kwargs["options"]
        return SimpleNamespace(
            value=DecisionOutput.model_validate(
                {
                    "user_message": "继续补充预算。",
                    "internal_reasoning": {
                        "state_summary": "预算未知。",
                        "stage_assessment": "需求挖掘",
                    },
                    "next_action": "ask_user",
                }
            )
        )

    monkeypatch.setattr(runner.agent, "run", fake_run)
    result = await runner.run("## 当前会话状态", "我想买冲锋衣")

    assert result.next_action == "ask_user"
    assert captured["options"]["response_format"] is DecisionOutput
    assert "## 用户消息" in captured["messages"]


def test_create_main_agent_has_no_tools() -> None:
    runner = create_main_agent(client=DummyClient())

    assert isinstance(runner, MainAgentRunner)
    assert runner.agent.default_options["tools"] == []


def test_create_main_agent_uses_runtime_prompt_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeAgent:
        def __init__(self, *, client: Any, name: str, instructions: str, tools: list[Any]) -> None:
            captured["client"] = client
            captured["name"] = name
            captured["instructions"] = instructions
            self.default_options = {"tools": tools}

    monkeypatch.setattr(main_agent_module, "Agent", FakeAgent)
    monkeypatch.setattr(
        main_agent_module,
        "load_main_agent_instructions",
        lambda: "runtime prompt marker",
    )

    runner = main_agent_module.create_main_agent(client=DummyClient())

    assert isinstance(runner, MainAgentRunner)
    assert captured["name"] == "main_agent"
    assert captured["instructions"] == "runtime prompt marker"
