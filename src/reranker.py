"""Cross-encoder re-ranking for retrieved candidates."""

from __future__ import annotations

from typing import Any

from src.config import RERANKER_MODEL, USE_RERANKER

_reranker_instance = None


def get_reranker():
    global _reranker_instance
    if _reranker_instance is None:
        from sentence_transformers import CrossEncoder

        _reranker_instance = CrossEncoder(RERANKER_MODEL, max_length=512)
    return _reranker_instance


def rerank(
    question: str,
    candidates: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Re-score candidates using cross-encoder; prefer parent_text for context."""
    if not USE_RERANKER or not candidates:
        return candidates[:top_k]

    pairs = []
    for c in candidates:
        passage = c.get("parent_text") or c.get("text", "")
        pairs.append((question, passage[:2000]))

    model = get_reranker()
    scores = model.predict(pairs)

    raw = [float(s) for s in scores]
    lo, hi = min(raw), max(raw)
    span = hi - lo if hi > lo else 1.0

    for c, score in zip(candidates, raw):
        c["rerank_score"] = score
        c["relevance"] = (score - lo) / span
        c["score"] = c["relevance"]

    ranked = sorted(candidates, key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]
