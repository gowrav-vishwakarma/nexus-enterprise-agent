"""In-memory vector store for development."""

from __future__ import annotations

import math
from typing import Dict, List

from nexus.rag.protocol import DocumentChunk


def _cosine(a: list[float], b: list[float]) -> float:
    # Mismatched lengths mean two different embedding models; scoring them against
    # each other would return a confident but meaningless number.
    if len(a) != len(b):
        raise ValueError(f"Embedding dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class InMemoryVectorStore:
    """Simple in-memory vector store keyed by collection."""

    def __init__(self) -> None:
        self._data: Dict[str, List[DocumentChunk]] = {}

    async def upsert(self, collection: str, chunks: list[DocumentChunk]) -> None:
        self._data.setdefault(collection, []).extend(chunks)

    async def search(
        self, collection: str, query_embedding: list[float], k: int = 5
    ) -> list[DocumentChunk]:
        items = self._data.get(collection, [])
        scored = [
            (c, _cosine(query_embedding, c.embedding or []))
            for c in items
            if c.embedding
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:k]]
