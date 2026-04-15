"""Phase 1 knowledge context provider backed by runtime fixtures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.store.document_store import DocumentStore

SessionState = dict[str, Any]


@dataclass(slots=True)
class KnowledgeContextProvider:
    """Load full category knowledge for Phase 1 without selective loading."""

    store: DocumentStore

    def build_context(self, session: SessionState) -> str:
        """Return knowledge context for the current category if available."""

        category = session.get("category")
        if not isinstance(category, str) or not category.strip():
            return ""

        knowledge_path = self.store.knowledge_dir / f"{category}.json"
        if not knowledge_path.exists():
            return ""

        with knowledge_path.open("r", encoding="utf-8") as file:
            knowledge = json.load(file)
        if not isinstance(knowledge, dict):
            raise ValueError(f"Knowledge file {knowledge_path} must contain a JSON object.")

        return "\n".join(
            [
                f"## 品类知识：{category}",
                json.dumps(knowledge, ensure_ascii=False, indent=2),
            ]
        )
