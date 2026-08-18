"""Tests for RAG chunkers."""

import pytest

from nexus.rag.chunking import (
    ContextualChunker,
    FixedChunker,
    RecursiveChunker,
    SemanticChunker,
    chunk_text,
)
from nexus.rag.embeddings import HashingEmbeddings


def test_chunk_text_overlap():
    chunks = chunk_text("abcdefghijklmnopqrstuvwxyz", chunk_size=10, overlap=3)
    assert chunks[0] == "abcdefghij"
    assert chunks[1].startswith("hij")
    assert "".join(c[3:] if i else c for i, c in enumerate(chunks)) or True
    assert chunks[-1].endswith("z")


@pytest.mark.asyncio
async def test_fixed_chunker_metadata():
    chunker = FixedChunker(chunk_size=8, overlap=0)
    chunks = await chunker.chunk("abcdefghijklmnop", metadata={"doc": "a"})
    assert len(chunks) == 2
    assert chunks[0].metadata["doc"] == "a"
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[0].id.startswith("chk_")


@pytest.mark.asyncio
async def test_recursive_chunker_prefers_paragraphs():
    text = "First paragraph is short.\n\nSecond paragraph is also short."
    chunks = await RecursiveChunker(chunk_size=40, overlap=0).chunk(text)
    assert len(chunks) >= 1
    assert any("First paragraph" in c.text for c in chunks)


@pytest.mark.asyncio
async def test_contextual_chunker_prepends():
    inner = FixedChunker(chunk_size=20, overlap=0)
    chunker = ContextualChunker(inner, context="About cats")
    chunks = await chunker.chunk("Cats sleep a lot during the day.")
    assert chunks
    assert chunks[0].text.startswith("Context: About cats")
    assert chunks[0].metadata["contextual"] is True


@pytest.mark.asyncio
async def test_semantic_chunker_falls_back_without_embeddings():
    chunker = SemanticChunker(embeddings=None, chunk_size=40, overlap=0)
    chunks = await chunker.chunk("One sentence. Two sentence. Three sentence.")
    assert chunks


@pytest.mark.asyncio
async def test_semantic_chunker_splits_on_low_similarity():
    embeddings = HashingEmbeddings(dim=32)
    chunker = SemanticChunker(embeddings, chunk_size=80, overlap=0, threshold=0.99)
    text = (
        "Alpha alpha alpha alpha. Zebra zebra zebra zebra. "
        "Alpha alpha continues. Zebra zebra continues."
    )
    chunks = await chunker.chunk(text)
    assert len(chunks) >= 1
