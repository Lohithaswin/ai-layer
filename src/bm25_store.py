"""BM25 sparse index for lexical / acronym matching (hybrid search)."""

from __future__ import annotations

import pickle
import re
from typing import Any

from rank_bm25 import BM25Okapi

from src.config import BM25_PATH


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


class BM25Store:
    def __init__(self) -> None:
        self._bm25: BM25Okapi | None = None
        self._records: list[dict[str, Any]] = []

    @property
    def size(self) -> int:
        return len(self._records)

    def build(self, records: list[dict[str, Any]]) -> None:
        """Build index from chunk records (uses child `text` field)."""
        self._records = records
        if not records:
            self._bm25 = None
            return
        corpus = [_tokenize(r["text"]) for r in records]
        self._bm25 = BM25Okapi(corpus)

    def _matches_filters(self, rec: dict, filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True
        for key, value in filters.items():
            if rec.get(key) != value:
                return False
        return True

    def search(
        self,
        query: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._bm25 or not self._records:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []

        indices = [
            i
            for i, rec in enumerate(self._records)
            if self._matches_filters(rec, filters)
        ]
        if not indices:
            return []

        all_scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            [(self._records[i], all_scores[i]) for i in indices],
            key=lambda x: x[1],
            reverse=True,
        )[: top_k * 2]

        hits: list[dict[str, Any]] = []
        max_score = ranked[0][1] if ranked and ranked[0][1] > 0 else 1.0
        for rec, raw in ranked:
            if raw <= 0:
                continue
            hits.append(
                {
                    **rec,
                    "score": float(raw / max_score),
                    "sparse_score": float(raw),
                }
            )
            if len(hits) >= top_k:
                break
        return hits

    def save(self, path: BM25_PATH | None = None) -> None:
        path = path or BM25_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"records": self._records, "bm25": self._bm25}, f)

    def load(self, path: BM25_PATH | None = None) -> bool:
        path = path or BM25_PATH
        if not path.exists():
            return False
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._records = data.get("records", [])
        self._bm25 = data.get("bm25")
        return bool(self._records and self._bm25)


_bm25_instance: BM25Store | None = None


def get_bm25_store() -> BM25Store:
    global _bm25_instance
    if _bm25_instance is None:
        _bm25_instance = BM25Store()
        _bm25_instance.load()
    return _bm25_instance


def reset_bm25_store() -> None:
    global _bm25_instance
    _bm25_instance = None
