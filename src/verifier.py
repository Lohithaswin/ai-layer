"""Ground answers in retrieved context — catch unsupported version numbers and cross-doc bleed."""

from __future__ import annotations

import re

# Claims that should not appear when answering from YOUR_PRODUCT manuals
_CROSS_CORPUS_MARKERS = (
    "payment.events",
    "Payment Service",
    "API Gateway",
    "Notification Service",
    "Kafka topic",
    "card capture",
    "OAuth 2.0",
    "semantic release tags",
)

_VERSION_IN_ANSWER = re.compile(
    r"\b(?:version|v\.?)\s*(\d+(?:\.\d+)*)\b", re.I
)
_PRODUCT_VERSION = re.compile(r"\b(\d+\.\d+\.\d+)\b")
_YEAR_MONTH = re.compile(r"\b(20\d{2}\.\d{2})\b")


def _context_blob(hits: list[dict]) -> str:
    parts = []
    for h in hits:
        parts.append(h.get("parent_text") or h.get("text", ""))
    return "\n".join(parts).lower()


def _question_products(question: str) -> list[str]:
    q = question.lower()
    from src.doc_registry import get_active_products
    active_products = get_active_products()
    matched = []
    for prod in active_products:
        if re.search(rf"\b{re.escape(prod)}\b", q):
            matched.append(prod)
    return matched


def _verify_product_consistency(
    question: str, answer: str, hits: list[dict]
) -> tuple[bool, str | None]:
    asked_products = _question_products(question)
    if not asked_products:
        return True, None

    # Get products of the retrieved hits
    from src.doc_registry import classify_pdf
    from pathlib import Path
    retrieved_products = set()
    for h in hits:
        src_file = h.get("source_file", "")
        if src_file:
            prod = classify_pdf(Path(src_file)).product
            if prod:
                retrieved_products.add(prod)

    # Check for missing products
    missing_products = [p for p in asked_products if p not in retrieved_products]
    
    # If all asked products are missing from retrieved sources (and we retrieved something)
    if len(missing_products) == len(asked_products) and hits:
        products_str = " or ".join(p.upper() for p in asked_products)
        return False, (
            f"The question asks about {products_str}, but retrieved sources are "
            f"from other products. Check that the correct manual is indexed."
        )

    # If some asked products are missing (e.g. comparison query where one is missing)
    if missing_products and hits:
        missing_str = ", ".join(p.upper() for p in missing_products)
        return False, (
            f"The question asks to compare/reference {missing_str}, but no retrieved sources "
            f"were found for {missing_str}. Check that the correct manuals are indexed."
        )

    ans = answer.lower()
    from src.doc_registry import get_active_products
    active_products = get_active_products()
    
    # Enforce that answer shouldn't discuss products that were not asked about and have no source files
    for asked in asked_products:
        other_products = {p for p in active_products if p not in asked_products}
        for other in other_products:
            if re.search(rf"\b{re.escape(other)}\b", ans):
                if not re.search(rf"\b{re.escape(asked)}\b", ans):
                    return False, (
                        f"The question asks for {asked.upper()}, but the answer describes {other.upper()}. "
                        f"Use {asked.upper()} sources only."
                    )

    return True, None


def verify_answer(
    answer: str,
    hits: list[dict],
    intent: str,
    subjects: list[str],
    question: str = "",
) -> tuple[bool, str | None]:
    """
    Return (is_grounded, warning_message).

    Checks:
    - Cross-corpus contamination for all queries
    - Version/product version claims appear in context (version_history intent)
    """
    if not answer or not hits:
        return True, None

    ok, msg = _verify_product_consistency(question, answer, hits)
    if not ok:
        return False, msg

    ctx = _context_blob(hits)
    answer_lower = answer.lower()

    # Cross-corpus contamination check (applied globally)
    for marker in _CROSS_CORPUS_MARKERS:
        if marker.lower() in answer_lower and marker.lower() not in ctx:
            return False, (
                "The answer may mix content from unrelated sample documents. "
                "Showing retrieved excerpts only — verify against sources."
            )

    if intent == "version_history":
        # If answer cites a version number, it must appear in context (not just V.140 header)
        for pat in (_PRODUCT_VERSION, _YEAR_MONTH):
            for m in pat.finditer(answer):
                token = m.group(1)
                if token not in ctx and token.replace(".", "") not in ctx:
                    return False, (
                        f"The answer mentions '{token}' but it was not found in the "
                        "retrieved Document Version History context. "
                        "The manual header version (e.g. 140) is not the first release."
                    )

        if "first version" in answer_lower or "first release" in answer_lower:
            if "first version" not in ctx and "first version" not in answer_lower:
                pass
            elif "100.0.0" in ctx and "100.0.0" not in answer and "100" not in answer:
                return False, (
                    "Context contains first release 100.0.0 (2012.10) but the answer "
                    "may have used the manual version number instead."
                )

    return True, None


def apply_verifier(
    answer: str,
    hits: list[dict],
    intent: str,
    subjects: list[str],
    context: str,
    question: str = "",
) -> tuple[str, str | None]:
    """Return possibly revised answer and optional note."""
    ok, warning = verify_answer(
        answer, hits, intent, subjects, question=question
    )
    if ok:
        return answer, None
    safe = (
        f"**Note:** {warning}\n\n"
        "**Retrieved context (verify manually):**\n\n"
        f"{context[:6000]}"
    )
    return safe, "verification_failed"

