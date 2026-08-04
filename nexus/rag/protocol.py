"""RAG protocols."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[list[float]] = None


@runtime_checkable
class EmbeddingsProtocol(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class VectorStore(Protocol):
    async def upsert(self, collection: str, chunks: list[DocumentChunk]) -> None: ...
    async def search(
        self, collection: str, query_embedding: list[float], k: int = 5
    ) -> list[DocumentChunk]: ...
