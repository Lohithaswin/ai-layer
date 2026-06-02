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


def _question_product(question: str) -> str | None:
    q = question.lower()
    from src.doc_registry import get_active_products
    active_products = get_active_products()
    for prod in active_products:
        if re.search(rf"\b{re.escape(prod)}\b", q):
            return prod
    return None


def _verify_product_consistency(
    question: str, answer: str, hits: list[dict]
) -> tuple[bool, str | None]:
    asked = _question_product(question)
    if not asked:
        return True, None

    # Check if the retrieved sources actually contain the asked product
    from src.doc_registry import classify_pdf
    from pathlib import Path
    has_asked_source = False
    for h in hits:
        src_file = h.get("source_file", "")
        if src_file:
            prod = classify_pdf(Path(src_file)).product
            if prod == asked:
                has_asked_source = True
                break

    if not has_asked_source and hits:
        return False, (
            f"The question asks about {asked.upper()}, but retrieved sources are "
            f"from other products. Check that the correct manual is indexed."
        )

    ans = answer.lower()
    from src.doc_registry import get_active_products
    active_products = get_active_products()
    
    other_products = {p for p in active_products if p != asked}
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

