from __future__ import annotations

import pandas as pd
from pathlib import Path

from src.config import DOCS_DIR, CHILD_CHUNK_SIZE, CHILD_CHUNK_OVERLAP, PARENT_MAX_CHARS
from src.pdf_loader import _split_child_chunks, _build_child_parent_text

def load_excel_chunks(file_path: Path, metadata: dict | None = None) -> list[dict]:
    """
    Load Excel sheets and convert rows into chunks for RAG.
    Each row is formatted as a text string with column names.
    """
    try:
        rel_path = str(file_path.relative_to(DOCS_DIR.parent))
    except Exception:
        try:
            rel_path = str(file_path.relative_to(file_path.parents[1]))
        except Exception:
            rel_path = file_path.name
    rel_path = rel_path.replace("\\", "/")

    chunks: list[dict] = []
    chunk_index = 0

    try:
        # Load all sheets
        xls = pd.ExcelFile(file_path)
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            
            # Drop completely empty rows or columns
            df.dropna(how="all", inplace=True)
            df.dropna(axis=1, how="all", inplace=True)
            
            # Fill NaNs with empty string
            df.fillna("", inplace=True)
            
            page_text_lines = [f"Sheet: {sheet_name}"]
            
            for idx, row in df.iterrows():
                row_parts = []
                for col in df.columns:
                    val = str(row[col]).strip()
                    if val:
                        # Skip Unnamed columns that pandas adds for blank headers
                        col_str = str(col).strip()
                        if col_str.startswith("Unnamed:"):
                            continue
                        row_parts.append(f"{col_str} is '{val}'")
                
                if row_parts:
                    row_text = "Item details: " + ", ".join(row_parts) + "."
                    page_text_lines.append(row_text)
                    
            page_text = "\n".join(page_text_lines)
            
            if not page_text.strip():
                continue

            # We treat each sheet as a "page"
            parent_id = f"{rel_path}|{sheet_name}"
            
            for piece, start, end in _split_child_chunks(
                page_text, CHILD_CHUNK_SIZE, CHILD_CHUNK_OVERLAP
            ):
                row_dict = {
                    "text": piece,
                    "parent_text": _build_child_parent_text(
                        page_text, start, end, PARENT_MAX_CHARS
                    ),
                    "parent_id": parent_id,
                    "source_file": rel_path,
                    "page": 1,
                    "chunk_index": chunk_index,
                    "section_title": f"Sheet: {sheet_name}",
                }
                if metadata:
                    row_dict.update(metadata)
                chunks.append(row_dict)
                chunk_index += 1
                
    except Exception as e:
        print(f"Error reading Excel {file_path}: {e}")

    return chunks
