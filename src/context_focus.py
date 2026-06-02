"""
Scalable context focusing: prefer one page/section when the answer is localized.

Used for procedural questions (how-to, configure, login, field forms) so the LLM
does not merge unrelated sections from other pages.
"""

from __future__ import annotations

import re
from typing import Any

from src.config import (
    CONTEXT_FOCUS_ENABLED,
    CONTEXT_FOCUS_MAX_SOURCES,
    CONTEXT_FOCUS_PAGE_GAP,
)

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "to", "for", "of", "in", "on", "at", "is", "are", "was",
        "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "should", "could", "may", "might", "must", "shall", "can",
        "what", "which", "who", "whom", "whose", "where", "when", "why", "how",
        "if", "then", "than", "that", "this", "these", "those", "it", "its",
        "they", "them", "their", "we", "our", "you", "your", "i", "me", "my",
        "and", "or", "but", "not", "no", "yes", "all", "any", "some", "such",
        "into", "about", "with", "from", "by", "as", "want", "wants", "need",
        "needs", "give", "tell", "explain", "describe", "using", "use",
    }
)

_PROCEDURE_RE = re.compile(
    r"\b("
    r"what to do|how to|how do|how can|steps?|procedure|configure|configuration|"
    r"enable|disable|set up|setup|install|deploy|log in|login|log on|sign in|"
    r"create|add|remove|delete|update|change|modify|map|enter|open|restart|"
    r"follow the|perform the|troubleshoot|troubleshooting|problems?|issues?|solutions?"
    r")\b",
    re.I,
)

_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{4,100})",
    re.M,
)

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def is_procedure_question(question: str) -> bool:
    """True when the user expects numbered steps or a single configuration procedure."""
    return bool(_PROCEDURE_RE.search(question))


def should_focus_context(intent: str, question: str) -> bool:
    """Whether to collapse retrieval to the best-matching page/section."""
    if not CONTEXT_FOCUS_ENABLED:
        return False
    if intent == "how_to":
        return True
    if intent == "field_detail":
        q = question.lower()
        # UI field tables often span consecutive pages — keep multi-page recall
        if any(
            x in q
            for x in (
                "add new user",
                "fields in the",
                "field",
                "window",
                "form",
                "table",
            )
        ):
            return False
        return True
    if intent == "general" and is_procedure_question(question):
        return True
    return False


def query_terms(question: str) -> set[str]:
    tokens = _TOKEN_RE.findall(question.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) >= 3}


def _hit_body(hit: dict) -> str:
    return hit.get("parent_text") or hit.get("text", "")


def _hit_score(hit: dict) -> float:
    return float(hit.get("relevance", hit.get("score", 0)))


def lexical_overlap(text: str, terms: set[str]) -> float:
    if not terms:
        return 0.0
    body_tokens = set(_TOKEN_RE.findall(text.lower()))
    if not body_tokens:
        return 0.0
    return len(terms & body_tokens) / len(terms)


def extract_section_titles(text: str) -> list[str]:
    return [m.group(1).strip() for m in _SECTION_RE.finditer(text)]


def _page_key(hit: dict) -> tuple[str, int]:
    return (hit.get("source_file", ""), int(hit.get("page", 0)))


def _combined_relevance(hit: dict, terms: set[str], anchor_body: str | None) -> float:
    body = _hit_body(hit)
    base = _hit_score(hit)
    q_ov = lexical_overlap(body, terms)
    a_ov = lexical_overlap(body, query_terms(anchor_body)) if anchor_body else 0.0
    return base * (1.0 + 0.35 * q_ov + 0.2 * a_ov)


def demote_weak_hits(hits: list[dict], terms: set[str], anchor: dict) -> None:
    """Down-rank chunks that share little vocabulary with the question and top hit."""
    anchor_body = _hit_body(anchor)
    anchor_sections = set(s.lower() for s in extract_section_titles(anchor_body))
    anchor_score = _combined_relevance(anchor, terms, anchor_body)

    for h in hits:
        if h is anchor:
            continue
        body = _hit_body(h)
        comb = _combined_relevance(h, terms, anchor_body)
        if comb >= anchor_score * 0.82:
            continue

        hit_sections = set(s.lower() for s in extract_section_titles(body))
        if anchor_sections and hit_sections and not (anchor_sections & hit_sections):
            factor = 0.4
        elif lexical_overlap(body, terms) < 0.08:
            factor = 0.5
        else:
            factor = 0.65

        for key in ("score", "relevance"):
            if key in h:
                h[key] = float(h[key]) * factor


def focus_hits(
    hits: list[dict],
    question: str,
    max_sources: int | None = None,
) -> list[dict]:
    """
    Collapse to dominant (file, page) sequences grouped per unique manual,
    allowing retrieval of relevant sections from both YOUR_PRODUCT.
    """
    if not hits:
        return hits

    max_sources = max_sources or CONTEXT_FOCUS_MAX_SOURCES
    terms = query_terms(question)
    ranked = sorted(hits, key=lambda h: _combined_relevance(h, terms, None), reverse=True)
    anchor = ranked[0]

    demote_weak_hits(ranked, terms, anchor)
    ranked = sorted(ranked, key=lambda h: _combined_relevance(h, terms, _hit_body(anchor)), reverse=True)

    # 1. Identify all unique source files represented in the ranked hits
    unique_files = []
    for h in ranked:
        f = h.get("source_file")
        if f and f not in unique_files:
            unique_files.append(f)

    # 2. Group hits by unique source file
    hits_by_file: dict[str, list[dict]] = {}
    for h in ranked:
        f = h.get("source_file")
        if f:
            hits_by_file.setdefault(f, []).append(h)

    # 3. Order the files by their highest relevance score
    files_ordered = []
    for f in unique_files:
        f_hits = hits_by_file[f]
        best_score_in_file = _combined_relevance(f_hits[0], terms, _hit_body(anchor))
        files_ordered.append((f, best_score_in_file))
    files_ordered.sort(key=lambda x: x[1], reverse=True)

    all_focused_results = []
    # Take up to 3 most relevant manuals/files
    for f, f_score in files_ordered[:3]:
        f_ranked = hits_by_file[f]
        f_anchor = f_ranked[0]

        # Calculate page scores within this file
        f_page_scores: dict[int, float] = {}
        f_page_hits: dict[int, list[dict]] = {}
        for h in f_ranked:
            p = h["page"]
            score = _combined_relevance(h, terms, _hit_body(f_anchor))
            f_page_scores[p] = f_page_scores.get(p, 0.0) + score
            f_page_hits.setdefault(p, []).append(h)

        f_ordered_pages = sorted(f_page_scores.items(), key=lambda x: x[1], reverse=True)
        if not f_ordered_pages:
            continue

        f_best_page, f_best_score = f_ordered_pages[0]
        f_second_score = f_ordered_pages[1][1] if len(f_ordered_pages) > 1 else 0.0

        f_dominant = (
            f_second_score == 0
            or f_best_score >= f_second_score * (1.0 + CONTEXT_FOCUS_PAGE_GAP)
            or lexical_overlap(_hit_body(f_page_hits[f_best_page][0]), terms) >= 0.12
        )

        if not f_dominant:
            # If no clear single page dominates inside this file, append the top hits of this file
            all_focused_results.extend(f_ranked[:3])
            continue

        # Backtrack to the earliest consecutive page present in f_page_hits within this file
        start_page = f_best_page
        while (start_page - 1) in f_page_hits:
            start_page -= 1

        focused = f_page_hits[start_page]

        by_parent: dict[str, dict] = {}
        for h in sorted(focused, key=_hit_score, reverse=True):
            pid = h.get("parent_id") or f"{h.get('source_file')}|{h.get('page')}"
            if pid not in by_parent:
                by_parent[pid] = h

        f_result = list(by_parent.values())[:5]

        # Gather consecutive pages in ascending order within this file
        current_page = start_page
        while len(f_result) < 5:
            next_page = current_page + 1
            if next_page in f_page_hits:
                added_any = False
                for h in f_page_hits[next_page]:
                    pid = h.get("parent_id") or f"{h.get('source_file')}|{h.get('page')}"
                    if pid not in {r.get("parent_id") for r in f_result}:
                        if lexical_overlap(_hit_body(h), terms) >= 0.05 or len(f_result) < 5:
                            f_result.append(h)
                            added_any = True
                            if len(f_result) >= 5:
                                break
                if added_any:
                    current_page = next_page
                else:
                    break
            else:
                break

        all_focused_results.extend(f_result)

    # 4. Deduplicate the combined results by parent_id
    final_by_parent: dict[str, dict] = {}
    for h in all_focused_results:
        pid = h.get("parent_id") or f"{h.get('source_file')}|{h.get('page')}"
        if pid not in final_by_parent:
            final_by_parent[pid] = h

    result = list(final_by_parent.values())[:max_sources]
    return result if result else ranked[:max_sources]
