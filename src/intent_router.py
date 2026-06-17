import re
from typing import TypedDict, Optional


class IntentResult(TypedDict):
    intent: str
    entity: Optional[str]


# ── Intent patterns (order matters — most specific first) ──────────────────────
_COUNT_RE = re.compile(
    r"\bhow\s+many\b|\bcount\b|\bnumber\s+of\b",
    re.I,
)
_ROLES_FOR_ATTR_RE = re.compile(
    r"\bwhat\s+roles?\b|\bwhich\s+roles?\b|\broles?\s+(that\s+)?(have|has|can|with)\b|\bgive\s+(me\s+)?roles?\b",
    re.I,
)
_ATTRS_FOR_ROLE_RE = re.compile(
    r"\blist\b|\ball\s+attr|\bgive\s+(the\s+|me\s+)?attr|\battr(ibutes?)?\s+(of|for)\b"
    r"|\battributes?\s+(of|for|that|does)\b|\bpermissions?\s+(of|for)\b|\bwhat\s+can\b",
    re.I,
)
_DESCRIBE_RE = re.compile(
    r"\bdescribe\b|\bcompare\b|\bexplain\s+attr|\bwhat\s+is\s+(?!project_name|project_module|sfs|mfa)",
    re.I,
)

# ── Stop words stripped before entity extraction ───────────────────────────────
_STOP = {
    "what", "which", "how", "many", "give", "me", "the", "a", "an", "all",
    "list", "show", "count", "number", "of", "for", "that", "have", "has",
    "can", "with", "does", "do", "are", "is", "and", "describe", "compare",
    "explain", "permissions", "attributes", "attr", "roles", "role",
    "please", "its", "their",
}


def _extract_entity(question: str) -> Optional[str]:
    """Strip intent keywords and stop words; return the remaining noun phrase."""
    q = question.lower().strip().rstrip("?.")
    # Remove leading intent verbs/phrases
    q = re.sub(
        r"^(list all|list|give (me |the )?|what (roles?|attr\w*)|which (roles?|attr\w*)|"
        r"how many (attr\w*|permissions?) (does |do )?|describe|compare|count|show)",
        "", q, flags=re.I
    ).strip()
    # Remove trailing noise
    q = re.sub(r"\b(have|has|for|attribute|attributes|attr|role|roles|permission|permissions)\b", "", q, flags=re.I)
    tokens = [t for t in q.split() if t not in _STOP and len(t) > 1]
    entity = " ".join(tokens).strip()
    return entity if entity else None


def route_role_intent(question: str) -> IntentResult:
    """
    Zero-cost local rules-based intent router.
    No API calls — instant, deterministic, no rate limits.
    """
    q = question.strip()

    if _COUNT_RE.search(q):
        entity = _extract_entity(q)
        return {"intent": "COUNT_ATTRIBUTES", "entity": entity}

    if _ROLES_FOR_ATTR_RE.search(q):
        entity = _extract_entity(q)
        return {"intent": "GET_ROLES_FOR_ATTRIBUTE", "entity": entity}

    if _ATTRS_FOR_ROLE_RE.search(q):
        entity = _extract_entity(q)
        return {"intent": "GET_ATTRIBUTES_FOR_ROLE", "entity": entity}

    if _DESCRIBE_RE.search(q):
        entity = _extract_entity(q)
        return {"intent": "DESCRIBE_ATTRIBUTE", "entity": entity}

    return {"intent": "GENERAL_SEARCH", "entity": None}
