"""
Semantic section matching and extraction
for enterprise manual RAG systems.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional


# =========================================================
# HEADING DETECTION
# =========================================================

_HEADING_RE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:(\d+(?:\.\d+)*)\.?\s+)?"
    r"([A-Z][^\n]{2,120})"
    r"(?=\n|$)",
    re.MULTILINE,
)

_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "for",
    "to",
    "in",
    "on",
    "with",
    "using",
    "used",
    "user",
    "users",
    "system",
}


# =========================================================
# NORMALIZATION
# =========================================================

def _normalize(text: str) -> str:
    """
    Normalize text for semantic comparison.
    """

    text = text.lower()

    text = re.sub(r"\s+", " ", text)

    text = re.sub(r"[^\w\s]", "", text)

    return text.strip()


def _similarity(a: str, b: str) -> float:
    """
    Semantic similarity score.
    """

    return SequenceMatcher(
        None,
        _normalize(a),
        _normalize(b),
    ).ratio()


# =========================================================
# QUERY + HEADING TERMS
# =========================================================

def _query_terms(query: str) -> set[str]:

    words = re.findall(
        r"[a-zA-Z]{3,}",
        query.lower(),
    )

    return {
        w
        for w in words
        if w not in _STOPWORDS
    }


def _heading_terms(heading: str) -> set[str]:

    return _query_terms(heading)


def _lexical_overlap(
    query_terms: set[str],
    heading_terms: set[str],
) -> float:

    if not query_terms:
        return 0.0

    return (
        len(query_terms & heading_terms)
        / len(query_terms)
    )


# =========================================================
# HEADING VALIDATION
# =========================================================

def _is_probable_heading(text: str) -> bool:
    """
    Reject prose lines and procedural text.
    """

    stripped = text.strip()

    if not stripped:
        return False

    if len(stripped) > 120:
        return False

    # prose usually ends with punctuation
    if stripped.endswith("."):
        return False

    # reject obvious prose lines (e.g. instruction phrases, inline figures)
    if re.search(
        r"\b("
        r"click|enter\s+the|user\s+can|provides?|enables?|"
        r"following\s+figure|shown\s+in|illustrated\s+in"
        r")\b",
        stripped,
        re.I,
    ):
        return False

    words = re.findall(
        r"[A-Za-z]+",
        stripped,
    )

    if not 1 <= len(words) <= 12:
        return False

    return True


# =========================================================
# HEADING EXTRACTION
# =========================================================

def extract_section_headings(
    text: str,
) -> list[tuple[str, int]]:

    headings = []

    for match in _HEADING_RE.finditer(text):

        heading = (
            match.group(2).strip()
        )

        if not _is_probable_heading(
            heading
        ):
            continue

        headings.append(
            (
                heading,
                match.start(),
            )
        )

    return headings


def _extract_headings(
    text: str,
) -> list[dict]:

    headings = []

    for match in _HEADING_RE.finditer(text):

        section_num = (
            match.group(1) or ""
        ).strip()

        heading = (
            match.group(2).strip()
        )

        if not _is_probable_heading(
            heading
        ):
            continue

        headings.append(
            {
                "heading": heading,
                "section_num": section_num,
                "position": match.start(),
            }
        )

    return headings


# =========================================================
# SECTION MATCHING
# =========================================================

def find_matching_sections(
    query: str,
    text: str,
    min_score: float = 0.50,
) -> list[dict]:
    """
    Find semantically matching section headings.
    """

    query_terms = _query_terms(query)

    headings = _extract_headings(text)

    matches = []

    for item in headings:

        heading = item["heading"]

        lexical = _lexical_overlap(
            query_terms,
            _heading_terms(heading),
        )

        # Skip expensive similarity comparisons if there is no lexical overlap.
        # Max score when lexical is 0.0 is 0.45, which can never meet min_score (>= 0.45).
        if lexical <= 0.0:
            continue

        semantic = _similarity(
            query,
            heading,
        )

        score = (
            lexical * 0.55
            + semantic * 0.45
        )

        if score < min_score:
            continue

        matches.append(
            {
                "heading": heading,
                "section_num": item["section_num"],
                "position": item["position"],
                "score": round(score, 4),
            }
        )

    matches.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    return matches


# =========================================================
# SECTION EXTRACTION
# =========================================================

def _parse_section_num(
    section: str,
) -> list[int]:

    parts = []

    for p in section.split("."):

        p = p.strip()

        if not p.isdigit():
            return []

        parts.append(int(p))

    return parts


def _is_new_section(
    current_num: str,
    next_num: str,
) -> bool:
    """
    Detect true section transitions.

    Keeps:
    - child subsections

    Stops at:
    - sibling sections
    - parent sections
    """

    if not next_num:
        return True

    if not current_num:
        return True

    current_parts = _parse_section_num(
        current_num
    )

    next_parts = _parse_section_num(
        next_num
    )

    if not current_parts or not next_parts:
        return True

    # child subsection
    if (
        len(next_parts) > len(current_parts)
        and next_parts[: len(current_parts)]
        == current_parts
    ):
        return False

    return True


def extract_complete_section(
    text: str,
    heading: str,
) -> Optional[str]:
    """
    Extract FULL semantic section.

    Supports:
    - multi-page sections
    - nested subsections
    - NOTE/WARNING blocks
    - long procedures
    - table continuations
    - avoids premature cutoff
    """

    headings = _extract_headings(text)

    if not headings:
        return None

    target = None

    best_score = 0.0

    # =====================================================
    # FIND BEST MATCHING HEADING
    # =====================================================

    for item in headings:

        score = _similarity(
            item["heading"],
            heading,
        )

        if score > best_score:
            best_score = score
            target = item

    if not target:
        return None

    if best_score < 0.72:
        return None

    start = target["position"]

    current_num = target["section_num"]

    end = len(text)

    current_idx = headings.index(target)

    # =====================================================
    # WALK FORWARD UNTIL TRUE NEXT SECTION
    # =====================================================

    for next_item in headings[current_idx + 1:]:

        next_num = next_item["section_num"]

        next_heading = next_item["heading"].strip()

        next_heading_lower = next_heading.lower()

        # -------------------------------------------------
        # KEEP CHILD SUBSECTIONS INSIDE CURRENT SECTION
        # -------------------------------------------------

        if (
            current_num
            and next_num
            and next_num.startswith(current_num + ".")
        ):
            continue

        # -------------------------------------------------
        # KEEP NOTE / WARNING / TIPS INSIDE SECTION
        # -------------------------------------------------

        if any(
            keyword in next_heading_lower
            for keyword in (
                "note",
                "notes",
                "warning",
                "warnings",
                "caution",
                "guideline",
                "guidelines",
                "tip",
                "tips",
                "important",
                "prerequisite",
                "prerequisites",
            )
        ):
            continue

        # -------------------------------------------------
        # KEEP TABLE CONTINUATIONS
        # -------------------------------------------------

        if any(
            keyword in next_heading_lower
            for keyword in (
                "table",
                "continued",
            )
        ):
            continue

        # -------------------------------------------------
        # DETECT TRUE NEXT SECTION
        # -------------------------------------------------

        if _is_new_section(
            current_num,
            next_num,
        ):
            end = next_item["position"]
            break

    extracted = text[start:end].strip()

    # =====================================================
    # CLEANUP
    # =====================================================

    extracted = re.sub(
        r"\n{3,}",
        "\n\n",
        extracted,
    )

    extracted = re.sub(
        r"[ \t]+",
        " ",
        extracted,
    )

    extracted = re.sub(
        r"\n\s*\n\s*\n+",
        "\n\n",
        extracted,
    )

    return extracted.strip()


# =========================================================
# SCORE BOOSTING
# =========================================================

def boost_section_content(
    hits: list[dict],
    query: str,
) -> None:
    """
    Boost retrieval hits containing
    semantically matching headings.
    """

    query_terms = _query_terms(query)

    for hit in hits:

        body = (
            hit.get("parent_text")
            or hit.get("text", "")
        )

        headings = _extract_headings(
            body
        )

        best = 0.0

        best_heading = None

        for item in headings:

            heading = item["heading"]

            lexical = _lexical_overlap(
                query_terms,
                _heading_terms(heading),
            )

            # Skip similarity matching if no word overlap (score cannot reach threshold 0.55)
            if lexical <= 0.0:
                continue

            semantic = _similarity(
                query,
                heading,
            )

            score = (
                lexical * 0.55
                + semantic * 0.45
            )

            if score > best:
                best = score
                best_heading = heading

        if best >= 0.55:

            hit["score"] = (
                float(
                    hit.get("score", 0)
                )
                * (1.0 + best * 0.35)
            )

            if best > 0.72:
                hit["score"] += 5.0

            hit["section_match"] = (
                best_heading
            )

            hit["section_score"] = best


# =========================================================
# HELPERS
# =========================================================

def extract_section_context(
    text: str,
    section_heading: str,
    context_lines: int = 5,
) -> Optional[str]:
    """
    Compatibility wrapper.
    """

    return extract_complete_section(
        text,
        section_heading,
    )


def is_configuration_question(
    query: str,
) -> bool:

    return bool(
        re.search(
            r"\b("
            r"configure|configuration|"
            r"setup|install|enable|"
            r"disable|set|adjust|"
            r"modify|change"
            r")\b",
            query,
            re.I,
        )
    )


def is_procedure_topic_question(
    query: str,
) -> bool:

    return bool(
        re.search(
            r"\b("
            r"how\s+to|steps?|"
            r"procedure|process"
            r")\b",
            query,
            re.I,
        )
    )


def get_likely_section_keywords(
    query: str,
) -> list[str]:
    """
    Extract probable section keywords.
    """

    query_clean = re.sub(
        r"\b("
        r"how|to|the|a|an|"
        r"steps?|procedure|process"
        r")\b",
        "",
        query,
        flags=re.I,
    )

    keywords = re.findall(
        r"\b([A-Z][A-Za-z0-9\s]+)\b",
        query_clean,
    )

    cleaned = []

    for kw in keywords:

        kw = kw.strip()

        if (
            3 <= len(kw) <= 50
            and kw.lower()
            not in {
                "system",
                "guide",
                "manual",
                "installation",
                "configuration",
            }
        ):
            cleaned.append(kw)

    return cleaned[:3]


def strongest_section_match(
    query: str,
    hits: list[dict],
):
    """
    Strict semantic heading matcher.
    """

    query_norm = re.sub(
        r"[^a-z0-9 ]",
        " ",
        query.lower(),
    )

    query_terms = {
        t
        for t in query_norm.split()
        if len(t) > 2
    }

    best = None
    best_score = 0.0

    heading_re = re.compile(
        r"(?:^|\n)\s*(\d+(?:\.\d+)*)?\.?\s*([^\n]{3,140})",
        re.M,
    )

    for hit in hits:

        text = (
            hit.get("parent_text")
            or hit.get("text", "")
        )

        for match in heading_re.finditer(text):

            heading = match.group(2).strip()

            heading_norm = re.sub(
                r"[^a-z0-9 ]",
                " ",
                heading.lower(),
            )

            heading_terms = {
                t
                for t in heading_norm.split()
                if len(t) > 2
            }

            if not heading_terms:
                continue

            overlap = len(
                query_terms
                & heading_terms
            )

            score = overlap / max(
                len(query_terms),
                1,
            )

            # strong phrase bonus
            if query_norm in heading_norm:
                score += 1.0

            if score > best_score:

                best_score = score

                best = {
                    "hit": hit,
                    "heading": heading,
                    "score": score,
                }

    return best