"""RAG primitives: embeddings, chunking, vector store, providers."""

from nexus.rag.protocol import (
    Chunker,
    DocumentChunk,
    EmbeddingsProtocol,
    RAGProvider,
    Reranker,
    SparseIndex,
    VectorStore,
)
from nexus.rag.config import ChunkerConfig, RAGConfig, RetrievalConfig
from nexus.rag.chunking import (
    ContextualChunker,
    FixedChunker,
    RecursiveChunker,
    SemanticChunker,
    chunk_text,
)
from nexus.rag.embeddings import HashingEmbeddings
from nexus.rag.memory import InMemorySparseIndex, InMemoryVectorStore
from nexus.rag.providers.in_memory import InMemoryRAGProvider
from nexus.rag.retrieve import RetrieveToolPlugin, create_retrieve_plugin
from nexus.rag.rerankers import PassThroughReranker

__all__ = [
    "Chunker",
    "DocumentChunk",
    "EmbeddingsProtocol",
    "RAGProvider",
    "Reranker",
    "SparseIndex",
    "VectorStore",
    "ChunkerConfig",
    "RAGConfig",
    "RetrievalConfig",
    "ContextualChunker",
    "FixedChunker",
    "RecursiveChunker",
    "SemanticChunker",
    "chunk_text",
    "HashingEmbeddings",
    "InMemorySparseIndex",
    "InMemoryVectorStore",
    "InMemoryRAGProvider",
    "RetrieveToolPlugin",
    "create_retrieve_plugin",
    "PassThroughReranker",
]
