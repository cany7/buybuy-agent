from __future__ import annotations

from pathlib import Path

from src.context.knowledge_provider import KnowledgeContextProvider
from src.store.document_store import DocumentStore


def test_knowledge_provider_loads_requested_product_type_only(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_knowledge(
        "户外装备",
        {
            "category_knowledge": {
                "shared_concepts": [{"name": "GORE-TEX", "description": "面料", "relevant_product_types": ["冲锋衣"]}]
            },
            "product_types": {
                "冲锋衣": {"decision_dimensions": [{"name": "防水"}]},
                "登山鞋": {"decision_dimensions": [{"name": "支撑"}]},
            },
        },
    )

    provider = KnowledgeContextProvider(store=store)
    context = provider.build_context({"category": "户外装备", "product_type": "冲锋衣"})

    assert "## 品类知识：户外装备" in context
    assert "GORE-TEX" in context
    assert "冲锋衣" in context
    assert "防水" in context
    assert "登山鞋" not in context


def test_knowledge_provider_marks_missing_category_research_need(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    provider = KnowledgeContextProvider(store=store)

    context = provider.build_context({"category": "户外装备", "product_type": "冲锋衣"})

    assert "需要品类调研" in context


def test_knowledge_provider_marks_missing_product_type_and_injects_known_types(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    store.save_knowledge(
        "户外装备",
        {
            "category_knowledge": {
                "shared_concepts": [{"name": "GORE-TEX", "description": "面料", "relevant_product_types": ["冲锋衣"]}]
            },
            "product_types": {
                "冲锋衣": {"decision_dimensions": [{"name": "防水"}]},
                "登山鞋": {"decision_dimensions": [{"name": "支撑"}]},
            },
        },
    )
    provider = KnowledgeContextProvider(store=store)

    context = provider.build_context({"category": "户外装备", "product_type": "抓绒衣"})

    assert "GORE-TEX" in context
    assert "需要产品类型调研" in context
    assert "冲锋衣" in context
    assert "登山鞋" in context
