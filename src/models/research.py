"""Research-side Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SharedConcept(BaseModel):
    """Cross-product-type concept within a category."""

    name: str
    description: str
    relevant_product_types: list[str]


class BrandInfo(BaseModel):
    """Brand summary."""

    brand: str
    positioning: str
    known_for: str


class ProductTypeOverview(BaseModel):
    """Overview entry for a product type."""

    product_type: str
    subtypes: list[str]
    description: str


class CategoryKnowledge(BaseModel):
    """Category-level reusable knowledge."""

    data_sources: list[str]
    product_type_overview: list[ProductTypeOverview]
    shared_concepts: list[SharedConcept]
    brand_landscape: list[BrandInfo]


class DecisionDimension(BaseModel):
    """Decision dimension definition."""

    name: str
    objectivity: str = Field(description="可量化 | 半量化 | 主观")
    importance: str = Field(description="高 | 中 | 低")
    ambiguity_risk: str = Field(description="高 | 中 | 低")
    ambiguity_note: str | None = None


class Tradeoff(BaseModel):
    """Tradeoff between dimensions."""

    dimensions: list[str]
    explanation: str


class PriceTier(BaseModel):
    """Price tier definition."""

    range: str
    typical: str
    features: str


class ScenarioMapping(BaseModel):
    """Scenario to requirement mapping."""

    scenario: str
    key_needs: list[str]
    can_compromise: list[str]


class Misconception(BaseModel):
    """Common misconception entry."""

    misconception: str
    reality: str
    anchor_suggestion: str


class ProductTypeKnowledge(BaseModel):
    """Product-type-specific knowledge."""

    subtypes: dict[str, str]
    decision_dimensions: list[DecisionDimension]
    tradeoffs: list[Tradeoff]
    price_tiers: list[PriceTier]
    scenario_mapping: list[ScenarioMapping]
    common_misconceptions: list[Misconception]


class CategoryResearchOutput(BaseModel):
    """Structured output for category research tasks."""

    category: str
    category_knowledge: CategoryKnowledge
    product_type_name: str
    product_type_knowledge: ProductTypeKnowledge
    notes: str | None = None


class PriceInfo(BaseModel):
    """Structured price information."""

    display: str
    currency: str | None = None
    amount: float | None = None


class ProductInfo(BaseModel):
    """Single product record from research output."""

    name: str
    brand: str
    price: PriceInfo
    specs: dict
    features: list[str]
    pros: list[str]
    cons: list[str]
    sources: list[str]
    source_consistency: str = Field(description="high | medium | low")


class ProductSearchOutput(BaseModel):
    """Structured output for product search tasks."""

    products: list[ProductInfo] = Field(default_factory=list)
    notes: str
    suggested_followup: str | None = None
