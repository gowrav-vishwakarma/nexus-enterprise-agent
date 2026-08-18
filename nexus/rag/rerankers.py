"""Pass-through and optional API rerankers."""

from __future__ import annotations

from typing import Any

from nexus.rag.protocol import DocumentChunk


class PassThroughReranker:
    """Keep the incoming order and cut to ``k``."""

    async def rerank(
        self, query: str, chunks: list[DocumentChunk], k: int = 5
    ) -> list[DocumentChunk]:
        del query
        return chunks[:k]


class CohereReranker:
    """Optional Cohere Rerank. Requires the ``cohere`` package at call time."""

    def __init__(self, api_key: str, *, model: str = "rerank-v3.5"):
        self.api_key = api_key
        self.model = model

    async def rerank(
        self, query: str, chunks: list[DocumentChunk], k: int = 5
    ) -> list[DocumentChunk]:
        try:
            import cohere  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "CohereReranker needs the cohere package. Install it separately."
            ) from exc
        if not chunks:
            return []
        client = cohere.AsyncClient(self.api_key)
        docs = [c.text for c in chunks]
        result = await client.rerank(
            model=self.model, query=query, documents=docs, top_n=min(k, len(docs))
        )
        return [chunks[item.index] for item in result.results]


class BGEReranker:
    """Optional local BGE cross-encoder. Requires ``sentence-transformers``."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.model_name = model_name
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder  # type: ignore

            self._model = CrossEncoder(self.model_name)
        return self._model

    async def rerank(
        self, query: str, chunks: list[DocumentChunk], k: int = 5
    ) -> list[DocumentChunk]:
        if not chunks:
            return []
        model = self._load()
        pairs = [(query, c.text) for c in chunks]
        scores = model.predict(pairs)
        ranked = sorted(zip(chunks, scores, strict=True), key=lambda x: float(x[1]), reverse=True)
        return [c for c, _ in ranked[:k]]
