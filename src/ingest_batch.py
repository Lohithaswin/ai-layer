"""Enhanced batch ingestion with parallel processing and incremental updates."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.config import DOCS_DIR
from src.document_manager import DocumentManager
from src.pdf_loader import load_pdf_chunks
from src.vector_store import VectorStore, reset_vector_store


def ingest_batch(
    pdf_paths: list[Path],
    max_workers: int = 4,
    show_progress: bool = True,
) -> dict:
    """
    Ingest multiple PDFs in parallel.
    
    Args:
        pdf_paths: List of PDF file paths
        max_workers: Number of parallel workers
        show_progress: Whether to print progress
        
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
    
    def load_single_pdf(pdf_path: Path) -> tuple[Path, list[dict], str | None]:
        """Load a single PDF, return (path, chunks, error_msg)."""
        try:
            chunks = load_pdf_chunks(pdf_path)
            return pdf_path, chunks, None
        except Exception as e:
            return pdf_path, [], str(e)
    
    if show_progress:
        print(f"Ingesting {len(pdf_paths)} PDFs with {max_workers} workers...")
    
    all_chunks = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
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
                    print(f"  ✗ {pdf_path.name} ({error})")
            else:
                stats["successful"] += 1
                stats["total_chunks"] += len(chunks)
                all_chunks.extend(chunks)
                if show_progress:
                    print(f"  ✓ {pdf_path.name} ({len(chunks)} chunks)")
    
    # Batch embed all chunks
    if all_chunks:
        if show_progress:
            print(f"Upserting {len(all_chunks)} chunks into ChromaDB...")
        reset_vector_store()
        store = VectorStore()
        n = store.upsert_chunks(all_chunks)
        stats["indexed_chunks"] = n
        if show_progress:
            print(f"Indexed {n} chunks into ChromaDB.")
    
    return stats


def main_incremental() -> None:
    """Ingest only new/changed PDFs (incremental mode)."""
    print(f"Loading PDFs from multiple sources...")
    
    manager = DocumentManager(
        local_docs_dir=DOCS_DIR,
        use_mocks=False,  # Set to True for testing without real SharePoint/Artifactory
    )
    
    # Find PDFs that need indexing
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
        stats = ingest_batch(local_paths, max_workers=4)
        print(f"\nIngestion complete:")
        print(f"  Successful: {stats['successful']}")
        print(f"  Failed: {stats['failed']}")
        print(f"  Total chunks: {stats['total_chunks']}")
        
        if stats["errors"]:
            print("Errors:")
            for error in stats["errors"]:
                print(f"  - {error}")
        
        # Mark documents as indexed
        for doc in to_ingest:
            if doc.source_type == "Local":
                manager.mark_ingested(doc, page_count=1)  # TODO: Extract actual page count
        
        if stats["failed"] > 0:
            sys.exit(1)


def main_full_reindex() -> None:
    """Full reindex of all PDFs (replaces old index)."""
    print(f"Loading all PDFs from: {DOCS_DIR.resolve()}")
    
    pdfs = sorted(DOCS_DIR.glob("*.pdf"))
    
    if not pdfs:
        print(f"No PDF files found in {DOCS_DIR}")
        sys.exit(1)
    
    print(f"Found {len(pdfs)} PDFs")
    stats = ingest_batch(pdfs, max_workers=4)
    
    print(f"\nFull reindex complete:")
    print(f"  Total PDFs: {stats['total_pdfs']}")
    print(f"  Successful: {stats['successful']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Total chunks: {stats['total_chunks']}")
    
    if stats["errors"]:
        print("Errors:")
        for error in stats["errors"]:
            print(f"  - {error}")
    
    if stats["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    
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
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    
    args = parser.parse_args()
    
    if args.mode == "full":
        main_full_reindex()
    else:
        main_incremental()
