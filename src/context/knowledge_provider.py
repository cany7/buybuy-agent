"""Knowledge context provider with selective product-type loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.store.document_store import DocumentStore

SessionState = dict[str, Any]


@dataclass(slots=True)
class KnowledgeContextProvider:
    """Load deterministic knowledge snippets for the active category/product type."""

    store: DocumentStore

    def build_context(self, session: SessionState) -> str:
        """Return knowledge context for the current category and product type."""

        category = session.get("category")
        if not isinstance(category, str) or not category.strip():
            return ""

        product_type = session.get("product_type")
        full_knowledge = self.store.load_knowledge(category)
        if full_knowledge is None:
            return f'## [系统标注] 当前品类 "{category}" 无知识文档，需要品类调研。'

        category_knowledge = full_knowledge.get("category_knowledge", {})
        product_types = full_knowledge.get("product_types")
        known_types = sorted(product_types) if isinstance(product_types, dict) else []

        if not isinstance(product_type, str) or not product_type.strip():
            return "\n".join(
                [
                    f"## 品类知识：{category}",
                    json.dumps(category_knowledge, ensure_ascii=False, indent=2),
                ]
            )

        selected_knowledge = self.store.load_knowledge(category, product_type)
        selected_product_types = (
            selected_knowledge.get("product_types")
            if isinstance(selected_knowledge, dict)
            else None
        )
        if not isinstance(selected_product_types, dict) or product_type not in selected_product_types:
            parts = [
                f"## 品类知识：{category}",
                json.dumps(category_knowledge, ensure_ascii=False, indent=2),
                "",
                f'## [系统标注] 品类 "{category}" 缺少产品类型 "{product_type}" 的知识文档，需要产品类型调研。',
            ]
            if known_types:
                parts.extend(["", "## 已有产品类型", json.dumps(known_types, ensure_ascii=False, indent=2)])
            return "\n".join(parts)

        return "\n".join(
            [
                f"## 品类知识：{category}",
                json.dumps(category_knowledge, ensure_ascii=False, indent=2),
                "",
                f"## 产品类型知识：{product_type}",
                json.dumps(selected_product_types[product_type], ensure_ascii=False, indent=2),
            ]
        )
