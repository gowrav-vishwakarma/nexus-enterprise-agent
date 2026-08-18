"""Deterministic hashing embeddings for tests and the in-memory RAG provider."""

from __future__ import annotations

import hashlib


class HashingEmbeddings:
    """Bag-of-words hashing trick. No model download; stable within a process."""

    def __init__(self, dim: int = 64):
        if dim < 8:
            raise ValueError("HashingEmbeddings dim must be at least 8")
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            tokens = text.lower().split()
            if not tokens:
                out.append(vec)
                continue
            for tok in tokens:
                digest = hashlib.md5(tok.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dim
                vec[idx] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out
