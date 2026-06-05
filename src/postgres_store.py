"""PostgreSQL dense index (pgvector) + sparse index (FTS) for hybrid search."""

from __future__ import annotations

import os
import hashlib
import re
from typing import Any
import psycopg2
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer

from src.config import EMBEDDING_MODEL, TOP_K

# Read database credentials from environment variables
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DB = os.getenv("PG_DB", "rag_db")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "password")


class PostgreSQLStore:
    def __init__(self) -> None:
        self._embedder = SentenceTransformer(EMBEDDING_MODEL)
        # Ensure database and tables are created
        self._init_db()

    def _get_connection(self):
        try:
            return psycopg2.connect(
                host=PG_HOST,
                port=PG_PORT,
                database=PG_DB,
                user=PG_USER,
                password=PG_PASSWORD
            )
        except psycopg2.OperationalError as e:
            raise RuntimeError(
                f"Could not connect to PostgreSQL database on {PG_HOST}:{PG_PORT}.\n"
                f"Please ensure your PostgreSQL Rancher Desktop container is running by executing:\n"
                f"  docker compose up -d\n"
                f"Error details: {e}"
            ) from e

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # 1. Enable pgvector extension
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                
                # 2. Create documents table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id SERIAL PRIMARY KEY,
                        source_file VARCHAR(512) UNIQUE NOT NULL,
                        product VARCHAR(64) NOT NULL,
                        doc_type VARCHAR(64) NOT NULL,
                        is_demo BOOLEAN DEFAULT FALSE,
                        manual_version VARCHAR(64)
                    );
                """)
                
                # 3. Create document_chunks table
                # Dimension of sentence-transformers/all-MiniLM-L6-v2 is 384
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS document_chunks (
                        id VARCHAR(256) PRIMARY KEY,
                        document_id INT REFERENCES documents(id) ON DELETE CASCADE,
                        page INT NOT NULL,
                        chunk_index INT NOT NULL,
                        text TEXT NOT NULL,
                        parent_text TEXT,
                        section_title VARCHAR(256),
                        embedding VECTOR(384),
                        tsv_content tsvector
                    );
                """)
                
                # 4. Create indices for speed and scalability
                cur.execute("CREATE INDEX IF NOT EXISTS idx_docs_metadata ON documents (product, doc_type, is_demo);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_page ON document_chunks (document_id, page);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_fts ON document_chunks USING gin (tsv_content);")
                
            conn.commit()
        finally:
            conn.close()

    def _chunk_id(
        self,
        source_file: str,
        page: int,
        chunk_index: int,
    ) -> str:
        raw = f"{source_file}|{page}|{chunk_index}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def upsert_chunks(self, chunks: list[dict], truncate: bool = True) -> int:
        if not chunks:
            return 0

        # Classify unique documents to minimize insert redundancy
        unique_docs = {}
        for c in chunks:
            sf = c["source_file"]
            if sf not in unique_docs:
                unique_docs[sf] = {
                    "source_file": sf,
                    "product": c.get("product", "unknown"),
                    "doc_type": c.get("doc_type", "unknown"),
                    "is_demo": bool(c.get("is_demo", False)),
                    "manual_version": c.get("manual_version")
                }

        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                if truncate:
                    # Truncate tables first (clean state)
                    cur.execute("TRUNCATE TABLE documents CASCADE;")
                else:
                    # Delete existing entries for the documents we are about to upsert
                    for sf in unique_docs.keys():
                        cur.execute("DELETE FROM documents WHERE source_file = %s;", (sf,))
            conn.commit()
        finally:
            conn.close()

        # 2. Insert unique documents and map source_file -> id
        conn = self._get_connection()
        doc_ids = {}
        try:
            with conn.cursor() as cur:
                for sf, d in unique_docs.items():
                    cur.execute("""
                        INSERT INTO documents (source_file, product, doc_type, is_demo, manual_version)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id;
                    """, (sf, d["product"], d["doc_type"], d["is_demo"], d["manual_version"]))
                    doc_ids[sf] = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        # 3. Batch process chunks (e.g. 5000 at a time) to prevent RAM exhaustion (OOM)
        SUB_BATCH_SIZE = 5000
        total_inserted = 0
        
        for start_idx in range(0, len(chunks), SUB_BATCH_SIZE):
            end_idx = min(start_idx + SUB_BATCH_SIZE, len(chunks))
            sub_chunks = chunks[start_idx:end_idx]
            
            # Embed this sub-batch
            sub_texts = [c["text"] for c in sub_chunks]
            print(f"Generating embeddings for sub-batch {start_idx}-{end_idx} of {len(chunks)}...")
            sub_embeddings = self._embedder.encode(
                sub_texts, show_progress_bar=False
            ).tolist()
            
            # Prepare rows
            chunk_rows = []
            for idx, c in enumerate(sub_chunks):
                sf = c["source_file"]
                doc_id = doc_ids[sf]
                cid = self._chunk_id(sf, c["page"], c["chunk_index"])
                parent_text = (c.get("parent_text") or c["text"])[:4000]
                emb = sub_embeddings[idx]
                
                chunk_rows.append((
                    cid,
                    doc_id,
                    c["page"],
                    c["chunk_index"],
                    c["text"],
                    parent_text,
                    c.get("section_title"),
                    emb,
                    c["text"]  # passed a second time for to_tsvector in the template
                ))
            
            # Insert this sub-batch
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    execute_values(
                        cur,
                        """
                        INSERT INTO document_chunks (id, document_id, page, chunk_index, text, parent_text, section_title, embedding, tsv_content)
                        VALUES %s
                        """,
                        chunk_rows,
                        template="(%s, %s, %s, %s, %s, %s, %s, %s, to_tsvector('english', coalesce(%s, '')))"
                    )
                conn.commit()
                total_inserted += len(sub_chunks)
                print(f"Successfully inserted {total_inserted}/{len(chunks)} chunks.")
            finally:
                conn.close()

        print("PostgreSQL indexing complete.")
        return len(chunks)

    def _parse_where_clause(self, where: dict | None) -> tuple[str, list[Any]]:
        if not where:
            return "", []

        clauses = []
        params = []

        def process_node(node: dict):
            if "$and" in node:
                for child in node["$and"]:
                    process_node(child)
            else:
                for key, val in node.items():
                    if isinstance(val, dict):
                        op = list(val.keys())[0]
                        target_val = val[op]
                        if op == "$eq":
                            col = f"d.{key}" if key in ("product", "doc_type", "is_demo", "source_file") else f"c.{key}"
                            clauses.append(f"{col} = %s")
                            params.append(target_val)
                        elif op == "$lte":
                            col = f"d.{key}" if key in ("product", "doc_type", "is_demo", "source_file") else f"c.{key}"
                            clauses.append(f"{col} <= %s")
                            params.append(target_val)
                    else:
                        col = f"d.{key}" if key in ("product", "doc_type", "is_demo", "source_file") else f"c.{key}"
                        clauses.append(f"{col} = %s")
                        params.append(val)

        process_node(where)
        if not clauses:
            return "", []

        return " AND " + " AND ".join(clauses), params

    def search(
        self,
        query: str,
        top_k: int = TOP_K,
        where: dict | None = None,
    ) -> list[dict[str, Any]]:
        query_embedding = self._embedder.encode([query]).tolist()[0]
        
        filter_sql, filter_params = self._parse_where_clause(where)
        sql = f"""
            SELECT c.text, c.parent_text, c.page, c.chunk_index, c.section_title,
                   d.source_file, d.product, d.doc_type, d.is_demo,
                   1 - (c.embedding <=> %s::vector) AS score
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE 1=1 {filter_sql}
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s;
        """
        
        # Parameters: [embedding, *filters, embedding, limit]
        params = [query_embedding] + filter_params + [query_embedding, top_k]
        
        conn = self._get_connection()
        hits = []
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                for row in cur.fetchall():
                    text, parent_text, page, chunk_index, section_title, source_file, product, doc_type, is_demo, score = row
                    hits.append({
                        "text": text,
                        "parent_text": parent_text,
                        "parent_id": f"{source_file}|{page}",
                        "source_file": source_file,
                        "page": page,
                        "chunk_index": chunk_index,
                        "section_title": section_title,
                        "product": product,
                        "doc_type": doc_type,
                        "is_demo": is_demo,
                        "score": score
                    })
        finally:
            conn.close()
        return hits

    def batch_search(
        self,
        queries: list[str],
        top_k: int = TOP_K,
        where: dict | None = None,
    ) -> list[list[dict[str, Any]]]:
        # Return empty list of hits for each query if no queries
        if not queries:
            return []
            
        # Call single search inside a loop (Postgres connection is pooled/fast enough)
        # To avoid multiple connections, we can reuse one connection
        conn = self._get_connection()
        batch_hits = []
        try:
            query_embeddings = self._embedder.encode(queries).tolist()
            filter_sql, filter_params = self._parse_where_clause(where)
            
            sql = f"""
                SELECT c.text, c.parent_text, c.page, c.chunk_index, c.section_title,
                       d.source_file, d.product, d.doc_type, d.is_demo,
                       1 - (c.embedding <=> %s::vector) AS score
                FROM document_chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE 1=1 {filter_sql}
                ORDER BY c.embedding <=> %s::vector
                LIMIT %s;
            """
            
            with conn.cursor() as cur:
                for q_emb in query_embeddings:
                    params = [q_emb] + filter_params + [q_emb, top_k]
                    cur.execute(sql, params)
                    hits = []
                    for row in cur.fetchall():
                        text, parent_text, page, chunk_index, section_title, source_file, product, doc_type, is_demo, score = row
                        hits.append({
                            "text": text,
                            "parent_text": parent_text,
                            "parent_id": f"{source_file}|{page}",
                            "source_file": source_file,
                            "page": page,
                            "chunk_index": chunk_index,
                            "section_title": section_title,
                            "product": product,
                            "doc_type": doc_type,
                            "is_demo": is_demo,
                            "score": score
                        })
                    batch_hits.append(hits)
        finally:
            conn.close()
        return batch_hits

    def search_sparse(
        self,
        query: str,
        top_k: int = TOP_K,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        # Format filters to standard where dict
        where = None
        if filters:
            where = {"$and": [{k: {"$eq": v}} for k, v in filters.items()]}
            
        filter_sql, filter_params = self._parse_where_clause(where)
        
        # Prepare TSQuery using websearch_to_tsquery for strict AND logic
        # This prevents garbage keyword hits from overwhelming the dense semantic hits in hybrid search.
        ts_query_str = query
        ts_function = "websearch_to_tsquery"
            
        sql = f"""
            SELECT c.text, c.parent_text, c.page, c.chunk_index, c.section_title,
                   d.source_file, d.product, d.doc_type, d.is_demo,
                   ts_rank_cd(c.tsv_content, {ts_function}('english', %s)) AS raw_score
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.tsv_content @@ {ts_function}('english', %s) {filter_sql}
            ORDER BY raw_score DESC
            LIMIT %s;
        """
        
        params = [ts_query_str, ts_query_str] + filter_params + [top_k]
        
        conn = self._get_connection()
        hits = []
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                if not rows:
                    return []
                    
                max_score = max(row[-1] for row in rows) if rows else 1.0
                if max_score <= 0:
                    max_score = 1.0
                    
                for row in rows:
                    text, parent_text, page, chunk_index, section_title, source_file, product, doc_type, is_demo, raw_score = row
                    hits.append({
                        "text": text,
                        "parent_text": parent_text,
                        "parent_id": f"{source_file}|{page}",
                        "source_file": source_file,
                        "page": page,
                        "chunk_index": chunk_index,
                        "section_title": section_title,
                        "product": product,
                        "doc_type": doc_type,
                        "is_demo": is_demo,
                        "score": float(raw_score / max_score),
                        "sparse_score": float(raw_score)
                    })
        finally:
            conn.close()
        return hits

    def search_keyword(
        self,
        term: str,
        top_k: int = 3,
        where: dict | None = None,
    ) -> list[dict[str, Any]]:
        # Substring/LIKE search
        filter_sql, filter_params = self._parse_where_clause(where)
        sql = f"""
            SELECT c.text, c.parent_text, c.page, c.chunk_index, c.section_title,
                   d.source_file, d.product, d.doc_type, d.is_demo
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.text ILIKE %s {filter_sql}
            LIMIT %s;
        """
        params = [f"%{term}%"] + filter_params + [top_k]
        
        conn = self._get_connection()
        hits = []
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                for row in cur.fetchall():
                    text, parent_text, page, chunk_index, section_title, source_file, product, doc_type, is_demo = row
                    hits.append({
                        "text": text,
                        "parent_text": parent_text,
                        "parent_id": f"{source_file}|{page}",
                        "source_file": source_file,
                        "page": page,
                        "chunk_index": chunk_index,
                        "section_title": section_title,
                        "product": product,
                        "doc_type": doc_type,
                        "is_demo": is_demo,
                        "score": 0.85
                    })
        finally:
            conn.close()
        return hits

    def search_early_pages(
        self,
        query: str,
        max_page: int = 3,
        top_k: int = 3,
        where: dict | None = None,
    ) -> list[dict[str, Any]]:
        page_filter = {"page": {"$lte": max_page}}
        combined = {"$and": [where, page_filter]} if where else page_filter
        return self.search(query, top_k=top_k, where=combined)

    def get_chunks_for_page(self, source_file: str, page: int) -> list[dict[str, Any]]:
        sql = """
            SELECT c.text, c.parent_text, c.page, c.chunk_index, c.section_title,
                   d.source_file, d.product, d.doc_type, d.is_demo
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.source_file = %s AND c.page = %s
            ORDER BY c.chunk_index ASC;
        """
        conn = self._get_connection()
        hits = []
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (source_file, page))
                for row in cur.fetchall():
                    text, parent_text, page_val, chunk_index, section_title, source_file_val, product, doc_type, is_demo = row
                    hits.append({
                        "text": text,
                        "parent_text": parent_text,
                        "parent_id": f"{source_file_val}|{page_val}",
                        "source_file": source_file_val,
                        "page": page_val,
                        "chunk_index": chunk_index,
                        "section_title": section_title,
                        "product": product,
                        "doc_type": doc_type,
                        "is_demo": is_demo,
                        "score": 0.85
                    })
        finally:
            conn.close()
        return hits

    @property
    def count(self) -> int:
        sql = "SELECT COUNT(*) FROM document_chunks;"
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchone()[0]
        finally:
            conn.close()

    def get_unique_files(self) -> list[str]:
        sql = "SELECT DISTINCT source_file FROM documents ORDER BY source_file ASC;"
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                return [row[0] for row in cur.fetchall() if row[0]]
        finally:
            conn.close()

    def get_unique_products(self) -> list[str]:
        sql = "SELECT DISTINCT product FROM documents WHERE product NOT IN ('unknown', 'demo') ORDER BY product ASC;"
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                return [row[0] for row in cur.fetchall() if row[0]]
        finally:
            conn.close()
