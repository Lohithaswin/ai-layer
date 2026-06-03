"""ChromaDB dense index + BM25 sparse index (hybrid search)."""

from __future__ import annotations

import hashlib
from typing import Any

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from src.bm25_store import get_bm25_store, reset_bm25_store
from src.config import (
    BM25_PATH,
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    TOP_K,
)

_store_instance: "VectorStore | None" = None


def get_vector_store() -> "VectorStore":
    global _store_instance
    if _store_instance is None:
        _store_instance = VectorStore()
    return _store_instance


def reset_vector_store() -> None:
    global _store_instance
    _store_instance = None
    reset_bm25_store()


class VectorStore:
    def __init__(self) -> None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._embedder = SentenceTransformer(EMBEDDING_MODEL)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def _chunk_id(
        self,
        source_file: str,
        page: int,
        chunk_index: int,
    ) -> str:

        raw = (
            f"{source_file}|"
            f"{page}|"
            f"{chunk_index}"
        )

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

    def _meta_row(self, c: dict) -> dict:
        row = {
            "source_file": c["source_file"],
            "page": c["page"],
            "chunk_index": c["chunk_index"],
            "parent_id": c.get("parent_id", f"{c['source_file']}|{c['page']}"),
            "parent_text": (c.get("parent_text") or c["text"])[:4000],
            "product": c.get("product", "unknown"),
            "doc_type": c.get("doc_type", "unknown"),
            "is_demo": bool(c.get("is_demo", False)),
        }
        return row

    def upsert_chunks(self, chunks: list[dict]) -> int:
        if not chunks:
            return 0

        ids = [
            self._chunk_id(c["source_file"], c["page"], c["chunk_index"])
            for c in chunks
        ]
        documents = [c["text"] for c in chunks]
        metadatas = [self._meta_row(c) for c in chunks]
        embeddings = self._embedder.encode(
            documents, show_progress_bar=True
        ).tolist()

        try:
            self._client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        BATCH_SIZE = 5000

        for start in range(0, len(ids), BATCH_SIZE):

            end = start + BATCH_SIZE

            self._collection.add(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
                embeddings=embeddings[start:end],
            )

            print(
                f"Indexed {min(end, len(ids))}/{len(ids)} chunks..."
            )

        bm25_records = [
            {
                "text": c["text"],
                "parent_text": c.get("parent_text") or c["text"],
                "parent_id": c.get("parent_id", ""),
                "source_file": c["source_file"],
                "page": c["page"],
                "chunk_index": c["chunk_index"],
                "product": c.get("product", "unknown"),
                "doc_type": c.get("doc_type", "unknown"),
                "is_demo": c.get("is_demo", False),
            }
            for c in chunks
        ]
        bm25 = get_bm25_store()
        bm25.build(bm25_records)
        bm25.save(BM25_PATH)

        return len(ids)

    def _hit_from_row(self, doc: str, meta: dict, score: float) -> dict[str, Any]:
        return {
            "text": doc,
            "parent_text": meta.get("parent_text") or doc,
            "parent_id": meta.get("parent_id", ""),
            "source_file": meta["source_file"],
            "page": int(meta["page"]),
            "chunk_index": int(meta["chunk_index"]),
            "product": meta.get("product", "unknown"),
            "doc_type": meta.get("doc_type", "unknown"),
            "is_demo": meta.get("is_demo", False),
            "score": score,
        }

    def _parse_results(self, result: dict) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        if not result["documents"] or not result["documents"][0]:
            return hits
        for doc, meta, dist in zip(
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        ):
            hits.append(self._hit_from_row(doc, meta, 1 - dist))
        return hits

    def _bm25_filters(self, where: dict | None) -> dict[str, Any] | None:
        if not where:
            return {"is_demo": False}
        filters: dict[str, Any] = {"is_demo": False}
        if "product" in str(where):
            prod_clause = where
            if "$and" in where:
                for clause in where["$and"]:
                    if "product" in clause:
                        filters["product"] = clause["product"]["$eq"]
            elif where.get("product"):
                filters["product"] = where["product"]["$eq"]
        return filters

    def search(
        self,
        query: str,
        top_k: int = TOP_K,
        where: dict | None = None,
    ) -> list[dict[str, Any]]:
        if self._collection.count() == 0:
            return []

        n = min(top_k, self._collection.count())
        query_embedding = self._embedder.encode([query]).tolist()
        kwargs: dict[str, Any] = {
            "query_embeddings": query_embedding,
            "n_results": n,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        try:
            result = self._collection.query(**kwargs)
        except Exception:
            result = self._collection.query(
                query_embeddings=query_embedding,
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )
        return self._parse_results(result)

    def batch_search(
        self,
        queries: list[str],
        top_k: int = TOP_K,
        where: dict | None = None,
    ) -> list[list[dict[str, Any]]]:
        if not queries or self._collection.count() == 0:
            return [[] for _ in queries]

        n = min(top_k, self._collection.count())
        query_embeddings = self._embedder.encode(queries).tolist()
        kwargs: dict[str, Any] = {
            "query_embeddings": query_embeddings,
            "n_results": n,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        try:
            results = self._collection.query(**kwargs)
        except Exception:
            results = self._collection.query(
                query_embeddings=query_embeddings,
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )

        batch_hits = []
        for i in range(len(queries)):
            hits = []
            if (
                results["documents"]
                and i < len(results["documents"])
                and results["documents"][i]
            ):
                for doc, meta, dist in zip(
                    results["documents"][i],
                    results["metadatas"][i],
                    results["distances"][i],
                ):
                    hits.append(self._hit_from_row(doc, meta, 1 - dist))
            batch_hits.append(hits)
        return batch_hits

    def search_keyword(
        self,
        term: str,
        top_k: int = 3,
        where: dict | None = None,
    ) -> list[dict[str, Any]]:
        if self._collection.count() == 0:
            return []
        try:
            kwargs: dict[str, Any] = {
                "query_embeddings": self._embedder.encode([term]).tolist(),
                "n_results": min(top_k, self._collection.count()),
                "where_document": {"$contains": term},
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                kwargs["where"] = where
            result = self._collection.query(**kwargs)
        except Exception:
            return []
        return self._parse_results(result)

    def search_early_pages(
        self,
        query: str,
        max_page: int = 3,
        top_k: int = 3,
        where: dict | None = None,
    ) -> list[dict[str, Any]]:
        if self._collection.count() == 0:
            return []
        page_filter = {"page": {"$lte": max_page}}
        combined = (
            {"$and": [where, page_filter]} if where else page_filter
        )
        query_embedding = self._embedder.encode([query]).tolist()
        try:
            result = self._collection.query(
                query_embeddings=query_embedding,
                n_results=min(top_k * 3, self._collection.count()),
                where=combined,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []
        hits = self._parse_results(result)
        return hits[:top_k]

    def get_chunks_for_page(self, source_file: str, page: int) -> list[dict[str, Any]]:
        if self._collection.count() == 0:
            return []
        try:
            result = self._collection.get(
                where={
                    "$and": [
                        {"source_file": source_file},
                        {"page": page},
                    ]
                },
                include=["documents", "metadatas"],
            )
        except Exception:
            return []

        hits: list[dict[str, Any]] = []
        for doc, meta in zip(result["documents"], result["metadatas"]):
            hits.append(self._hit_from_row(doc, meta, 0.85))
        return hits

    @property
    def count(self) -> int:
        return self._collection.count()
