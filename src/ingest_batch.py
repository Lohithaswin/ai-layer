"""Enhanced batch ingestion with parallel processing and incremental updates."""

from __future__ import annotations

import sys
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from src.config import DOCS_DIR
from src.document_manager import DocumentManager
from src.pdf_loader import load_pdf_chunks
from src.vector_store import VectorStore, reset_vector_store


def load_single_pdf(pdf_path: Path) -> tuple[Path, list[dict], str | None]:
    """Load a single PDF, return (path, chunks, error_msg)."""
    from src.doc_registry import classify_pdf, attach_metadata
    try:
        meta = classify_pdf(pdf_path)
        chunks = load_pdf_chunks(pdf_path)
        chunks = attach_metadata(chunks, meta)
        return pdf_path, chunks, None
    except Exception as e:
        return pdf_path, [], str(e)


def ingest_batch(
    pdf_paths: list[Path],
    max_workers: int | None = None,
    show_progress: bool = True,
    truncate: bool = False,
) -> dict:
    """
    Ingest multiple PDFs in parallel.
    
    Args:
        pdf_paths: List of PDF file paths
        max_workers: Number of parallel workers
        show_progress: Whether to print progress
        truncate: Whether to truncate the database first
        
    Returns:
        Dictionary with ingestion stats
    """
    stats = {
        "total_pdfs": len(pdf_paths),
        "successful": 0,
        "failed": 0,
        "total_chunks": 0,
        "errors": [],
    }
    
    if not pdf_paths:
        return stats
        
    if max_workers is None:
        max_workers = os.cpu_count() or 4
    
    if show_progress:
        print(f"Ingesting {len(pdf_paths)} PDFs with {max_workers} workers...")
    
    all_chunks = []
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(load_single_pdf, pdf_path): pdf_path
            for pdf_path in pdf_paths
        }
        
        for future in as_completed(futures):
            pdf_path, chunks, error = future.result()
            
            if error:
                stats["failed"] += 1
                stats["errors"].append(f"{pdf_path.name}: {error}")
                if show_progress:
                    print(f"  [FAIL] {pdf_path.name} ({error})")
            else:
                stats["successful"] += 1
                stats["total_chunks"] += len(chunks)
                all_chunks.extend(chunks)
                if show_progress:
                    print(f"  [OK] {pdf_path.name} ({len(chunks)} chunks)")
    
    # Batch embed all chunks
    if all_chunks:
        if show_progress:
            print(f"Upserting {len(all_chunks)} chunks into Database...")
        reset_vector_store()
        store = VectorStore()
        n = store.upsert_chunks(all_chunks, truncate=truncate)
        stats["indexed_chunks"] = n
        if show_progress:
            print(f"Indexed {n} chunks into Database.")
    
    return stats


def main_incremental(workers: int | None = None) -> None:
    """Ingest only new/changed PDFs (incremental mode)."""
    print(f"Loading PDFs from multiple sources...")
    
    manager = DocumentManager(
        local_docs_dir=DOCS_DIR,
        use_mocks=False,  # Set to True for testing without real SharePoint/Artifactory
    )
    
    # 1. Sync deletions (documents in cache but no longer in active docs listing)
    all_docs = manager.list_all_pdfs()
    all_current_keys = {f"{doc.source_type}:{doc.source_file}" for doc in all_docs}
    
    deleted_keys = []
    for key in list(manager.index.indexed_documents.keys()):
        if key not in all_current_keys:
            deleted_keys.append(key)
            
    if deleted_keys:
        print(f"Removing {len(deleted_keys)} deleted documents from Database and Cache...")
        store = VectorStore()
        conn = store._get_connection()
        try:
            with conn.cursor() as cur:
                for key in deleted_keys:
                    parts = key.split(":", 1)
                    if len(parts) == 2:
                        source_file = parts[1]
                        print(f"  - {source_file}")
                        cur.execute("DELETE FROM documents WHERE source_file = %s;", (source_file,))
                        manager.index.remove_by_key(key)
            conn.commit()
        finally:
            conn.close()
        manager.index.save()
    
    # 2. Find PDFs that need indexing
    to_ingest = manager.list_new_or_changed_pdfs()
    
    if not to_ingest:
        print("All documents are up to date. No indexing needed.")
        return
    
    print(f"Found {len(to_ingest)} new/changed PDFs to index:")
    for doc in to_ingest:
        print(f"  - {doc.name} ({doc.source_type})")
    
    # Extract local paths (for now, only local docs)
    local_paths = [Path(doc.path) for doc in to_ingest if doc.source_type == "Local"]
    
    if local_paths:
        stats = ingest_batch(local_paths, max_workers=workers, truncate=False)
        print(f"\nIngestion complete:")
        print(f"  Successful: {stats['successful']}")
        print(f"  Failed: {stats['failed']}")
        print(f"  Total chunks: {stats['total_chunks']}")
        
        if stats["errors"]:
            print("Errors:")
            for error in stats["errors"]:
                print(f"  - {error}")
        
        # Mark documents as indexed with actual page counts
        for doc in to_ingest:
            if doc.source_type == "Local":
                page_count = 1
                try:
                    import fitz
                    d = fitz.open(doc.path)
                    page_count = len(d)
                    d.close()
                except Exception:
                    pass
                manager.mark_ingested(doc, page_count=page_count)
        
        if stats["failed"] > 0:
            sys.exit(1)


def main_full_reindex(workers: int | None = None) -> None:
    """Full reindex of all PDFs (replaces old index)."""
    print(f"Loading all PDFs from: {DOCS_DIR.resolve()}")
    
    pdfs = sorted(DOCS_DIR.rglob("*.pdf"))
    
    if not pdfs:
        print(f"No PDF files found in {DOCS_DIR}")
        sys.exit(1)
    
    print(f"Found {len(pdfs)} PDFs")
    
    # Clear the persisted index cache
    manager = DocumentManager(local_docs_dir=DOCS_DIR)
    manager.index.indexed_documents = {}
    manager.index.save()
    
    stats = ingest_batch(pdfs, max_workers=workers, truncate=True)
    
    print(f"\nFull reindex complete:")
    print(f"  Total PDFs: {stats['total_pdfs']}")
    print(f"  Successful: {stats['successful']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Total chunks: {stats['total_chunks']}")
    
    if stats["errors"]:
        print("Errors:")
        for error in stats["errors"]:
            print(f"  - {error}")
            
    # Mark all PDFs as indexed
    all_current_docs = manager.list_all_pdfs()
    for doc in all_current_docs:
        if doc.source_type == "Local" and Path(doc.path).exists():
            # compute hash
            with open(doc.path, "rb") as f:
                content_hash = hashlib.sha256(f.read()).hexdigest()
            doc.content_hash = content_hash
            
            page_count = 1
            try:
                import fitz
                d = fitz.open(doc.path)
                page_count = len(d)
                d.close()
            except Exception:
                pass
            manager.mark_ingested(doc, page_count=page_count)
    
    if stats["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    import hashlib
    
    parser = argparse.ArgumentParser(description="PDF batch ingestion")
    parser.add_argument(
        "--mode",
        choices=["full", "incremental"],
        default="incremental",
        help="Ingest mode: full reindex or incremental (default: incremental)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)",
    )
    
    args = parser.parse_args()
    
    if args.mode == "full":
        main_full_reindex(workers=args.workers)
    else:
        main_incremental(workers=args.workers)
