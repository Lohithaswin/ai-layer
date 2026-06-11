from __future__ import annotations
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import ROLE_ATTR_DIR
from src.ingest_batch import ingest_batch

def main():
    if not ROLE_ATTR_DIR or not ROLE_ATTR_DIR.exists():
        print(f"Directory not found: {ROLE_ATTR_DIR}")
        return

    # Find all Excel and Word files in ROLE_ATTR_DIR
    files = []
    for ext in ["*.xlsx", "*.docx"]:
        files.extend(list(ROLE_ATTR_DIR.rglob(ext)))

    if not files:
        print("No Excel or Word files found.")
        return

    print(f"Found {len(files)} files to ingest.")
    for f in files:
        print(f" - {f.name}")

    # Ingest the files without truncating the database
    stats = ingest_batch(files, truncate=False)
    
    print(f"\nIngestion complete:")
    print(f"  Successful: {stats['successful']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Total chunks: {stats['total_chunks']}")
    
    if stats["errors"]:
        print("Errors:")
        for error in stats["errors"]:
            print(f"  - {error}")

if __name__ == "__main__":
    main()
