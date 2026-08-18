"""Small RAG eval over the in-memory provider using the fixture JSONL."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.rag.config import RAGConfig, RetrievalConfig
from nexus.rag.embeddings import HashingEmbeddings
from nexus.rag.providers.in_memory import InMemoryRAGProvider
from nexus.tools.context import RunContext

FIXTURE = Path(__file__).parent / "fixtures" / "rag_eval.jsonl"


def _load_rows() -> list[dict]:
    rows = []
    with FIXTURE.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@pytest.mark.asyncio
async def test_in_memory_rag_eval_hit_rate():
    rows = _load_rows()
    assert len(rows) == 50
    provider = InMemoryRAGProvider(
        embeddings=HashingEmbeddings(dim=64),
        config=RAGConfig(retrieval=RetrievalConfig(k=5, hybrid=True)),
    )
    ctx = RunContext(tenant_id="eval", user_id="eval")
    await provider.ingest(ctx, [row["doc"] for row in rows])
    hits = 0
    for row in rows:
        retrieved = await provider.retrieve(ctx, row["query"], k=5)
        texts = " ".join(h.text for h in retrieved)
        if row["answer"].lower() in texts.lower() or row["doc"] in texts:
            hits += 1
    assert hits / len(rows) >= 0.6
