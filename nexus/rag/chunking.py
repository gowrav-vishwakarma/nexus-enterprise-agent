"""Text chunking utilities."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from nexus.rag.protocol import DocumentChunk


def chunk_text(text: str, *, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """Split text into overlapping chunks by character count."""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _chunk_id(text: str, index: int) -> str:
    digest = hashlib.sha256(f"{index}:{text}".encode("utf-8")).hexdigest()[:16]
    return f"chk_{digest}"


class FixedChunker:
    """Character-count chunks with overlap (same as ``chunk_text``)."""

    def __init__(self, *, chunk_size: int = 512, overlap: int = 64):
        self.chunk_size = chunk_size
        self.overlap = overlap

    async def chunk(
        self, text: str, *, metadata: dict[str, Any] | None = None
    ) -> list[DocumentChunk]:
        meta = dict(metadata or {})
        out: list[DocumentChunk] = []
        for i, piece in enumerate(chunk_text(text, chunk_size=self.chunk_size, overlap=self.overlap)):
            out.append(
                DocumentChunk(
                    id=_chunk_id(piece, i),
                    text=piece,
                    metadata={**meta, "chunk_index": i},
                )
            )
        return out


class RecursiveChunker:
    """Split on paragraph, then sentence, then characters."""

    def __init__(self, *, chunk_size: int = 512, overlap: int = 64):
        self.chunk_size = chunk_size
        self.overlap = overlap

    async def chunk(
        self, text: str, *, metadata: dict[str, Any] | None = None
    ) -> list[DocumentChunk]:
        meta = dict(metadata or {})
        pieces = _recursive_split(text, self.chunk_size)
        if self.overlap and len(pieces) > 1:
            pieces = _apply_overlap(pieces, self.overlap)
        return [
            DocumentChunk(
                id=_chunk_id(piece, i),
                text=piece,
                metadata={**meta, "chunk_index": i},
            )
            for i, piece in enumerate(pieces)
            if piece.strip()
        ]


def _recursive_split(text: str, chunk_size: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text else []
    for sep in ("\n\n", "\n", ". ", " "):
        if sep in text:
            parts = text.split(sep)
            acc: list[str] = []
            buf = ""
            for part in parts:
                candidate = part if not buf else buf + sep + part
                if len(candidate) <= chunk_size:
                    buf = candidate
                else:
                    if buf:
                        acc.extend(_recursive_split(buf, chunk_size))
                    buf = part
            if buf:
                acc.extend(_recursive_split(buf, chunk_size))
            return acc
    return chunk_text(text, chunk_size=chunk_size, overlap=0)


def _apply_overlap(pieces: list[str], overlap: int) -> list[str]:
    if overlap <= 0 or len(pieces) < 2:
        return pieces
    out = [pieces[0]]
    for prev, cur in zip(pieces, pieces[1:]):
        prefix = prev[-overlap:] if len(prev) > overlap else prev
        out.append(prefix + cur)
    return out


class SemanticChunker:
    """Split where adjacent sentence embeddings drop below a similarity floor.

    Needs an embeddings object with ``async embed(texts) -> list[list[float]]``.
    Falls back to ``RecursiveChunker`` if embeddings are missing.
    """

    def __init__(
        self,
        embeddings: Any = None,
        *,
        chunk_size: int = 512,
        overlap: int = 64,
        threshold: float = 0.35,
    ):
        self.embeddings = embeddings
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.threshold = threshold

    async def chunk(
        self, text: str, *, metadata: dict[str, Any] | None = None
    ) -> list[DocumentChunk]:
        if self.embeddings is None:
            return await RecursiveChunker(
                chunk_size=self.chunk_size, overlap=self.overlap
            ).chunk(text, metadata=metadata)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if len(sentences) <= 1:
            return await FixedChunker(
                chunk_size=self.chunk_size, overlap=self.overlap
            ).chunk(text, metadata=metadata)
        vectors = await self.embeddings.embed(sentences)
        groups: list[list[str]] = [[sentences[0]]]
        for i in range(1, len(sentences)):
            sim = _cosine(vectors[i - 1], vectors[i])
            if sim < self.threshold or sum(len(s) for s in groups[-1]) >= self.chunk_size:
                groups.append([sentences[i]])
            else:
                groups[-1].append(sentences[i])
        meta = dict(metadata or {})
        out: list[DocumentChunk] = []
        for i, group in enumerate(groups):
            piece = " ".join(group)
            out.append(
                DocumentChunk(
                    id=_chunk_id(piece, i),
                    text=piece,
                    metadata={**meta, "chunk_index": i},
                )
            )
        return out


class ContextualChunker:
    """Wrap another chunker and prepend a short context string to each chunk text.

    The context comes from ``metadata['context']`` when present; otherwise the
    first 200 characters of the source document. Generating a model-written
    summary is the caller's job (opt-in LLM cost).
    """

    def __init__(self, inner: Any, *, context: Optional[str] = None):
        self.inner = inner
        self.context = context

    async def chunk(
        self, text: str, *, metadata: dict[str, Any] | None = None
    ) -> list[DocumentChunk]:
        meta = dict(metadata or {})
        ctx = self.context or meta.get("context") or text[:200].strip()
        chunks = await self.inner.chunk(text, metadata=meta)
        if not ctx:
            return chunks
        prefix = f"Context: {ctx}\n\n"
        for chunk in chunks:
            chunk.text = prefix + chunk.text
            chunk.metadata["contextual"] = True
        return chunks


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(x * x for x in b) ** 0.5 or 1.0
    return dot / (na * nb)


def build_chunker(
    strategy: str,
    *,
    chunk_size: int = 512,
    overlap: int = 64,
    contextual: bool = False,
    embeddings: Any = None,
    context: Optional[str] = None,
) -> Any:
    """Factory used by RAG providers."""
    if strategy == "none":
        inner: Any = _IdentityChunker()
    elif strategy == "recursive":
        inner = RecursiveChunker(chunk_size=chunk_size, overlap=overlap)
    elif strategy == "semantic":
        inner = SemanticChunker(
            embeddings, chunk_size=chunk_size, overlap=overlap
        )
    else:
        inner = FixedChunker(chunk_size=chunk_size, overlap=overlap)
    if contextual:
        return ContextualChunker(inner, context=context)
    return inner


class _IdentityChunker:
    async def chunk(
        self, text: str, *, metadata: dict[str, Any] | None = None
    ) -> list[DocumentChunk]:
        if not text:
            return []
        return [
            DocumentChunk(
                id=_chunk_id(text, 0),
                text=text,
                metadata=dict(metadata or {}),
            )
        ]
