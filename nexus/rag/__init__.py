"""RAG primitives: embeddings, chunking, vector store."""

from nexus.rag.protocol import EmbeddingsProtocol, VectorStore
from nexus.rag.chunking import chunk_text
from nexus.rag.memory import InMemoryVectorStore
from nexus.rag.retrieve import RetrieveToolPlugin, create_retrieve_plugin

__all__ = [
    "EmbeddingsProtocol",
    "VectorStore",
    "chunk_text",
    "InMemoryVectorStore",
    "RetrieveToolPlugin",
    "create_retrieve_plugin",
]
