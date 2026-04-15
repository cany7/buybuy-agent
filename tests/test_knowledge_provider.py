from __future__ import annotations

import shutil
from pathlib import Path

from src.context.knowledge_provider import KnowledgeContextProvider
from src.store.document_store import DocumentStore


def test_knowledge_provider_loads_fixture_from_runtime_file(tmp_path: Path) -> None:
    store = DocumentStore(base_dir=tmp_path / "data")
    fixture_path = Path(__file__).resolve().parents[0] / "fixtures" / "户外装备.json"
    runtime_path = store.knowledge_dir / "户外装备.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture_path, runtime_path)

    provider = KnowledgeContextProvider(store=store)
    context = provider.build_context({"category": "户外装备", "product_type": "冲锋衣"})

    assert "## 品类知识：户外装备" in context
    assert "GORE-TEX" in context
    assert "冲锋衣" in context
    assert "防水" in context
