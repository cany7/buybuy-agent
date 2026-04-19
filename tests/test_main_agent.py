from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.agents import main_agent as main_agent_module
from src.agents.main_agent import MainAgentRunner, build_main_agent_client, create_main_agent
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


def test_build_main_agent_client_uses_shared_default_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(main_agent_module, "OpenAIChatClient", FakeClient)
    monkeypatch.setenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_API_KEY", "shared-key")
    monkeypatch.setenv("MAIN_AGENT_MODEL", "qwen/qwen3-235b-a22b")
    monkeypatch.delenv("MAIN_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("MAIN_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("SHOPPING_MAIN_AGENT_MODEL", "legacy-model")

    build_main_agent_client()

    assert captured["model"] == "qwen/qwen3-235b-a22b"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["api_key"] == "shared-key"
    assert captured["env_file_path"] is None or captured["env_file_path"].endswith(".env")


def test_build_main_agent_client_uses_agent_specific_override(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(main_agent_module, "OpenAIChatClient", FakeClient)
    monkeypatch.setenv("LLM_BASE_URL", "https://shared.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "shared-key")
    monkeypatch.setenv("MAIN_AGENT_MODEL", "gpt-4.1")
    monkeypatch.setenv("MAIN_AGENT_BASE_URL", "https://main.example/v1")
    monkeypatch.setenv("MAIN_AGENT_API_KEY", "main-key")

    build_main_agent_client()

    assert captured["model"] == "gpt-4.1"
    assert captured["base_url"] == "https://main.example/v1"
    assert captured["api_key"] == "main-key"


def test_build_main_agent_client_rejects_partial_agent_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://shared.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "shared-key")
    monkeypatch.setenv("MAIN_AGENT_BASE_URL", "https://main.example/v1")
    monkeypatch.delenv("MAIN_AGENT_API_KEY", raising=False)

    with pytest.raises(ValueError, match="MAIN_AGENT_BASE_URL and MAIN_AGENT_API_KEY must be set together"):
        build_main_agent_client()
