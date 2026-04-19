"""Main agent definition for Phase 1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

from src.agents.prompts import load_main_agent_instructions
from src.models.decision import DecisionOutput
from src.utils.runtime_config import resolve_openai_compatible_client_config


def build_main_agent_client(model: str | None = None) -> OpenAIChatClient:
    """Build the chat client used by the main agent."""

    config = resolve_openai_compatible_client_config(
        model_env_var="MAIN_AGENT_MODEL",
        default_model="gpt-4o",
        agent_base_url_env="MAIN_AGENT_BASE_URL",
        agent_api_key_env="MAIN_AGENT_API_KEY",
    )
    return OpenAIChatClient(
        model=model or config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        env_file_path=config.env_file_path,
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
