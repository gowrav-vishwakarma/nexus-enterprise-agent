"""Retrieve tool for RAG."""

from __future__ import annotations

import json
from typing import Optional

from nexus.rag.protocol import EmbeddingsProtocol, VectorStore
from nexus.scope import ScopeLevel, scope_key
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool


class RetrieveToolPlugin:
    """Namespace plugin exposing rag.retrieve."""

    _plugin_name = "rag"

    def __init__(
        self,
        store: VectorStore,
        embeddings: Optional[EmbeddingsProtocol] = None,
    ):
        self.store = store
        self.embeddings = embeddings

    @tool(name="retrieve", description="Search the knowledge base for relevant passages.")
    async def retrieve(
        self,
        query: str,
        k: int = 5,
        ctx: Optional[RunContext] = None,
    ) -> str:
        if ctx is None:
            return json.dumps({"ok": False, "error": "missing context"})
        collection = scope_key(ctx, ScopeLevel.TENANT, "rag")
        if self.embeddings is None:
            return json.dumps({"ok": False, "error": "embeddings not configured"})
        vectors = await self.embeddings.embed([query])
        hits = await self.store.search(collection, vectors[0], k=k)
        return json.dumps(
            {
                "ok": True,
                "results": [{"text": h.text, "metadata": h.metadata} for h in hits],
            }
        )


def create_retrieve_plugin(
    store: VectorStore,
    embeddings: Optional[EmbeddingsProtocol] = None,
) -> RetrieveToolPlugin:
    return RetrieveToolPlugin(store, embeddings)
