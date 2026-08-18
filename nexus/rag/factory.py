"""Build a RAGProvider from RAGConfig."""

from __future__ import annotations

from typing import Any, Optional

from nexus.orchestration.imports import import_from_path
from nexus.rag.config import RAGConfig
from nexus.rag.embeddings import HashingEmbeddings
from nexus.rag.protocol import EmbeddingsProtocol, RAGProvider, Reranker
from nexus.rag.providers.in_memory import InMemoryRAGProvider
from nexus.rag.rerankers import PassThroughReranker


def build_rag_provider(
    config: RAGConfig,
    *,
    embeddings: Optional[EmbeddingsProtocol] = None,
    reranker: Optional[Reranker] = None,
    **extra: Any,
) -> RAGProvider:
    """Instantiate the configured RAG provider.

    ``custom_class`` loads ``config.provider_class``. ``pgvector`` is imported
    lazily so the postgres extra is not required until you select it.
    """
    embedder = embeddings
    if embedder is None and config.embeddings_class:
        embedder = import_from_path(config.embeddings_class)()
    if embedder is None:
        embedder = HashingEmbeddings()

    ranker = reranker
    if ranker is None and config.reranker_class:
        ranker = import_from_path(config.reranker_class)()
    if ranker is None:
        ranker = PassThroughReranker()

    kwargs = {**config.provider_config, **extra}

    if config.provider == "custom_class":
        if not config.provider_class:
            raise ValueError("RAGConfig.provider_class is required when provider is custom_class")
        cls = import_from_path(config.provider_class)
        return cls(
            embeddings=embedder,
            reranker=ranker,
            config=config,
            **kwargs,
        )

    if config.provider == "pgvector":
        from nexus.rag.providers.pgvector import PGVectorRAGProvider

        return PGVectorRAGProvider(
            embeddings=embedder,
            reranker=ranker,
            config=config,
            **kwargs,
        )

    return InMemoryRAGProvider(
        embeddings=embedder,
        reranker=ranker,
        config=config,
        **kwargs,
    )
