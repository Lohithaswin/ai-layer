"""BM25 sparse index delegator to PostgreSQL Full-Text Search (FTS)."""

from __future__ import annotations

from typing import Any

class BM25Store:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    @property
    def size(self) -> int:
        from src.vector_store import get_vector_store
        try:
            return get_vector_store().count
        except Exception:
            return 0

    def build(self, records: list[dict[str, Any]]) -> None:
        """No-op: Chunks are now indexed during upsert_chunks in PostgreSQLStore."""
        pass

    def search(
        self,
        query: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Delegate search to PostgreSQL FTS."""
        from src.vector_store import get_vector_store
        store = get_vector_store()
        return store.search_sparse(query, top_k=top_k, filters=filters)

    def save(self, path: Any | None = None) -> None:
        """No-op: Handled automatically by database."""
        pass

    def load(self, path: Any | None = None) -> bool:
        """No-op: Handled automatically by database."""
        return True


_bm25_instance: BM25Store | None = None


def get_bm25_store() -> BM25Store:
    global _bm25_instance
    if _bm25_instance is None:
        _bm25_instance = BM25Store()
    return _bm25_instance


def reset_bm25_store() -> None:
    global _bm25_instance
    _bm25_instance = None
