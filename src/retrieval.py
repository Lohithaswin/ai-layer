"""Metadata-filtered hybrid retrieval + rerank (production pipeline)."""

from __future__ import annotations

from typing import Any

from src.bm25_store import get_bm25_store
from src.config import (
    CONTEXT_FOCUS_MAX_SOURCES,
    HYBRID_DENSE_WEIGHT,
    HYBRID_SPARSE_WEIGHT,
    MAX_SECTION_PAGES,
    RETRIEVAL_CANDIDATES,
    RRF_K,
    TOP_K,
    USE_HYBRID_SEARCH,
)
from src.context_focus import focus_hits
from src.query_router import QueryPlan, route_query
from src.reranker import rerank
from src.section_matcher import (
    boost_section_content,
    is_configuration_question,
    find_matching_sections,
    extract_complete_section,
)
from src.vector_store import VectorStore

import re


def _retrieval_content_quality(text: str) -> int:
    """Score-based content quality — higher means more substantive content."""
    score = 0
    if re.search(r"^\s*\d+[.)]\s+\w", text, re.M):
        score += 3
    if re.search(r"^\s*[-*\u2022]\s+\w", text, re.M):
        score += 2
    sentences = re.findall(r"[.!?]\s+[A-Z]", text)
    if len(sentences) >= 2:
        score += 2
    elif len(sentences) == 1:
        score += 1
    if re.search(r"\w[\w\s]{2,30}:\s+\w", text):
        score += 1
    if re.search(r"[A-Za-z]:\\|/[a-z]+/|HKEY_|\.config\b|\.xml\b|\.json\b", text):
        score += 2
    if text.count("|") >= 3:
        score += 2
    wc = len(text.split())
    if wc >= 40:
        score += 2
    elif wc >= 20:
        score += 1
    return score


def _chunk_key(hit: dict) -> str:
    return f"{hit['source_file']}|{hit['page']}|{hit['chunk_index']}"


def _rrf_fuse(
    dense_hits: list[dict],
    sparse_hits: list[dict],
    dense_weight: float,
    sparse_weight: float,
    k: int = RRF_K,
) -> list[dict]:
    scores: dict[str, float] = {}
    records: dict[str, dict] = {}

    for rank, hit in enumerate(dense_hits):
        key = _chunk_key(hit)
        scores[key] = hit.get("score", 0.0)
        records[key] = dict(hit)

    for rank, hit in enumerate(sparse_hits):
        key = _chunk_key(hit)
        if key in scores:
            # Give a small bonus for being found in both sparse and dense
            scores[key] += 0.02
        else:
            # Baseline score for pure sparse hits so they don't override strong dense hits
            scores[key] = 0.55
            records[key] = dict(hit)

    fused = []

    for key, score in sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True,
    ):
        rec = dict(records[key])
        rec["score"] = score
        fused.append(rec)

    return fused


def _append_hit(
    hits: list[dict],
    hit: dict,
    min_score: float,
) -> None:

    key = _chunk_key(hit)

    for h in hits:

        if _chunk_key(h) == key:
            h["score"] = max(
                h["score"],
                min_score,
            )
            return

    hit["score"] = max(
        hit.get("score", 0),
        min_score,
    )

    hits.append(hit)


def _demote_boilerplate(
    hits: list[dict],
) -> None:

    for h in hits:

        text = (
            h.get("parent_text")
            or h.get("text", "")
        )

        if (
            text.count("Installation Guide") >= 2
            and len(text) < 900
        ):
            h["score"] *= 0.7


def _demote_release_logs(
    hits: list[dict],
    intent: str,
) -> None:
    if intent == "version_history":
        return

    for h in hits:
        doc_type = h.get("doc_type", "")
        src_file = (h.get("source_file") or "").lower()

        is_log = (
            doc_type in ("release_notes", "change_log")
            or "release notes" in src_file
            or "release_notes" in src_file
            or "change log" in src_file
            or "changelog" in src_file
        )

        if is_log:
            h["score"] = h.get("score", 0.0) * 0.1


def _is_metadata_or_toc_page(text: str) -> bool:
    text_lower = text.lower()
    # Dotted leaders or spaced dotted leaders
    if len(re.findall(r'[\.\-\_]{3,}\s*\d+', text_lower)) >= 3:
        return True
    if len(re.findall(r'\.\s+\.\s+\.\s+\d+', text_lower)) >= 3:
        return True
    
    # Typical introductory section titles
    intro_keywords = [
        "intended audience", 
        "document structure", 
        "document conventions", 
        "disclaimer of liability", 
        "qualified personnel",
        "use as described",
        "table of contents",
        "table of content",
        "preface"
    ]
    if any(kw in text_lower for kw in intro_keywords):
        return True
        
    # Chapter list table / summaries
    if "brief description" in text_lower and any(kw in text_lower for kw in ["glossary", "uninstallation procedure", "troubleshooting"]):
        return True
        
    return False


def _demote_toc_and_history(
    hits: list[dict],
) -> None:
    for h in hits:
        text = (
            h.get("parent_text")
            or h.get("text", "")
        )
        is_intro = _is_metadata_or_toc_page(text)
        is_history = any(kw in text.lower() for kw in ["document version history", "revision history", "version history", "modification record"])
        if is_intro or is_history:
            h["score"] = h.get("score", 0.0) * 0.01


def _boost_matching_doc_type(
    hits: list[dict],
    doc_type_filter: str | None,
) -> None:
    if not doc_type_filter:
        return

    for h in hits:
        doc_type = h.get("doc_type")
        if doc_type == doc_type_filter:
            h["score"] = h.get("score", 0.0) * 1.2
        elif doc_type == "unknown":
            # Neutral weight for unknown since it might be a valid guide
            pass
        else:
            # Demote non-matching types slightly
            h["score"] = h.get("score", 0.0) * 0.8


_SEC_NUM_RE = re.compile(
    r"(?:^|\n)\s*(\d+\.\d+(?:\.\d+)*)\.?\s+[A-Z]",
    re.M,
)


def _extract_section_numbers(
    text: str,
) -> list[str]:

    return _SEC_NUM_RE.findall(text)


def _parse_section_num(
    s: str,
) -> list[int] | None:

    parts = []

    for p in s.split("."):

        p = p.strip()

        if p.isdigit():
            parts.append(int(p))
        else:
            return None

    return parts if parts else None


def _is_new_section(
    ns: str,
    current_section: str,
) -> bool:

    ns_parts = _parse_section_num(ns)
    curr_parts = _parse_section_num(current_section)

    if not ns_parts or not curr_parts:
        return False

    min_len = min(
        len(ns_parts),
        len(curr_parts),
    )

    for i in range(min_len - 1):

        if ns_parts[i] != curr_parts[i]:
            return ns_parts[i] > curr_parts[i]

    last_idx = min_len - 1

    if ns_parts[last_idx] > curr_parts[last_idx]:
        return True

    elif ns_parts[last_idx] < curr_parts[last_idx]:
        return False

    if len(ns_parts) > len(curr_parts):
        return False

    if len(ns_parts) < len(curr_parts):
        return True

    return False


def _page_text(
    chunks: list[dict],
) -> str:

    seen = set()
    parts = []

    for chunk in sorted(
        chunks,
        key=lambda c: int(c.get("chunk_index", 0)),
    ):

        text = (
            chunk.get("parent_text")
            or chunk.get("text", "")
        )

        normalized = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        if normalized and normalized not in seen:
            seen.add(normalized)
            parts.append(text)

    return "\n".join(parts)


def _complete_section_from_pages(
    store: VectorStore,
    hit: dict,
    heading: str,
) -> str | None:
    """
    Build a section from the matched page forward.

    Parent chunks can contain only the first part of a long section. This
    gathers following pages from the same PDF and lets section extraction trim
    at the next detected heading.
    """

    source_file = hit.get("source_file")
    start_page = int(hit.get("page", 0))

    if not source_file or start_page < 1:
        return None

    page_texts = []

    for page in range(
        start_page,
        start_page + MAX_SECTION_PAGES,
    ):

        chunks = store.get_chunks_for_page(
            source_file,
            page,
        )

        if not chunks:
            break

        page_body = _page_text(chunks)

        if page_body:
            page_texts.append(page_body)

        # Stop once we have enough content AND hit a new section boundary
        if len(page_texts) >= 3:
            combined_so_far = "\n".join(page_texts)
            if _retrieval_content_quality(combined_so_far) >= 4:
                break

    if not page_texts:
        return None

    combined = "\n".join(page_texts)

    result = extract_complete_section(
        text=combined,
        heading=heading,
    )

    # Fallback: if section extraction fails (can't locate heading in combined text),
    # return all gathered pages as raw content — better than returning nothing.
    if not result and len(combined.strip()) > 80:
        return combined.strip()

    return result


def _expand_adjacent_pages(
    hits: list[dict],
    store: VectorStore,
    expand_further: bool = False,
) -> None:
    # Caching helper to avoid redundant SQLite queries for the same pages
    page_cache: dict[tuple[str, int], list[dict]] = {}

    def get_cached_chunks(source_file: str, page: int) -> list[dict]:
        key = (source_file, page)
        if key not in page_cache:
            page_cache[key] = store.get_chunks_for_page(source_file, page)
        return page_cache[key]

    # Only run adjacent page/section expansion on the top 15 candidates.
    # Candidates ranked 16+ are highly unlikely to make it into the final context anyway.
    anchors = sorted(hits, key=lambda x: x.get("score", 0), reverse=True)[:5]

    for h in anchors:

        h_text = (
            h.get("parent_text")
            or h.get("text", "")
        )

        # -------------------------------------------------
        # STANDARD PAGE EXPANSION
        # -------------------------------------------------

        for p in (
            h["page"] - 1,
            h["page"],
            h["page"] + 1,
        ):

            if p >= 1:

                for extra in get_cached_chunks(
                    h["source_file"],
                    p,
                ):

                    _append_hit(
                        hits,
                        extra,
                        min_score=h["score"] * 0.97,
                    )

        # -------------------------------------------------
        # DYNAMIC SECTION EXPANSION
        # -------------------------------------------------

        if expand_further:

            anchor_chunks = get_cached_chunks(
                h["source_file"],
                h["page"],
            )

            anchor_text = "\n".join(
                c.get("parent_text")
                or c.get("text", "")
                for c in anchor_chunks
            )

            sections = _extract_section_numbers(
                anchor_text
            )

            current_section = (
                sections[-1]
                if sections
                else None
            )

            current_p = h["page"]

            # Cap expansion pages to prevent excessive DB calls
            for _ in range(1):

                current_p += 1

                page_chunks = get_cached_chunks(
                    h["source_file"],
                    current_p,
                )

                if not page_chunks:
                    break

                page_text = "\n".join(
                    c.get("parent_text")
                    or c.get("text", "")
                    for c in page_chunks
                )

                next_sections = _extract_section_numbers(
                    page_text
                )

                section_ended = False

                if current_section and next_sections:

                    for ns in next_sections:

                        if _is_new_section(
                            ns,
                            current_section,
                        ):
                            section_ended = True
                            break

                meaningful_text = re.sub(
                    r"\s+",
                    " ",
                    page_text,
                ).strip()

                short_note_page = (
                    len(meaningful_text) < 1200
                    and (
                        "note" in meaningful_text.lower()
                        or "warning" in meaningful_text.lower()
                        or "caution" in meaningful_text.lower()
                    )
                )

                if section_ended and not short_note_page:
                    break

                for extra in page_chunks:

                    _append_hit(
                        hits,
                        extra,
                        min_score=h["score"] * 0.97,
                    )

        # -------------------------------------------------
        # TABLE CONTINUATION
        # -------------------------------------------------

        table_like = (
            "TABLE:" in h_text
            or "|" in h_text
            or re.search(
                r"\bcolumn\b",
                h_text,
                re.I,
            )
        )

        if table_like:

            current_p = h["page"]

            # Cap table expansion to prevent CPU/database bottlenecks
            for _ in range(1):

                current_p += 1

                page_chunks = get_cached_chunks(
                    h["source_file"],
                    current_p,
                )

                if not page_chunks:
                    break

                page_text = "\n".join(
                    c.get("parent_text")
                    or c.get("text", "")
                    for c in page_chunks
                )

                next_table_like = (
                    "TABLE:" in page_text
                    or "|" in page_text
                    or re.search(
                        r"\bcolumn\b",
                        page_text,
                        re.I,
                    )
                )

                if next_table_like:

                    for extra in page_chunks:

                        _append_hit(
                            hits,
                            extra,
                            min_score=h["score"] * 0.97,
                        )

                else:
                    break


def _dedupe_by_parent(
    hits: list[dict],
    limit: int,
) -> list[dict]:

    by_parent: dict[str, dict] = {}

    for h in sorted(
        hits,
        key=lambda x: x.get("score", 0),
        reverse=True,
    ):

        pid = (
            h.get("parent_id")
            or _chunk_key(h)
        )

        if pid not in by_parent:
            by_parent[pid] = h

    return list(by_parent.values())[:limit]


def _bm25_filter_dict(
    plan: QueryPlan,
) -> dict[str, Any] | None:

    f: dict[str, Any] = {}

    if plan.product_filter:
        f["product"] = plan.product_filter

    # doc_type is soft-boosted in retrieval rather than hard-filtered here
    if plan.exclude_demo:
        f["is_demo"] = False

    return f or None


def hybrid_search(
    store: VectorStore,
    query: str,
    top_k: int = RETRIEVAL_CANDIDATES,
    where: dict | None = None,
    bm25_filters: dict | None = None,
) -> list[dict[str, Any]]:

    dense = store.search(
        query,
        top_k=top_k,
        where=where,
    )

    if not USE_HYBRID_SEARCH:
        return dense

    bm25 = get_bm25_store()

    sparse = bm25.search(
        query,
        top_k=top_k,
        filters=bm25_filters,
    )

    if not sparse and not dense:
        return []

    if not sparse:
        return dense

    if not dense:
        return sparse

    return _rrf_fuse(
        dense,
        sparse,
        HYBRID_DENSE_WEIGHT,
        HYBRID_SPARSE_WEIGHT,
    )[:top_k]


def retrieve(
    question: str,
    store: VectorStore,
    final_k: int | None = None,
    history: list[dict] | None = None,
    plan: QueryPlan | None = None,
    product_filter: str | None = None,
    file_filter: str | None = None,
) -> tuple[list[dict[str, Any]], QueryPlan]:

    final_k = final_k or TOP_K

    plan = plan or route_query(
        question,
        history,
    )

    if product_filter:
        plan.product_filter = product_filter

    if file_filter:
        plan.chroma_where = {"source_file": {"$eq": file_filter}}
        if plan.exclude_demo:
            plan.chroma_where = {
                "$and": [
                    {"source_file": {"$eq": file_filter}},
                    {"is_demo": {"$eq": False}}
                ]
            }

    candidate_k = RETRIEVAL_CANDIDATES

    if plan.intent in (
        "definition",
        "field_detail",
        "architecture",
        "version_history",
    ):
        candidate_k = max(
            RETRIEVAL_CANDIDATES,
            22,
        )

    if (
        plan.focus_context
        or plan.intent == "how_to"
    ):
        candidate_k = max(
            RETRIEVAL_CANDIDATES,
            45,
        )

    where = plan.chroma_where

    bm25_f = _bm25_filter_dict(plan)
    if file_filter:
        bm25_f = bm25_f or {}
        bm25_f["source_file"] = file_filter

    merged: dict[str, dict] = {}

    per_query = max(
        5,
        candidate_k // max(
            len(plan.search_queries),
            1,
        ),
    )

    # Batch dense query matching for speed
    batch_dense_hits = store.batch_search(
        plan.search_queries,
        top_k=per_query,
        where=where,
    )

    bm25 = get_bm25_store()

    for idx, q in enumerate(plan.search_queries):
        dense_hits = batch_dense_hits[idx]

        if USE_HYBRID_SEARCH:
            sparse_hits = bm25.search(
                q,
                top_k=per_query,
                filters=bm25_f,
            )
            # Reciprocal Rank Fusion (RRF) fusion
            hits = _rrf_fuse(
                dense_hits,
                sparse_hits,
                HYBRID_DENSE_WEIGHT,
                HYBRID_SPARSE_WEIGHT,
            )[:per_query]
        else:
            hits = dense_hits

        for hit in hits:
            key = _chunk_key(hit)
            
            # Apply penalty to expanded queries so primary query takes precedence
            query_penalty = 1.0 if idx == 0 else 0.90
            effective_score = hit.get("score", 0.0) * query_penalty
            
            # Create a copy so we don't modify the original hit if it's shared
            hit_copy = dict(hit)
            hit_copy["score"] = effective_score
            
            if (
                key not in merged
                or effective_score
                > merged[key]["score"]
            ):
                merged[key] = hit_copy

    hits = list(merged.values())

    # =====================================================
    # SECTION-FIRST RETRIEVAL
    # =====================================================

    section_hits = []

    for hit in hits:

        body = (
            hit.get("parent_text")
            or hit.get("text", "")
        )

        matches = find_matching_sections(
            query=plan.search_question,
            text=body,
            min_score=0.45,
        )

        if not matches:
            continue

        # =====================================================
        # AMBIGUITY DETECTION
        # =====================================================

        strong_matches = [
            m
            for m in matches
            if m["score"] >= 0.72
        ]

        ambiguous_sections = []

        if (
            len(strong_matches) >= 2
            and abs(
                strong_matches[0]["score"]
                - strong_matches[1]["score"]
            ) < 0.12
        ):
            ambiguous_sections = [
                {
                    "heading": m["heading"],
                    "score": m["score"],
                }
                for m in strong_matches[:5]
            ]

        top_match = matches[0]

        complete_section = _complete_section_from_pages(
            store=store,
            hit=hit,
            heading=top_match["heading"],
        ) or extract_complete_section(
            text=body,
            heading=top_match["heading"],
        )

        if not complete_section or _retrieval_content_quality(complete_section) < 2:
            # ── FALLBACK: Section heading found but content not in same page ──
            # Instead of skipping, try fetching raw content from the next 2 pages.
            # This handles the common case where the heading is on a near-empty
            # page and content starts on the following page.
            fallback_text = ""
            for fallback_page in range(
                int(hit.get("page", 0)) + 1,
                int(hit.get("page", 0)) + 4,
            ):
                fc = store.get_chunks_for_page(hit.get("source_file", ""), fallback_page)
                if fc:
                    fallback_text += "\n" + _page_text(fc)
                if fallback_text.strip():
                    if _retrieval_content_quality(fallback_text) >= 2:
                        break

            if not fallback_text.strip():
                continue  # truly nothing found — skip

            complete_section = fallback_text.strip()

        boosted = {
            **hit,
            "parent_text": complete_section,
            "section_title": top_match["heading"],
            "section_score": top_match["score"],
            "ambiguous_sections": ambiguous_sections,
            "score": hit.get("score", 0)
            + (top_match["score"] * 3.0),
        }

        if top_match["score"] > 0.72:
            boosted["score"] += 5.0

        section_hits.append(boosted)

    if section_hits:
        hits.extend(section_hits)

    # =====================================================
    # SECTION BOOSTING
    # =====================================================

    if (
        is_configuration_question(plan.search_question)
        or plan.intent in (
            "how_to",
            "procedure",
        )
    ):
        boost_section_content(
            hits,
            plan.search_question,
        )

    _demote_boilerplate(hits)
    _demote_release_logs(hits, plan.intent)
    _demote_toc_and_history(hits)
    _boost_matching_doc_type(hits, plan.doc_type_filter)

    # =====================================================
    # RERANK
    # =====================================================

    # Cap candidates sent to CPU Cross-Encoder reranker to minimize latency
    rerank_limit = min(candidate_k, 8)
    hits = sorted(
        hits,
        key=lambda x: x.get("score", 0),
        reverse=True,
    )[:rerank_limit]

    reranked = rerank(
        plan.search_question,
        hits,
        top_k=rerank_limit,
    )

    # preserve section names for references
    for r in reranked:
        if r.get("section_title"):
            r["reference_label"] = (
                f"{r['section_title']} "
                f"(Page {r['page']})"
            )

    # =====================================================
    # PAGE EXPANSION
    # =====================================================

    if (
        plan.intent in (
            "definition",
            "architecture",
            "version_history",
            "how_to",
        )
        or plan.focus_context
    ):
        _expand_adjacent_pages(
            reranked,
            store,
            expand_further=True,
        )

    elif (
        plan.intent == "field_detail"
        and not plan.focus_context
    ):
        _expand_adjacent_pages(
            reranked,
            store,
            expand_further=False,
        )

    limit = (
        final_k + 2
        if plan.intent == "field_detail"
        else final_k
    )

    if plan.focus_context:

        reranked = focus_hits(
            reranked,
            plan.search_question,
        )

        # Use a larger limit for procedures to prevent truncation across duplicate manuals
        limit = max(
            limit,
            15,
        )

    return _dedupe_by_parent(
        reranked,
        limit,
    ), plan
