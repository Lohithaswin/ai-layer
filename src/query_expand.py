"""Extra search queries for acronym / definition questions."""

from __future__ import annotations

import re

from src.context_focus import is_procedure_question, query_terms

_DEFINITION_PATTERNS = re.compile(
    r"\b(full form|stands for|meaning of|what is|what does|expand|definition of|acronym)\b",
    re.I,
)
_FIELD_DETAIL_PATTERNS = re.compile(
    r"\b(fields?|details?|window|form|table|columns?|mandatory|required)\b",
    re.I,
)
_UI_SECTION_PATTERNS = re.compile(
    r"\b(add new user|user details|user roles)\b",
    re.I,
)
_ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9-]{1,9}\b")
_NOISE = frozenset(
    {
        "THE", "AND", "FOR", "ITS", "WHAT", "WIND", "POWER", "MANAGEMENT",
        "CENTER", "AGENT", "CENTRAL", "EXPLAIN", "INTRODUCTION", "SECURITY",
        "USER", "MANUAL", "GUIDE", "VERSION", "RESTRICTED", "HOW", "TO", "DO",
        "WE", "YOU", "ARE", "THEM", "THIS", "THAT", "SAME", "ABOUT",
    }
)


def is_definition_question(question: str) -> bool:
    return bool(_DEFINITION_PATTERNS.search(question))


def is_field_detail_question(question: str) -> bool:
    return bool(_FIELD_DETAIL_PATTERNS.search(question)) or bool(
        _UI_SECTION_PATTERNS.search(question)
    )


def extract_acronyms(question: str) -> list[str]:
    # Extract uppercase words resembling acronyms (e.g. PROJECT_MODULE, JWT)
    found = _ACRONYM_PATTERN.findall(question)
    acronyms: list[str] = []
    
    # Check uppercase matching tokens
    for token in found:
        token_upper = token.upper()
        if token_upper in _NOISE:
            continue
        # Length check for typical acronyms/products
        if 2 <= len(token_upper) <= 10:
            # Only add if it contains letters (not pure numbers)
            if re.search(r"[A-Za-z]", token_upper):
                if token_upper not in acronyms:
                    acronyms.append(token_upper)

    # Check lowercase acronyms inside quotes
    quoted = re.findall(r'"([A-Za-z0-9-]+)"', question)
    for q in quoted:
        q_upper = q.upper()
        if q_upper not in _NOISE and 2 <= len(q_upper) <= 10:
            if q_upper not in acronyms:
                acronyms.append(q_upper)

    # Check if any active products are mentioned in lowercase/mixedcase
    from src.doc_registry import get_active_products
    active_products = get_active_products()
    q_lower = question.lower()
    for prod in active_products:
        if re.search(rf"\b{re.escape(prod)}\b", q_lower):
            prod_upper = prod.upper()
            if prod_upper not in acronyms:
                acronyms.append(prod_upper)

    return acronyms


def is_version_history_question(question: str) -> bool:
    q = question.lower()
    has_version_kw = any(
        w in q
        for w in (
            "first version",
            "initial version",
            "earliest version",
            "version history",
            "document version history",
            "software release",
            "product version",
            "when was",
            "released",
        )
    )
    if not has_version_kw:
        return False
        
    if any(w in q for w in ("version", "release")):
        return True
        
    from src.doc_registry import get_active_products
    active_products = get_active_products()
    return any(prod in q for prod in active_products)


def is_architecture_question(question: str) -> bool:
    q = question.lower()
    return any(
        w in q
        for w in (
            "architecture",
            "components",
            "structure",
            "client-server",
            "client server",
            "sub-system",
            "subsystem",
        )
    )


def expanded_queries(question: str, subjects: list[str] | None = None) -> list[str]:
    """Return unique queries: original + helpers for definition lookup + multi-angle queries."""
    queries = [question.strip()]
    
    q_lower = question.lower()
    
    # ACRONYM/DEFINITION QUESTIONS - Most aggressive search
    if is_definition_question(question):
        for ac in extract_acronyms(question):
            queries.extend(
                [
                    ac,  # Just the acronym itself
                    f"{ac} definition",
                    f"{ac} meaning",
                    f"{ac} hereafter definition",
                    f'"{ac}" hereafter applies',
                    f"{ac} stands for",
                    f"what is {ac}",
                    f"full form {ac}",
                    f"{ac} acronym expansion",
                    f"{ac} disclaimer user manual",
                ]
            )
    
    # Also check for "full form" pattern specifically
    if "full form" in q_lower or "stands for" in q_lower or "what is" in q_lower:
        # Extract the acronym/term being asked about
        for ac in extract_acronyms(question):
            if ac not in queries:
                queries.append(ac)
    
    # Multi-angle queries for how-to and process questions
    if any(word in q_lower for word in ["how", "process", "steps", "deploy", "implement", "install"]):
        if "how to" in q_lower or "how do" in q_lower:
            core = question.split("how")[-1].strip().replace("do we", "").replace("do you", "").strip()
            if core:
                queries.extend([
                    f"{core} process steps",
                    f"procedure for {core}",
                    f"guide to {core}",
                ])
    
    # UI field / form detail questions
    if is_field_detail_question(question):
        # Extract window/form name dynamically
        m = re.search(r"\b([A-Za-z0-9\s]+?)\s+(?:window|form|screen|dialog|tab|panel|table)\b", question, re.I)
        title = m.group(1).strip() if m else None
        if not title:
            m_quote = re.search(r'"([^"]+)"', question)
            title = m_quote.group(1).strip() if m_quote else None
        if not title:
            title = "user" if "user" in q_lower else "fields"
            
        queries.extend(
            [
                f"{title} window fields table",
                f"fields in the {title} window Menu Description",
                f"User Name Expiry Date Password Language Classification", # general common fields
            ]
        )

    if is_procedure_question(question):
        for term in list(query_terms(question))[:8]:
            queries.append(term)
        queries.append(f"procedure steps configuration {question[:120]}")

    if is_version_history_question(question):
        from src.doc_registry import get_active_products
        active_products = get_active_products()
        prod_suffix = ""
        for prod in active_products:
            if prod in q_lower:
                prod_suffix = f" of the {prod.upper()} Security Management"
                break
                
        queries.extend(
            [
                "Document Version History",
                f"first version{prod_suffix} software release",
                "Product Version Year and Month of release Modification",
                "100.0.0 2012.10 first version",
            ]
        )

    subjects = subjects or extract_acronyms(question)
    if is_architecture_question(question):
        for ac in subjects:
            ac_upper = ac.upper()
            queries.extend(
                [
                    f"{ac_upper} Security Management architecture",
                    f"{ac_upper} client-server structure layout",
                    f"User Management Security Logging Security Integrity",
                    f"{ac_upper} implementation SFGU components",
                ]
            )

    # Summary/overview queries
    if any(word in q_lower for word in ["summarize", "summary", "overview", "explain", "what is"]):
        if "what is" in q_lower or "what are" in q_lower:
            topic = question.replace("what is", "").replace("what are", "").strip()
            if topic:
                queries.extend([
                    f"{topic} overview",
                    f"{topic} definition",
                    f"about {topic}",
                ])

    # Dedupe preserving order; cap count for latency
    from src.config import MAX_EXPANDED_QUERIES

    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique[:MAX_EXPANDED_QUERIES]

