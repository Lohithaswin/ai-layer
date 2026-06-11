"""Layout-aware PDF parsing (PyMuPDF) with parent-child chunking."""

from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

from src.config import (
    CHILD_CHUNK_OVERLAP,
    CHILD_CHUNK_SIZE,
    PARENT_MAX_CHARS,
)


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\ufffd", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _split_child_chunks(
    text: str, chunk_size: int, overlap: int
) -> list[tuple[str, int, int]]:
    """Return (chunk_text, start_offset, end_offset) for child-aligned parent windows."""
    text = _normalize_whitespace(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [(text, 0, len(text))]

    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append((text[start:end], start, end))
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def _build_child_parent_text(
    page_text: str, start: int, end: int, max_chars: int
) -> str:
    """
    Parent context centered on the child chunk (not always page top).

    Fixes long pages where the answer (e.g. EnableADLogin) is after the first 1500 chars.
    """
    if len(page_text) <= max_chars:
        return page_text

    mid = (start + end) // 2
    half = max_chars // 2
    win_start = max(0, mid - half)
    win_end = min(len(page_text), win_start + max_chars)
    if win_end - win_start < max_chars:
        win_start = max(0, win_end - max_chars)

    window = page_text[win_start:win_end]
    if win_start > 0:
        window = "[...]\n" + window
    if win_end < len(page_text):
        window = window + "\n[...]"
    return window


def _format_table(table) -> str:
    """Convert a PyMuPDF table to readable text (pipe-separated rows), collapsing empty columns."""
    try:
        rows = table.extract()
    except Exception:
        return ""
    if not rows:
        return ""

    lines: list[str] = []
    for row in rows:
        cells = [str(c or "").strip().replace("\n", " ") for c in row]
        if any(cells):
            row_str = " | ".join(cells)
            # Collapse multiple consecutive pipe separators (caused by empty or merged cells)
            row_str = re.sub(r"(\s*\|\s*){2,}", " | ", row_str).strip(" |")
            if row_str:
                lines.append(row_str)
    if not lines:
        return ""
    return "TABLE:\n" + "\n".join(lines)


def _extract_page_content(page: fitz.Page) -> str:
    """Extract page text with layout blocks and tables, avoiding duplication of table text."""
    parts: list[str] = []

    tables = []
    from src.config import EXTRACT_TABLES
    if EXTRACT_TABLES:
        try:
            finder = page.find_tables()
            tables = finder.tables if hasattr(finder, "tables") else []
        except Exception:
            pass

    def is_in_any_table(bbox) -> bool:
        bx0, by0, bx1, by1 = bbox[:4]
        for table in tables:
            tx0, ty0, tx1, ty1 = table.bbox
            if bx0 >= tx0 - 5 and by0 >= ty0 - 5 and bx1 <= tx1 + 5 and by1 <= ty1 + 5:
                return True
        return False

    blocks = page.get_text("blocks", sort=True)
    for block in blocks:
        if len(block) >= 5 and block[4].strip():
            if not is_in_any_table(block):
                parts.append(block[4].strip())

    for table in tables:
        formatted = _format_table(table)
        if formatted:
            parts.append(formatted)

    if not parts:
        parts.append(page.get_text("text", sort=True) or "")

    return _normalize_whitespace("\n\n".join(parts))


def load_pdf_chunks(pdf_path: Path, metadata: dict | None = None) -> list[dict]:
    """
    Return child chunk dicts for indexing.

    Each record:
      - text: small child chunk (embedded + BM25)
      - parent_text: larger parent block (page-level, for LLM context)
      - parent_id, source_file, page, chunk_index
    """
    doc = fitz.open(str(pdf_path))
    fitz.TOOLS.mupdf_display_errors(False) # Suppress noisy MuPDF structure tree errors
    from src.config import DOCS_DIR
    try:
        rel_path = str(pdf_path.relative_to(DOCS_DIR.parent))
    except Exception:
        try:
            rel_path = str(pdf_path.relative_to(pdf_path.parents[1]))
        except Exception:
            rel_path = pdf_path.name
    rel_path = rel_path.replace("\\", "/") # normalize backslashes on Windows
    chunks: list[dict] = []
    chunk_index = 0

    import re
    _SECTION_RE = re.compile(r"(?:^|\n)\s*((?:\d+(?:\.\d+)*\.?|Appendix\s+[A-Z])\s+[A-Z][^\n]{4,100})", re.I | re.M)
    current_section = None

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = _extract_page_content(page)
            if not page_text:
                continue

            parent_id = f"{rel_path}|{page_num + 1}"

            page_sections = []
            for match in _SECTION_RE.finditer(page_text):
                page_sections.append((match.start(), match.group(1).strip()))

            for piece, start, end in _split_child_chunks(
                page_text, CHILD_CHUNK_SIZE, CHILD_CHUNK_OVERLAP
            ):
                for sec_start, sec_title in page_sections:
                    if sec_start <= start + (CHILD_CHUNK_SIZE // 2):
                        current_section = sec_title

                row = {
                    "text": piece,
                    "parent_text": _build_child_parent_text(
                        page_text, start, end, PARENT_MAX_CHARS
                    ),
                    "parent_id": parent_id,
                    "source_file": rel_path,
                    "page": page_num + 1,
                    "chunk_index": chunk_index,
                    "section_title": current_section,
                }
                if metadata:
                    row.update(metadata)
                chunks.append(row)
                chunk_index += 1
    finally:
        doc.close()

    return chunks


def load_all_pdfs(docs_dir: Path, indexed_files: dict[str, float] = None) -> list[dict]:
    if indexed_files is None:
        indexed_files = {}

    pdfs = sorted(docs_dir.rglob("*.pdf"))
    
    # Also support xlsx and docx ingestion here since we use the same pipeline
    xlsxs = sorted(docs_dir.rglob("*.xlsx"))
    docxs = sorted(docs_dir.rglob("*.docx"))
    all_files = pdfs + xlsxs + docxs
    
    if not all_files:
        raise FileNotFoundError(
            f"No PDF/Excel/Word files found in {docs_dir}. Add files or run: "
            "python scripts/generate_sample_docs.py"
        )

    from src.doc_registry import attach_metadata, classify_pdf
    from src.excel_loader import load_excel_chunks
    from src.word_loader import load_word_chunks

    all_chunks: list[dict] = []
    skipped = 0
    for file_path in all_files:
        # Calculate relative path exactly as load_pdf_chunks does
        try:
            rel_path = str(file_path.relative_to(docs_dir.parent))
        except Exception:
            try:
                rel_path = str(file_path.relative_to(file_path.parents[1]))
            except Exception:
                rel_path = file_path.name
        rel_path = rel_path.replace("\\", "/")
        
        mtime = file_path.stat().st_mtime
        
        # Incremental skip check
        if rel_path in indexed_files and mtime <= indexed_files[rel_path]:
            skipped += 1
            continue

        meta = classify_pdf(file_path)
        
        try:
            ext = file_path.suffix.lower()
            if ext == ".xlsx":
                raw = load_excel_chunks(file_path)
            elif ext == ".docx":
                raw = load_word_chunks(file_path)
            elif ext == ".pdf":
                raw = load_pdf_chunks(file_path)
            else:
                continue
                
            # Add mtime to each chunk's metadata
            for r in raw:
                r["mtime"] = mtime
                r["product"] = meta.product
                r["doc_type"] = meta.doc_type
                r["is_demo"] = meta.is_demo

            all_chunks.extend(attach_metadata(raw, meta))
        except Exception as e:
            print(f"Error loading {file_path.name}: {e}")
            
    if skipped > 0:
        print(f"Skipped {skipped} files that were already up-to-date.")
    return all_chunks
