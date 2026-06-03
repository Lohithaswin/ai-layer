"""Classify PDFs into product / doc_type metadata at ingest (scales to 1000s of files)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.config import DEMO_PDF_NAMES

_DOC_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("user_manual", re.compile(r"user\s*manual|_manual|user\s*guide", re.I)),
    ("install_guide", re.compile(r"installation|install", re.I)),
    ("security_manual", re.compile(r"security\s*management|securitymanagement|cybersecurity", re.I)),
    ("release_notes", re.compile(r"release\s*notes|release_notes", re.I)),
    ("change_log", re.compile(r"change\s*log|changelog", re.I)),
]


@dataclass(frozen=True)
class DocMetadata:
    source_file: str
    product: str  # e.g. project_name | project_module | demo | unknown
    doc_type: str  # user_manual | install_guide | security_manual | sample | unknown
    is_demo: bool
    manual_version: str | None  # e.g. 140 from filename


def _extract_manual_version(filename: str) -> str | None:
    m = re.search(r"version[_\s]*(\d+(?:\.\d+)*)", filename, re.I)
    if m:
        return m.group(1)
    m = re.search(r"_v\.?\s*(\d+)", filename, re.I)
    if m:
        return m.group(1)
    return None


def classify_pdf(path: Path) -> DocMetadata:
    name = path.name
    lower = name.lower()

    if lower in DEMO_PDF_NAMES or any(
        x in lower
        for x in (
            "deployment-guide",
            "api-security",
            "architecture-overview",
            "sample",
            "demo",
        )
    ):
        return DocMetadata(
            source_file=name,
            product="demo",
            doc_type="sample",
            is_demo=True,
            manual_version=None,
        )

    # 1. Scan for known products first (scalable keyword scan)
    product = "unknown"
    for known in ("project_name", "project_module", "pki", "sfs", "ldap", "iam", "mfa", "se1210"):
        if known in lower:
            product = known
            break

    # 2. Fall back to dynamic product extraction from the filename prefix
    # e.g., "PROJECT_MODULE_User Manual.pdf" -> product is "project_module"
    if product == "unknown":
        base = path.stem
        normalized = base.replace("-", "_").replace(" ", "_")
        parts = [p.strip() for p in normalized.split("_") if p.strip()]
        if parts:
            first = parts[0]
            # Alphanumeric between 2 and 10 characters represents the product code
            if 2 <= len(first) <= 10 and re.match(r"^[A-Za-z0-9]+$", first):
                if first.lower() not in ("release", "change", "changelog"):
                    product = first.lower()

    doc_type = "unknown"
    for dtype, pat in _DOC_TYPE_PATTERNS:
        if pat.search(name):
            doc_type = dtype
            break

    if "security" in lower and doc_type == "unknown":
        doc_type = "security_manual"

    return DocMetadata(
        source_file=name,
        product=product,
        doc_type=doc_type,
        is_demo=False,
        manual_version=_extract_manual_version(name),
    )


def get_active_products() -> set[str]:
    """Scan the docs folder and return all unique active products dynamically."""
    from src.config import DOCS_DIR
    products = set()
    if DOCS_DIR.exists():
        for path in DOCS_DIR.rglob("*.pdf"):
            meta = classify_pdf(path)
            if meta.product and meta.product not in ("unknown", "demo"):
                products.add(meta.product.lower())
    return products


def attach_metadata(chunks: list[dict], meta: DocMetadata) -> list[dict]:
    for c in chunks:
        c["product"] = meta.product
        c["doc_type"] = meta.doc_type
        c["is_demo"] = meta.is_demo
        if meta.manual_version:
            c["manual_version"] = meta.manual_version
    return chunks

