"""Research agent definition and execution helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import TypeVar

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv
from pydantic import BaseModel

from src.agents.prompts import load_category_research_template, load_product_search_template
from src.agents.tools import search_web
from src.models.research import CategoryResearchOutput, ProductSearchOutput

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)
ResearchOutput = CategoryResearchOutput | ProductSearchOutput

DEFAULT_RESEARCH_BRIEF = "请根据任务目标，自主选择合适的搜索语言和关键词策略。"


def _default_env_path() -> str:
    return str(Path(__file__).resolve().parents[2] / ".env")


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def build_research_agent_client(model: str | None = None) -> OpenAIChatClient:
    """Build the chat client used by the research agent."""

    load_dotenv(_default_env_path(), override=False)
    return OpenAIChatClient(
        model=model or os.getenv("SHOPPING_RESEARCH_AGENT_MODEL", "gpt-4o-mini"),
        env_file_path=_default_env_path(),
    )


def _format_optional_value(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, list):
        return "、".join(str(item) for item in value) if value else default
    if value == "":
        return default
    return str(value)


def validate_product_search_payload(action_payload: dict[str, Any]) -> None:
    """Validate the minimal payload shape required for dispatch_product_search."""

    if not isinstance(action_payload, dict):
        raise ValueError("action_payload must be a dict.")

    product_type = action_payload.get("product_type")
    search_goal = action_payload.get("search_goal")
    constraints = action_payload.get("constraints")

    if not isinstance(product_type, str) or not product_type.strip():
        raise ValueError("action_payload.product_type is required.")
    if not isinstance(search_goal, str) or not search_goal.strip():
        raise ValueError("action_payload.search_goal is required.")
    if not isinstance(constraints, dict):
        raise ValueError("action_payload.constraints must be an object.")

    key_requirements = constraints.get("key_requirements")
    exclusions = constraints.get("exclusions")
    budget = constraints.get("budget")

    if not isinstance(key_requirements, list):
        raise ValueError("constraints.key_requirements must be a list.")
    if not isinstance(exclusions, list):
        raise ValueError("constraints.exclusions must be a list.")
    if budget is not None and budget != "unspecified" and not isinstance(budget, str):
        raise ValueError("constraints.budget must be null, 'unspecified', or a string.")


def validate_category_research_payload(action_payload: dict[str, Any]) -> None:
    """Validate the minimal payload shape required for dispatch_category_research."""

    if not isinstance(action_payload, dict):
        raise ValueError("action_payload must be a dict.")

    category = action_payload.get("category")
    product_type = action_payload.get("product_type")
    user_context = action_payload.get("user_context")

    if not isinstance(category, str) or not category.strip():
        raise ValueError("action_payload.category is required.")
    if not isinstance(product_type, str) or not product_type.strip():
        raise ValueError("action_payload.product_type is required.")
    if not isinstance(user_context, str) or not user_context.strip():
        raise ValueError("action_payload.user_context is required.")


def build_product_search_instructions(action_payload: dict[str, Any]) -> str:
    """Render the product-search prompt template with payload fields."""

    constraints = action_payload["constraints"]
    research_brief = action_payload.get("research_brief", "")
    if not research_brief:
        research_brief = DEFAULT_RESEARCH_BRIEF

    return load_product_search_template().format(
        product_type=action_payload["product_type"],
        search_goal=action_payload["search_goal"],
        budget=_format_optional_value(constraints.get("budget"), default="null"),
        gender=_format_optional_value(constraints.get("gender"), default="未提供"),
        key_requirements=_format_optional_value(constraints.get("key_requirements"), default="无"),
        scenario=_format_optional_value(constraints.get("scenario"), default="未提供"),
        exclusions=_format_optional_value(constraints.get("exclusions"), default="无"),
        research_brief=research_brief,
    )


def build_category_research_instructions(action_payload: dict[str, Any]) -> str:
    """Render the category-research prompt template with payload fields."""

    research_brief = action_payload.get("research_brief", "")
    if not research_brief:
        research_brief = DEFAULT_RESEARCH_BRIEF

    return load_category_research_template().format(
        category=action_payload["category"],
        product_type=action_payload["product_type"],
        user_context=action_payload["user_context"],
        research_brief=research_brief,
    )


@dataclass(slots=True)
class ResearchAgentRunner:
    """Thin wrapper that fixes the research-agent output type."""

    agent: Agent

    async def run_structured(
        self,
        task_prompt: str,
        response_format: type[ResponseModelT],
    ) -> ResponseModelT:
        """Run one research task and parse the response as the requested output model."""

        response = await self.agent.run(
            task_prompt,
            options={"response_format": response_format},
        )
        value = response.value
        if value is None:
            raise ValueError("Research agent returned no structured output.")
        return value

    async def run(self, task_prompt: str) -> ProductSearchOutput:
        """Backward-compatible helper for product search tasks."""

        return await self.run_structured(task_prompt, ProductSearchOutput)


def create_research_agent(
    instructions: str,
    client: Any | None = None,
) -> ResearchAgentRunner:
    """Create a new research agent instance with isolated context."""

    agent = Agent(
        client=client or build_research_agent_client(),
        name="research_agent",
        instructions=instructions,
        tools=[search_web],
    )
    return ResearchAgentRunner(agent=agent)


async def execute_research(
    task_type: str,
    action_payload: dict[str, Any],
    *,
    client: Any | None = None,
) -> ResearchOutput:
    """Run a research task for product search or category research."""

    if task_type == "dispatch_product_search":
        validate_product_search_payload(action_payload)
        instructions = build_product_search_instructions(action_payload)
        task_prompt = (
            "请根据提供的约束执行产品搜索，并严格按 ProductSearchOutput 返回结构化结果。"
        )
        response_format: type[ResearchOutput] = ProductSearchOutput
    elif task_type == "dispatch_category_research":
        validate_category_research_payload(action_payload)
        instructions = build_category_research_instructions(action_payload)
        task_prompt = (
            "请根据提供的品类调研任务执行搜索，并严格按 CategoryResearchOutput 返回结构化结果。"
        )
        response_format = CategoryResearchOutput
    else:
        raise ValueError("Unsupported research task type.")

    runner = create_research_agent(instructions=instructions, client=client)
    return await runner.run_structured(task_prompt, response_format)
