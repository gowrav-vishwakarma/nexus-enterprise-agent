"""Reciprocal Rank Fusion for hybrid retrieval."""

from __future__ import annotations

from nexus.rag.protocol import DocumentChunk


def reciprocal_rank_fusion(
    ranked_lists: list[list[DocumentChunk]],
    *,
    k: int = 60,
    top_n: int = 50,
) -> list[DocumentChunk]:
    """Merge ranked chunk lists with Reciprocal Rank Fusion (constant ``k``)."""
    scores: dict[str, float] = {}
    list_counts: dict[str, int] = {}
    by_id: dict[str, DocumentChunk] = {}
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            by_id[chunk.id] = chunk
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (k + rank)
            list_counts[chunk.id] = list_counts.get(chunk.id, 0) + 1
    ordered = sorted(
        scores,
        key=lambda cid: (scores[cid], list_counts.get(cid, 0)),
        reverse=True,
    )
    return [by_id[cid] for cid in ordered[:top_n]]
