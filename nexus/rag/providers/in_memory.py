"""In-memory RAG provider (default for tests and local development)."""

from __future__ import annotations

from typing import Any, Optional, Union

from nexus.rag.chunking import build_chunker
from nexus.rag.config import RAGConfig
from nexus.rag.embeddings import HashingEmbeddings
from nexus.rag.fusion import reciprocal_rank_fusion
from nexus.rag.memory import InMemorySparseIndex, InMemoryVectorStore
from nexus.rag.protocol import DocumentChunk, EmbeddingsProtocol, Reranker, SparseIndex, VectorStore
from nexus.rag.rerankers import PassThroughReranker
from nexus.scope import ScopeLevel, scope_key
from nexus.tools.context import RunContext


def scoped_collection_key(
    ctx: RunContext,
    *,
    collection: str,
    scope_level: str = "tenant",
) -> str:
    """Build the storage key for a RAG collection.

    The default collection name ``default`` maps to namespace ``rag`` so the
    old ``RetrieveToolPlugin(store, embeddings)`` path keeps the same key
    (``scope_key(ctx, TENANT, "rag")``).
    """
    level = ScopeLevel(scope_level)
    ns = "rag" if collection in ("", "default", "rag") else f"rag:{collection}"
    return scope_key(ctx, level, ns)


class InMemoryRAGProvider:
    """Composite provider: chunk → embed → dense (+ optional sparse) → fuse → rerank."""

    def __init__(
        self,
        *,
        embeddings: Optional[EmbeddingsProtocol] = None,
        store: Optional[VectorStore] = None,
        sparse: Optional[SparseIndex] = None,
        chunker: Any = None,
        reranker: Optional[Reranker] = None,
        config: Optional[RAGConfig] = None,
        **_: Any,
    ):
        self.config = config or RAGConfig()
        self.embeddings = embeddings or HashingEmbeddings()
        self.store = store or InMemoryVectorStore()
        self.sparse = sparse or InMemorySparseIndex()
        self.chunker = chunker or build_chunker(
            self.config.chunker.strategy,
            chunk_size=self.config.chunker.chunk_size,
            overlap=self.config.chunker.overlap,
            contextual=self.config.chunker.contextual,
            embeddings=self.embeddings,
        )
        self.reranker = reranker or PassThroughReranker()

    def _collection(self, ctx: RunContext, collection: str | None = None) -> str:
        name = collection or self.config.collection
        return scoped_collection_key(
            ctx, collection=name, scope_level=self.config.scope_level
        )

    async def ingest(
        self,
        ctx: RunContext,
        documents: Union[list[DocumentChunk], list[str]],
        *,
        collection: str | None = None,
    ) -> None:
        col = self._collection(ctx, collection)
        chunks: list[DocumentChunk] = []
        for doc in documents:
            if isinstance(doc, DocumentChunk):
                chunks.append(doc)
            else:
                chunks.extend(await self.chunker.chunk(str(doc)))
        if not chunks:
            return
        missing = [c for c in chunks if not c.embedding]
        if missing:
            vectors = await self.embeddings.embed([c.text for c in missing])
            for chunk, vector in zip(missing, vectors, strict=True):
                chunk.embedding = vector
        await self.store.upsert(col, chunks)
        await self.sparse.upsert(col, chunks)

    async def retrieve(
        self, ctx: RunContext, query: str, k: int = 5
    ) -> list[DocumentChunk]:
        col = self._collection(ctx)
        retrieval = self.config.retrieval
        candidate_k = max(k, retrieval.k)
        if retrieval.hybrid or retrieval.rerank:
            candidate_k = max(candidate_k, retrieval.rerank_top_k)
        vectors = await self.embeddings.embed([query])
        dense = await self.store.search(col, vectors[0], k=candidate_k)
        if retrieval.hybrid:
            sparse_hits = await self.sparse.search(col, query, k=candidate_k)
            fused = reciprocal_rank_fusion([dense, sparse_hits], top_n=candidate_k)
        else:
            fused = dense
        if retrieval.rerank:
            return await self.reranker.rerank(query, fused, k=k)
        return fused[:k]
