"""RAG protocols."""

from __future__ import annotations

from typing import Any, Optional, Protocol, Union, runtime_checkable

from pydantic import BaseModel, Field

from nexus.tools.context import RunContext


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


@runtime_checkable
class Chunker(Protocol):
    """Split raw text into document chunks."""

    async def chunk(
        self, text: str, *, metadata: dict[str, Any] | None = None
    ) -> list[DocumentChunk]: ...


@runtime_checkable
class SparseIndex(Protocol):
    """Optional keyword / BM25-style index."""

    async def upsert(self, collection: str, chunks: list[DocumentChunk]) -> None: ...
    async def search(
        self, collection: str, query: str, k: int = 5
    ) -> list[DocumentChunk]: ...


@runtime_checkable
class Reranker(Protocol):
    """Score and reorder candidate chunks for a query."""

    async def rerank(
        self, query: str, chunks: list[DocumentChunk], k: int = 5
    ) -> list[DocumentChunk]: ...


@runtime_checkable
class RAGProvider(Protocol):
    """Composite retrieval object the runner talks to."""

    async def ingest(
        self,
        ctx: RunContext,
        documents: Union[list[DocumentChunk], list[str]],
        *,
        collection: str | None = None,
    ) -> None: ...

    async def retrieve(
        self, ctx: RunContext, query: str, k: int = 5
    ) -> list[DocumentChunk]: ...
