"""VectorStore delegate routing calls to PostgreSQLStore."""

from __future__ import annotations

from src.postgres_store import PostgreSQLStore
from src.bm25_store import reset_bm25_store

_store_instance: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = VectorStore()
    return _store_instance


def reset_vector_store() -> None:
    global _store_instance
    _store_instance = None
    reset_bm25_store()


class VectorStore(PostgreSQLStore):
    """
    Subclass of PostgreSQLStore that preserves the VectorStore name for 
    seamless backwards compatibility across the ingestion and retrieval codebase.
    """
    pass
