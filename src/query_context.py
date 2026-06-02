"""Resolve follow-up questions using recent chat history."""

from __future__ import annotations

import re

from src.query_expand import extract_acronyms

_FOLLOWUP_RE = re.compile(
    r"\b(it|its|it's|this|that|they|them|the system|the application|above|same)\b",
    re.I,
)
_SHORT_ACRONYM_RE = re.compile(r"^[A-Za-z]{2,8}\??$")


def _pick_primary_subject(acronyms: list[str]) -> str | None:
    from src.doc_registry import get_active_products
    active_products = get_active_products()
    for ac in acronyms:
        if ac.lower() in active_products:
            return ac
    return acronyms[0] if acronyms else None


def collect_subjects(question: str, history: list[dict] | None) -> list[str]:
    """Acronyms from the current question plus recent turns."""
    subjects = extract_acronyms(question)
    for msg in (history or [])[-8:]:
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        for ac in extract_acronyms(content):
            if ac not in subjects:
                subjects.append(ac)
    return subjects


def is_follow_up(question: str) -> bool:
    q = question.strip()
    if _FOLLOWUP_RE.search(q):
        return True
    if len(q.split()) <= 6 and not _SHORT_ACRONYM_RE.match(q):
        return True
    return False


def resolve_question(
    question: str, history: list[dict] | None = None
) -> tuple[str, list[str]]:
    """
    Return (search_question, subject_acronyms).

    If the current message names a product explicitly, ignore history subjects.
    Otherwise rewrite vague follow-ups using prior turns.
    """
    from src.query_router import resolve_primary_product

    subjects = collect_subjects(question, history)
    q_lower = question.lower().strip()

    if _SHORT_ACRONYM_RE.match(question.strip()):
        ac = question.strip().rstrip("?").upper()
        return f"What is {ac}? definition and overview", subjects or [ac]

    if not is_follow_up(question) and subjects:
        return question, subjects

    if not subjects:
        return question, subjects

    primary = resolve_primary_product(question, subjects, history)
    if not primary:
        primary = _pick_primary_subject(subjects)

    if not primary:
        return question, subjects

    primary_upper = primary.upper()
    if "architecture" in q_lower or "components" in q_lower:
        return (
            f"{primary_upper} architecture components client-server Security Management User Management Security Logging Security Integrity SFGU {question}",
            subjects,
        )

    if "security management" in q_lower or "implementation" in q_lower:
        return (
            f"{primary_upper} security management implementation configuration {question}",
            subjects,
        )

    return f"{primary_upper}: {question}", subjects

