"""Research agent definition and execution helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import TypeVar
from urllib.parse import urlparse

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
LOGGER = logging.getLogger(__name__)
MAX_REASONABLE_PRICE_AMOUNT = 1_000_000
VALID_SOURCE_CONSISTENCY = {"high", "medium", "low"}
VALIDATION_NOTE_PREFIX = "[系统校验警告]"


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


def _require_non_empty_string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required and must be a non-empty string.")


def _validate_string_list(value: Any, path: str, *, allow_empty: bool) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list.")
    if not allow_empty and not value:
        raise ValueError(f"{path} must not be empty.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{path} must contain non-empty strings.")


def validate_product_search_payload(action_payload: Any) -> None:
    """Validate the minimal payload shape required for dispatch_product_search."""

    if not isinstance(action_payload, dict):
        raise ValueError("action_payload must be a dict.")

    product_type = action_payload.get("product_type")
    search_goal = action_payload.get("search_goal")
    constraints = action_payload.get("constraints")

    _require_non_empty_string(product_type, "action_payload.product_type")
    _require_non_empty_string(search_goal, "action_payload.search_goal")
    if not isinstance(constraints, dict):
        raise ValueError("action_payload.constraints must be an object.")
    if not constraints:
        raise ValueError("action_payload.constraints must not be empty.")

    key_requirements = constraints.get("key_requirements")
    exclusions = constraints.get("exclusions")
    budget = constraints.get("budget")
    gender = constraints.get("gender")
    scenario = constraints.get("scenario")
    research_brief = action_payload.get("research_brief")

    _validate_string_list(key_requirements, "constraints.key_requirements", allow_empty=False)
    if exclusions is not None:
        _validate_string_list(exclusions, "constraints.exclusions", allow_empty=True)
    if budget is not None and budget != "unspecified" and not isinstance(budget, str):
        raise ValueError("constraints.budget must be null, 'unspecified', or a string.")
    if isinstance(budget, str) and budget != "unspecified" and not budget.strip():
        raise ValueError("constraints.budget must not be an empty string.")
    if gender is not None and not isinstance(gender, str):
        raise ValueError("constraints.gender must be a string when provided.")
    if scenario is not None and not isinstance(scenario, str):
        raise ValueError("constraints.scenario must be a string when provided.")
    if research_brief is not None and not isinstance(research_brief, str):
        raise ValueError("action_payload.research_brief must be a string when provided.")


def validate_category_research_payload(action_payload: Any) -> None:
    """Validate the minimal payload shape required for dispatch_category_research."""

    if not isinstance(action_payload, dict):
        raise ValueError("action_payload must be a dict.")

    category = action_payload.get("category")
    product_type = action_payload.get("product_type")
    user_context = action_payload.get("user_context")
    research_brief = action_payload.get("research_brief")

    _require_non_empty_string(category, "action_payload.category")
    _require_non_empty_string(product_type, "action_payload.product_type")
    _require_non_empty_string(user_context, "action_payload.user_context")
    if research_brief is not None and not isinstance(research_brief, str):
        raise ValueError("action_payload.research_brief must be a string when provided.")


def validate_research_payload(task_type: str, action_payload: Any) -> None:
    """Run task-specific payload sanity checks before creating the research agent."""

    validator = {
        "dispatch_product_search": validate_product_search_payload,
        "dispatch_category_research": validate_category_research_payload,
    }.get(task_type)
    if validator is None:
        LOGGER.error("Unsupported research task type for payload validation: %s", task_type)
        raise ValueError("Unsupported research task type.")

    try:
        validator(action_payload)
    except ValueError as error:
        LOGGER.error("Research payload sanity check failed for %s: %s", task_type, error)
        raise


def _build_validation_note(warnings: list[str]) -> str:
    warning_summary = "；".join(warnings)
    return f"{VALIDATION_NOTE_PREFIX} {warning_summary}"


def _append_note(existing_notes: str | None, warnings: list[str]) -> str:
    validation_note = _build_validation_note(warnings)
    if isinstance(existing_notes, str) and existing_notes.strip():
        return f"{existing_notes.rstrip()}\n{validation_note}"
    return validation_note


def _is_valid_source_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_product_search_output(
    result: ProductSearchOutput,
) -> tuple[ProductSearchOutput, list[str]]:
    """Run application-layer sanity checks on ProductSearchOutput."""

    warnings: list[str] = []
    for index, product in enumerate(result.products):
        prefix = f"products[{index}]"
        if not isinstance(product.name, str) or not product.name.strip():
            warnings.append(f"{prefix}.name 不能为空。")
        if not isinstance(product.brand, str) or not product.brand.strip():
            warnings.append(f"{prefix}.brand 不能为空。")
        if not isinstance(product.price.display, str) or not product.price.display.strip():
            warnings.append(f"{prefix}.price.display 不能为空。")
        if product.price.amount is not None:
            if product.price.amount <= 0:
                warnings.append(f"{prefix}.price.amount 必须大于 0。")
            elif product.price.amount >= MAX_REASONABLE_PRICE_AMOUNT:
                warnings.append(f"{prefix}.price.amount 疑似异常高价。")
        if not isinstance(product.specs, dict) or not product.specs:
            warnings.append(f"{prefix}.specs 应为非空对象。")
        if not isinstance(product.features, list) or not product.features:
            warnings.append(f"{prefix}.features 应为非空列表。")
        if not isinstance(product.pros, list) or not product.pros:
            warnings.append(f"{prefix}.pros 应为非空列表。")
        if not isinstance(product.cons, list) or not product.cons:
            warnings.append(f"{prefix}.cons 应为非空列表。")
        if not isinstance(product.sources, list) or not product.sources:
            warnings.append(f"{prefix}.sources 应为非空列表。")
        elif any(not isinstance(source, str) or not _is_valid_source_url(source) for source in product.sources):
            warnings.append(f"{prefix}.sources 应包含有效 URL。")
        if product.source_consistency not in VALID_SOURCE_CONSISTENCY:
            warnings.append(f"{prefix}.source_consistency 必须为 high/medium/low。")

    if not warnings:
        return result, warnings

    LOGGER.warning("Research output validation warnings for product search: %s", warnings)
    return result.model_copy(update={"notes": _append_note(result.notes, warnings)}), warnings


def validate_category_research_output(
    result: CategoryResearchOutput,
) -> tuple[CategoryResearchOutput, list[str]]:
    """Run application-layer sanity checks on CategoryResearchOutput."""

    warnings: list[str] = []
    if not result.category_knowledge.data_sources:
        warnings.append("category_knowledge.data_sources 不应为空。")
    if not result.category_knowledge.product_type_overview:
        warnings.append("category_knowledge.product_type_overview 不应为空。")
    if not result.product_type_knowledge.decision_dimensions:
        warnings.append("product_type_knowledge.decision_dimensions 不应为空。")
    if not result.product_type_knowledge.scenario_mapping:
        warnings.append("product_type_knowledge.scenario_mapping 不应为空。")

    if not warnings:
        return result, warnings

    LOGGER.warning("Research output validation warnings for category research: %s", warnings)
    return result.model_copy(update={"notes": _append_note(result.notes, warnings)}), warnings


def validate_research_output(result: ResearchOutput) -> tuple[ResearchOutput, list[str]]:
    """Apply application-layer validation to a structured research result."""

    if isinstance(result, ProductSearchOutput):
        return validate_product_search_output(result)
    return validate_category_research_output(result)


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

    validate_research_payload(task_type, action_payload)

    if task_type == "dispatch_product_search":
        instructions = build_product_search_instructions(action_payload)
        task_prompt = (
            "请根据提供的约束执行产品搜索，并严格按 ProductSearchOutput 返回结构化结果。"
        )
        response_format: type[ResearchOutput] = ProductSearchOutput
    elif task_type == "dispatch_category_research":
        instructions = build_category_research_instructions(action_payload)
        task_prompt = (
            "请根据提供的品类调研任务执行搜索，并严格按 CategoryResearchOutput 返回结构化结果。"
        )
        response_format = CategoryResearchOutput
    else:
        raise ValueError("Unsupported research task type.")

    runner = create_research_agent(instructions=instructions, client=client)
    return await runner.run_structured(task_prompt, response_format)
