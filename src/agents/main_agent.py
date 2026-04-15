"""Main agent definition for Phase 1."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv

from src.agents.prompts import load_main_agent_instructions
from src.models.decision import DecisionOutput


def _default_env_path() -> str:
    return str(Path(__file__).resolve().parents[2] / ".env")


def build_main_agent_client(model: str | None = None) -> OpenAIChatClient:
    """Build the chat client used by the main agent."""

    load_dotenv(_default_env_path(), override=False)
    return OpenAIChatClient(
        model=model or os.getenv("SHOPPING_MAIN_AGENT_MODEL", "gpt-4o"),
        env_file_path=_default_env_path(),
    )


@dataclass(slots=True)
class MainAgentRunner:
    """Thin wrapper that fixes the main-agent output type."""

    agent: Agent

    async def run(self, context: str, user_message: str) -> DecisionOutput:
        """Run one reasoning turn and parse the response as DecisionOutput."""

        combined_input = f"{context.strip()}\n\n## 用户消息\n{user_message.strip()}"
        response = await self.agent.run(
            combined_input,
            options={"response_format": DecisionOutput},
        )
        value = response.value
        if value is None:
            raise ValueError("Main agent returned no structured output.")
        return value


def create_main_agent(client: Any | None = None) -> MainAgentRunner:
    """Create the Phase 1 main agent with no tools."""

    agent = Agent(
        client=client or build_main_agent_client(),
        name="main_agent",
        instructions=load_main_agent_instructions(),
        tools=[],
    )
    return MainAgentRunner(agent=agent)
