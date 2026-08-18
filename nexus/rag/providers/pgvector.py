"""PostgreSQL + pgvector RAG provider (optional ``nexus[postgres]`` extra)."""

from __future__ import annotations

import json
from typing import Any, Optional, Union

from nexus.rag.chunking import build_chunker
from nexus.rag.config import RAGConfig
from nexus.rag.embeddings import HashingEmbeddings
from nexus.rag.fusion import reciprocal_rank_fusion
from nexus.rag.protocol import DocumentChunk, EmbeddingsProtocol, Reranker
from nexus.rag.providers.in_memory import scoped_collection_key
from nexus.rag.rerankers import PassThroughReranker
from nexus.tools.context import RunContext


class PGVectorRAGProvider:
    """Dense vectors in Postgres; sparse search via ``tsvector``.

    Requires ``asyncpg``. The ``pgvector`` extension is used when present;
    otherwise embeddings are stored as ``float[]`` and scored in Python.
    """

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        pool: Any = None,
        embeddings: Optional[EmbeddingsProtocol] = None,
        reranker: Optional[Reranker] = None,
        config: Optional[RAGConfig] = None,
        table: str = "nexus_rag_chunks",
        **_: Any,
    ):
        try:
            import asyncpg  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PGVectorRAGProvider. "
                "Install with: pip install nexus-enterprise-agent[postgres]"
            ) from exc
        if dsn is None and pool is None:
            raise ValueError("PGVectorRAGProvider needs dsn= or pool=")
        self.dsn = dsn
        self._pool = pool
        self._owns_pool = pool is None
        self.config = config or RAGConfig()
        self.embeddings = embeddings or HashingEmbeddings()
        self.reranker = reranker or PassThroughReranker()
        self.table = table
        self.chunker = build_chunker(
            self.config.chunker.strategy,
            chunk_size=self.config.chunker.chunk_size,
            overlap=self.config.chunker.overlap,
            contextual=self.config.chunker.contextual,
            embeddings=self.embeddings,
        )
        self._schema_ready = False
        self._dims: dict[str, int] = {}

    async def _get_pool(self):
        import asyncpg

        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
        return self._pool

    async def close(self) -> None:
        if self._pool is not None and self._owns_pool:
            await self._pool.close()
            self._pool = None

    async def _ensure_schema(self, conn) -> None:
        if self._schema_ready:
            return
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                id TEXT PRIMARY KEY,
                collection TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{{}}',
                embedding FLOAT8[],
                tsv tsvector
            );
            CREATE INDEX IF NOT EXISTS idx_{self.table}_collection
                ON {self.table} (collection);
            """
        )
        self._schema_ready = True

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
        dim = len(chunks[0].embedding or [])
        existing = self._dims.get(col)
        if existing is not None and existing != dim:
            raise ValueError(
                f"Embedding dimension mismatch: collection {col!r} has dim {existing}, "
                f"new chunks have dim {dim}"
            )
        self._dims[col] = dim
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_schema(conn)
            for chunk in chunks:
                await conn.execute(
                    f"""
                    INSERT INTO {self.table} (id, collection, text, metadata, embedding, tsv)
                    VALUES ($1, $2, $3, $4::jsonb, $5, to_tsvector('simple', $3))
                    ON CONFLICT (id) DO UPDATE SET
                        text = EXCLUDED.text,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding,
                        tsv = EXCLUDED.tsv
                    """,
                    chunk.id,
                    col,
                    chunk.text,
                    json.dumps(chunk.metadata),
                    chunk.embedding,
                )

    async def retrieve(
        self, ctx: RunContext, query: str, k: int = 5
    ) -> list[DocumentChunk]:
        col = self._collection(ctx)
        retrieval = self.config.retrieval
        candidate_k = max(k, retrieval.k)
        if retrieval.hybrid or retrieval.rerank:
            candidate_k = max(candidate_k, retrieval.rerank_top_k)
        query_vec = (await self.embeddings.embed([query]))[0]
        expected = self._dims.get(col)
        if expected is not None and len(query_vec) != expected:
            raise ValueError(
                f"Embedding dimension mismatch: {len(query_vec)} vs {expected}"
            )
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_schema(conn)
            rows = await conn.fetch(
                f"""
                SELECT id, text, metadata, embedding
                FROM {self.table}
                WHERE collection = $1
                """,
                col,
            )
            sparse_rows = []
            if retrieval.hybrid:
                sparse_rows = await conn.fetch(
                    f"""
                    SELECT id, text, metadata, embedding,
                           ts_rank_cd(tsv, plainto_tsquery('simple', $2)) AS rank
                    FROM {self.table}
                    WHERE collection = $1 AND tsv @@ plainto_tsquery('simple', $2)
                    ORDER BY rank DESC
                    LIMIT $3
                    """,
                    col,
                    query,
                    candidate_k,
                )

        dense = _rank_dense(rows, query_vec, candidate_k)
        if retrieval.hybrid:
            sparse_hits = [
                DocumentChunk(
                    id=r["id"],
                    text=r["text"],
                    metadata=_as_meta(r["metadata"]),
                    embedding=list(r["embedding"]) if r["embedding"] is not None else None,
                )
                for r in sparse_rows
            ]
            fused = reciprocal_rank_fusion([dense, sparse_hits], top_n=candidate_k)
        else:
            fused = dense
        if retrieval.rerank:
            return await self.reranker.rerank(query, fused, k=k)
        return fused[:k]


def _as_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(x * x for x in b) ** 0.5 or 1.0
    return dot / (na * nb)


def _rank_dense(rows: list[Any], query_vec: list[float], k: int) -> list[DocumentChunk]:
    scored: list[tuple[float, DocumentChunk]] = []
    for row in rows:
        emb = list(row["embedding"]) if row["embedding"] is not None else []
        if not emb:
            continue
        scored.append(
            (
                _cosine(query_vec, emb),
                DocumentChunk(
                    id=row["id"],
                    text=row["text"],
                    metadata=_as_meta(row["metadata"]),
                    embedding=emb,
                ),
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]
