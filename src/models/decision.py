"""Decision-side Pydantic models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DimensionUpdate(BaseModel):
    """Single dimension update used only in internal reasoning."""

    dimension: str
    value: str | None = None
    priority: int = Field(ge=1, le=4)
    confidence: int = Field(ge=1, le=4)
    urgency: int = Field(ge=1, le=16)
    update_reason: str


class InternalReasoning(BaseModel):
    """Debug-facing reasoning trace for a single agent turn."""

    state_summary: str
    updated_dimensions: list[DimensionUpdate] = Field(default_factory=list)
    blocking_dimensions: list[str] = Field(default_factory=list)
    uncertain_dimensions: list[str] = Field(default_factory=list)
    jtbd_observations: str | None = None
    stage_assessment: str


class DecisionOutput(BaseModel):
    """Structured output produced by the main agent each turn."""

    user_message: str
    internal_reasoning: InternalReasoning
    next_action: Literal[
        "ask_user",
        "dispatch_category_research",
        "dispatch_product_search",
        "recommend",
        "onboard_user",
    ]
    action_payload: dict | None = None
    session_updates: dict | None = None
    profile_updates: dict | None = None
