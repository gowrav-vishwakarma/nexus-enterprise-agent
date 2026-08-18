"""Retrieve tool for RAG."""

from __future__ import annotations

import json
from typing import Any, Optional, Union

from nexus.rag.protocol import EmbeddingsProtocol, RAGProvider, VectorStore
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool


def _is_rag_provider(obj: Any) -> bool:
    return hasattr(obj, "retrieve") and hasattr(obj, "ingest")


class RetrieveToolPlugin:
    """Namespace plugin exposing rag.retrieve.

    Accepts a ``RAGProvider``, or the legacy ``(store, embeddings)`` pair which
    is wrapped in ``InMemoryRAGProvider``.
    """

    _plugin_name = "rag"

    def __init__(
        self,
        store_or_provider: Union[VectorStore, RAGProvider],
        embeddings: Optional[EmbeddingsProtocol] = None,
        *,
        provider: Optional[RAGProvider] = None,
    ):
        if provider is not None:
            self.provider = provider
            self.store = getattr(provider, "store", store_or_provider)
            self.embeddings = embeddings or getattr(provider, "embeddings", None)
        elif _is_rag_provider(store_or_provider):
            self.provider = store_or_provider  # type: ignore[assignment]
            self.store = getattr(store_or_provider, "store", store_or_provider)
            self.embeddings = embeddings or getattr(store_or_provider, "embeddings", None)
        else:
            from nexus.rag.providers.in_memory import InMemoryRAGProvider

            wrapped = InMemoryRAGProvider(
                store=store_or_provider,  # type: ignore[arg-type]
                embeddings=embeddings,
            )
            self.provider = wrapped
            self.store = store_or_provider
            self.embeddings = embeddings or wrapped.embeddings

    @tool(name="retrieve", description="Search the knowledge base for relevant passages.")
    async def retrieve(
        self,
        query: str,
        k: int = 5,
        ctx: Optional[RunContext] = None,
    ) -> str:
        if ctx is None:
            return json.dumps({"ok": False, "error": "missing context"})
        hits = await self.provider.retrieve(ctx, query, k=k)
        return json.dumps(
            {
                "ok": True,
                "results": [{"text": h.text, "metadata": h.metadata} for h in hits],
            }
        )


def create_retrieve_plugin(
    store: Union[VectorStore, RAGProvider],
    embeddings: Optional[EmbeddingsProtocol] = None,
) -> RetrieveToolPlugin:
    """Factory used by apps and the runner. Accepts a store pair or a provider."""
    return RetrieveToolPlugin(store, embeddings)
