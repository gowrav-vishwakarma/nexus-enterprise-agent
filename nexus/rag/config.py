"""RAG configuration models.

All fields are optional. When ``AgentConfig.rag`` is ``None``, the runner does
not register retrieval tools and existing apps are unchanged.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChunkerConfig(BaseModel):
    """How ingested text is split into chunks before embedding."""

    strategy: Literal["fixed", "recursive", "semantic", "none"] = Field(
        default="fixed",
        description="Chunking strategy (semantic needs an embeddings model)",
    )
    chunk_size: int = Field(
        default=512, ge=32, description="Target chunk size in characters"
    )
    overlap: int = Field(
        default=64, ge=0, description="Character overlap between adjacent chunks"
    )
    contextual: bool = Field(
        default=False,
        description="Prepend a short document-context summary to each chunk before embedding",
    )


class RetrievalConfig(BaseModel):
    """How retrieve() searches a collection."""

    k: int = Field(default=5, ge=1, description="Number of chunks to return")
    hybrid: bool = Field(
        default=False,
        description="Run dense (vector) and sparse (keyword) search and fuse results",
    )
    rerank: bool = Field(
        default=False,
        description="Pass fused candidates through a reranker (opt-in; may add latency)",
    )
    rerank_top_k: int = Field(
        default=50, ge=1, description="Candidate count fed to the reranker before cutting to k"
    )


class RAGConfig(BaseModel):
    """Opt-in retrieval-augmented generation settings on an agent.

    Leave this unset (``None`` on ``AgentConfig.rag``) to keep current behaviour:
    no ``rag.retrieve`` tool is registered.
    """

    provider: Literal["in_memory", "pgvector", "custom_class"] = Field(
        default="in_memory",
        description="Built-in provider id, or custom_class with provider_class",
    )
    provider_class: Optional[str] = Field(
        default=None,
        description="Dotted import path when provider is custom_class",
    )
    provider_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Kwargs passed to the provider constructor",
    )
    collection: str = Field(
        default="default",
        description="Logical collection name (scoped by tenant at run time)",
    )
    chunker: ChunkerConfig = Field(
        default_factory=ChunkerConfig,
        description="Ingestion chunking",
    )
    retrieval: RetrievalConfig = Field(
        default_factory=RetrievalConfig,
        description="Query-time retrieval",
    )
    embeddings_class: Optional[str] = Field(
        default=None,
        description="Optional dotted path to an EmbeddingsProtocol implementation",
    )
    reranker_class: Optional[str] = Field(
        default=None,
        description="Optional dotted path to a Reranker implementation",
    )
    scope_level: Literal["global", "tenant", "company", "user"] = Field(
        default="tenant",
        description="How collections are partitioned so tenants cannot mix data",
    )
