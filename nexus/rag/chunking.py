"""Text chunking utilities."""

from __future__ import annotations


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
