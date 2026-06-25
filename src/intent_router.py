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
    r"|\battributes?\s+(of|for|that|does|do)\b|\bpermissions?\s+(of|for)\b|\bwhat\s+can\b"
    r"|\bwhat\s+attr|\battr\w*\s+(does|do)\b",
    re.I,
)
_DESCRIBE_RE = re.compile(
    r"\bdescribe\b|\bcompare\b|\bexplain\s+attr|\bwhat\s+is\s+(?!project_name|project_module|sfs|mfa)",
    re.I,
)

# Catch-all for any query mentioning roles/attributes that missed the specific regexes
_ROLE_KEYWORD_RE = re.compile(
    r"\b(role|roles|attribute|attributes|permission|permissions)\b",
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

# Phrases to strip from start of question before entity extraction
_STRIP_PREFIX_RE = re.compile(
    r"^(list\s+all\s+attr\w*\s+(of|for)|list\s+all|list|give\s+(me\s+|the\s+)?attr\w*\s+(of|for)|give\s+(me\s+|the\s+)?"
    r"|what\s+attr\w*\s+does|what\s+attr\w*\s+do|what\s+(roles?|attr\w*)|which\s+(roles?|attr\w*)"
    r"|how\s+many\s+(attr\w*|permissions?)\s+(does|do)?|describe|compare|count|show\s+attr\w*\s+(of|for)|show)",
    re.I,
)

# Trailing noise words to strip after prefix removal
_STRIP_SUFFIX_RE = re.compile(
    r"\b(have|has|for|the|attribute|attributes|attr|role|roles|permission|permissions|contain|contains|include|includes)\b",
    re.I,
)


def _extract_entity(question: str) -> Optional[str]:
    """Strip intent keywords and stop words; return the remaining noun phrase.
    Preserves hyphenated role names like 'swp-PPC View Full Configuration'.
    """
    q = question.strip().rstrip("?.")

    # Remove leading intent phrase
    q = _STRIP_PREFIX_RE.sub("", q, count=1).strip()

    # Remove trailing noise words (but preserve hyphenated tokens)
    q = _STRIP_SUFFIX_RE.sub("", q).strip()

    # Strip pure stop words (case-insensitive) but preserve casing of result
    tokens = [t for t in q.split() if t.lower() not in _STOP and len(t) > 1]
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

    # Check ATTRS_FOR_ROLE before ROLES_FOR_ATTR — avoids false match on
    # "role have" in "What attributes does X role have"
    if _ATTRS_FOR_ROLE_RE.search(q):
        entity = _extract_entity(q)
        # Remove the word "role" from end of entity if it snuck in
        if entity:
            entity = re.sub(r"\brole\b", "", entity, flags=re.I).strip()
        return {"intent": "GET_ATTRIBUTES_FOR_ROLE", "entity": entity}

    if _ROLES_FOR_ATTR_RE.search(q):
        entity = _extract_entity(q)
        return {"intent": "GET_ROLES_FOR_ATTRIBUTE", "entity": entity}

    if _DESCRIBE_RE.search(q):
        entity = _extract_entity(q)
        return {"intent": "DESCRIBE_ATTRIBUTE", "entity": entity}

    # If it contains role keywords but didn't match the specific patterns,
    # route it to a general DB search instead of letting the LLM hallucinate
    # from the old Excel docs.
    if _ROLE_KEYWORD_RE.search(q):
        entity = _extract_entity(q)
        # Even if entity is empty after stripping, we can just pass the original question
        # words as keywords to the DB search.
        if not entity:
            # Just strip stop words to get search keywords
            tokens = [t for t in q.split() if t.lower() not in _STOP and len(t) > 2]
            entity = " ".join(tokens)
        
        if entity:
            return {"intent": "GENERAL_ROLE_SEARCH", "entity": entity}

    return {"intent": "GENERAL_SEARCH", "entity": None}
