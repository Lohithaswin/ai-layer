"""Index all PDFs in docs/ into the local vector store."""

from __future__ import annotations

import sys

from src.config import DOCS_DIR
from src.pdf_loader import load_all_pdfs
from src.vector_store import VectorStore, reset_vector_store


def main() -> None:
    print(f"Loading files from: {DOCS_DIR.resolve()}")
    
    store = VectorStore()
    indexed_files = store.get_indexed_files()
    
    try:
        chunks = load_all_pdfs(DOCS_DIR, indexed_files=indexed_files)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    if not chunks:
        print("0 files updated. All documents are up-to-date!")
        return

    products: dict[str, int] = {}
    demos = 0
    for c in chunks:
        products[c.get("product", "unknown")] = products.get(c.get("product", "unknown"), 0) + 1
        if c.get("is_demo"):
            demos += 1
    print(f"Parsed {len(chunks)} chunks.")
    print(f"  By product: {dict(products)}  |  demo chunks: {demos}")
    
    n = store.upsert_chunks(chunks, truncate=False)
    print(f"Indexed {n} chunks into ChromaDB. Ready to chat.")


if __name__ == "__main__":
    main()
