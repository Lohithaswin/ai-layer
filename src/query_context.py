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
    for msg in reversed((history or [])[-8:]):
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

    # Extract previous user message to inject context for follow-ups (like role/attribute names that aren't acronyms)
    prev_user_msg = ""
    if history:
        for msg in reversed(history):
            if msg.get("role") == "user":
                prev_user_msg = msg.get("content", "").strip()
                break

    if not is_follow_up(question) and subjects:
        return question, subjects

    if not subjects:
        # If it's a follow up but no acronyms were found, at least inject the previous user message!
        if is_follow_up(question) and prev_user_msg:
            return f"{prev_user_msg} - {question}", subjects
        return question, subjects

    primary = resolve_primary_product(question, subjects, history)
    if not primary:
        primary = _pick_primary_subject(subjects)

    if not primary:
        if is_follow_up(question) and prev_user_msg:
             return f"{prev_user_msg} - {question}", subjects
        return question, subjects

    primary_upper = primary.upper()
    
    # Inject previous user message into the resolved question
    context_prefix = f"{prev_user_msg} - " if prev_user_msg else ""
    
    if "architecture" in q_lower or "components" in q_lower:
        return (
            f"{primary_upper} architecture components client-server Security Management User Management Security Logging Security Integrity SFGU {context_prefix}{question}",
            subjects,
        )

    if "security management" in q_lower or "implementation" in q_lower:
        return (
            f"{primary_upper} security management implementation configuration {context_prefix}{question}",
            subjects,
        )

    return f"{primary_upper}: {context_prefix}{question}", subjects


_AFFIRMATION_RE = re.compile(r"^\s*(yes|y|sure|ok|okay|please|yep|do\s+it|go\s+ahead)\b\s*[.?]*$", re.I)


def rewrite_affirmation_query(question: str, history: list[dict] | None) -> str:
    """
    If the user's question is a short affirmation (e.g. "yes", "sure", "ok")
    and the last assistant message suggested looking into certain topics/options,
    rewrite the query to target those topics.
    """
    q_strip = question.strip().lower()
    if not _AFFIRMATION_RE.match(q_strip) or len(q_strip.split()) > 3:
        return question

    if not history:
        return question

    # Find the last assistant message
    last_assistant_msg = None
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_assistant_msg = msg.get("content", "")
            break

    if not last_assistant_msg:
        return question

    # Look for suggestion patterns, e.g. "Would you like me to look into MFA | Multifactor Authentication or MFA v3.0.0 – Restricted instead?"
    # Or "Would you like me to look into X or Y?"
    # Or "Would you like to search for X?"
    suggestion_patterns = [
        r"look into (.+?) instead\?",
        r"look into (.+?)\?",
        r"search for (.+?)\?",
        r"reference (.+?)\?",
        r"discuss (.+?)\?",
    ]

    for pattern in suggestion_patterns:
        match = re.search(pattern, last_assistant_msg, re.I)
        if match:
            suggestion_content = match.group(1)
            # Split by " or "
            options = [opt.strip() for opt in re.split(r"\b(?:or)\b", suggestion_content, flags=re.I)]
            cleaned_options = []
            for opt in options:
                opt = re.sub(r"[.?*]$", "", opt).strip()
                # Remove quotes or markdown formatting
                opt = re.sub(r'^["\'`*]+|["\'`*]+$', "", opt)
                if opt:
                    cleaned_options.append(opt)
            if cleaned_options:
                return " and ".join(cleaned_options)

    # Fallback: if we can't parse specific options, but there was a previous user question,
    # rewrite to the previous user question so we don't search for "yes"
    for msg in reversed(history):
        if msg.get("role") == "user":
            content = msg.get("content", "").strip()
            if content and not _AFFIRMATION_RE.match(content.lower()):
                return content

    return question


