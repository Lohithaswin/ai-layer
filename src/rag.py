"""Enterprise section-aware RAG pipeline."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from src.answer_formatter import (
    clean_procedural_answer,
)
from src.config import (
    USE_HYBRID_SEARCH,
    USE_RERANKER,
)
from src.llm import (
    OllamaTimeoutError,
    generate_answer,
    ollama_available,
)
from src.retrieval import retrieve
from src.vector_store import (
    VectorStore,
    get_vector_store,
)

# =========================================================
# SOURCE MODEL
# =========================================================

@dataclass
class Source:
    ref: int
    source_file: str
    page: int
    excerpt: str
    score: float
    section: str = ""
    source_type: str = "Local"
    product: str = "unknown"

    context_before: str = ""
    context_after: str = ""


# =========================================================
# RESPONSE MODEL
# =========================================================

@dataclass
class ChatResponse:
    answer: str

    sources: list[Source] = field(
        default_factory=list
    )

    used_llm: bool = True

    note: str | None = None

    processing_time_ms: float = 0.0

    retrieval_time_ms: float = 0.0

    num_sources_retrieved: int = 0

    num_sources_used: int = 0

    question_intent: str = "general"

    retrieval_mode: str = ""

    options: list[str] = field(
        default_factory=list
    )


# =========================================================
# HELPERS
# =========================================================

def _context_text(
    hit: dict,
) -> str:

    return (
        hit.get("parent_text")
        or hit.get("text", "")
    )


def _clean_pdf_boilerplate(
    text: str,
) -> str:
    """
    Remove PDF boilerplate.
    """

    lines = text.split("\n")

    cleaned = []

    for line in lines:

        stripped = line.strip()

        if not stripped:
            continue

        # Generic classification/confidentiality label match (exact)
        if stripped.lower() in ("restricted", "confidential", "internal use", "public", "proprietary"):
            continue
        # Generic copyright/rights match (typical short footer line, not a long paragraph)
        if len(stripped) < 120 and ("all rights reserved" in stripped.lower() or "©" in stripped or "copyright" in stripped.lower()):
            continue
        # Generic document title match (short lines starting with YOUR_PRODUCT/SFS/PKI and ending in Guide/Manual/Notes/Log/Overview)
        if len(stripped) < 80 and re.match(r"^(?:PROJECT_NAME|PROJECT_MODULE|SFS|PKI)\s+.*(?:Guide|Manual|Notes|Log|Overview)$", stripped, re.I):
            continue

        # figure/table labels
        if re.match(
            r"^(Figure|Table)\s+\d+[:.]?$",
            stripped,
            re.I,
        ):
            continue

        # page labels
        if re.match(
            r"^Page\s+\d+$",
            stripped,
            re.I,
        ):
            continue

        # version footer/header
        if re.match(
            r"^PROJECT_NAME[A-Z]*\s+(Installation|User|Manual|Guide|Security).*v\d+",
            stripped,
            re.I,
        ):
            continue

        # figure wording cleanup
        stripped = re.sub(
            r"as shown in (the )?(following|below) figure",
            "as illustrated in the manual",
            stripped,
            flags=re.I,
        )

        stripped = re.sub(
            r"shown in the following figure",
            "illustrated in the manual",
            stripped,
            flags=re.I,
        )

        # useless references
        if re.search(
            r"this step is described in detail in",
            stripped,
            re.I,
        ):
            continue

        cleaned.append(stripped)

    return "\n".join(cleaned).strip()


def _similar(
    a: str,
    b: str,
) -> float:

    return SequenceMatcher(
        None,
        a.lower(),
        b.lower(),
    ).ratio()


# Removed _remove_duplicate_content as it destroys tables and checklists


def _remove_inline_citations(
    answer: str,
) -> str:
    """
    Remove inline citations.
    """

    answer = re.sub(
        r"\s*\[\d+\]",
        "",
        answer,
    )

    answer = re.sub(
        r"^\s*\[\d+\]\s*$",
        "",
        answer,
        flags=re.MULTILINE,
    )

    return answer.strip()


# =========================================================
# SOURCE FORMAT
# =========================================================

def _content_quality_score(text: str) -> int:
    """
    Score-based content quality check — no hardcoded char limits.
    Measures independent signals of substantive content.
    Returns int: 0 = heading-only, higher = more content.
    """
    score = 0

    # Numbered procedural steps (1. step / 1) step)
    if re.search(r"^\s*\d+[.)]\s+\w", text, re.M):
        score += 3

    # Bullet points / dash lists
    if re.search(r"^\s*[-*•]\s+\w", text, re.M):
        score += 2

    # Multiple complete sentences (ends with . or : and continues)
    sentences = re.findall(r"[.!?]\s+[A-Z]", text)
    if len(sentences) >= 2:
        score += 2
    elif len(sentences) == 1:
        score += 1

    # Key: value style content (config/table rows)
    if re.search(r"\w[\w\s]{2,30}:\s+\w", text):
        score += 1

    # File paths or registry paths
    if re.search(r"[A-Za-z]:\\|/[a-z]+/|HKEY_|\.config\b|\.xml\b|\.json\b", text):
        score += 2

    # Table-like rows with pipe separators
    if text.count("|") >= 3:
        score += 2

    # Enough words to be substantive
    word_count = len(text.split())
    if word_count >= 40:
        score += 2
    elif word_count >= 20:
        score += 1

    return score


_CONTENT_QUALITY_THRESHOLD = 2  # below this = heading-only, no substantive content


def _format_context(
    hits: list[dict],
) -> tuple[str, list[Source]]:

    sources: list[Source] = []

    blocks: list[str] = []

    for i, hit in enumerate(
        hits,
        start=1,
    ):

        raw_body = _context_text(
            hit
        )

        clean_body = (
            _clean_pdf_boilerplate(
                raw_body
            )
        )

        section_name = (
            hit.get("section_title")
            or hit.get("section_match")
            or ""
        )

        heading_only = _content_quality_score(clean_body) < _CONTENT_QUALITY_THRESHOLD

        # Build excerpt (shown in source card — always 600 chars)
        if section_name:
            excerpt = (
                f"[SECTION: {section_name}]\n"
                + clean_body[:600]
            )
        else:
            excerpt = clean_body[:600]

        if len(clean_body) > 600:
            excerpt += "..."

        sources.append(
            Source(
                ref=i,
                source_file=hit.get(
                    "source_file",
                    "",
                ),
                page=hit.get(
                    "page",
                    0,
                ),
                excerpt=excerpt,
                score=round(
                    hit.get(
                        "relevance",
                        hit.get(
                            "score",
                            0,
                        ),
                    ),
                    4,
                ),
                section=(
                    hit.get("section_title")
                    or hit.get("section_match")
                    or ""
                ),
                product=hit.get("product", "unknown"),
            )
        )

        heading_only = _content_quality_score(clean_body) < _CONTENT_QUALITY_THRESHOLD

        # Build LLM context block
        relevance = hit.get("relevance", hit.get("score", 0))
        if heading_only and section_name and len(clean_body.split()) < 30 and relevance < 0.6:
            # Only block LLM on weak/accidental heading matches — not high-confidence matches
            blocks.append(
                f"[SECTION: {section_name}]\n{clean_body}\n"
                f"[NOTE: Section heading found but no body content was indexed for this section. "
                f"Do NOT invent content for '{section_name}'.]\n"
            )
        else:
            if section_name:
                blocks.append(f"[SECTION: {section_name}]\n{clean_body}")
            else:
                blocks.append(clean_body)

    return (
        "\n\n".join(blocks),
        sources,
    )


def _retrieval_mode_label(
    product_filter: str | None = None,
) -> str:

    parts = []

    if USE_HYBRID_SEARCH:
        parts.append("hybrid")
    else:
        parts.append("dense")

    if USE_RERANKER:
        parts.append("rerank")

    if product_filter:
        parts.append(
            f"filter:{product_filter}"
        )

    return "+".join(parts)


# =========================================================
# MAIN ASK
# =========================================================

def _try_role_sql_direct(
    question: str,
    store,
    start_time: float,
    retrieval_start: float,
    retrieval_time: float,
    intent: str,
    mode: str,
    product_filter: str | None = None,
) -> "ChatResponse | None":
    """
    Shortcut: if the question is a role/attribute relational query,
    answer it directly from the SQL DB — NO LLM call, no token limits,
    no 413 errors, instant and accurate.

    Gating logic:
    - Specific structured intents (GET_ATTRIBUTES_FOR_ROLE, GET_ROLES_FOR_ATTRIBUTE,
      COUNT_ATTRIBUTES) always bypass the LLM — they are unambiguous.
    - Ambiguous intents (DESCRIBE_ATTRIBUTE, GENERAL_ROLE_SEARCH) only route to the
      role DB when the user has explicitly selected the "Roles" filter in the UI
      (product_filter == 'roles'). Otherwise they fall through to the normal
      document search so general queries like "compare FAT and SAT format" are
      answered from the PDFs, not the role database.

    Returns a ChatResponse if handled, or None to fall through to the LLM.
    """
    from src.intent_router import route_role_intent

    router_result = route_role_intent(question)   # keep original casing — ILIKE handles case on DB side

    sql_intent = router_result["intent"]
    entity     = router_result["entity"]

    if sql_intent == "GENERAL_SEARCH" or not entity:
        return None  # not a role query — let LLM handle it

    # Ambiguous intents: only hit the role DB if the user explicitly chose
    # the Roles filter. Otherwise fall through to normal document retrieval.
    _AMBIGUOUS_INTENTS = {"DESCRIBE_ATTRIBUTE", "GENERAL_ROLE_SEARCH"}
    _roles_filter_active = (product_filter or "").lower() in ("roles", "role")
    if sql_intent in _AMBIGUOUS_INTENTS and not _roles_filter_active:
        return None

    sql_answer = ""
    try:
        if sql_intent == "GET_ATTRIBUTES_FOR_ROLE" and hasattr(store, "get_attributes_for_role"):
            sql_answer = store.get_attributes_for_role(entity)

        elif sql_intent == "GET_ROLES_FOR_ATTRIBUTE" and hasattr(store, "get_roles_for_attribute"):
            sql_answer = store.get_roles_for_attribute(entity)

        elif sql_intent == "COUNT_ATTRIBUTES" and hasattr(store, "count_role_attributes"):
            sql_answer = store.count_role_attributes(entity)

        elif sql_intent == "DESCRIBE_ATTRIBUTE" and hasattr(store, "describe_attribute"):
            sql_answer = store.describe_attribute(entity)
            # "Describe X" may refer to a role, not an attribute — try role lookup as fallback
            if not sql_answer and hasattr(store, "get_attributes_for_role"):
                sql_answer = store.get_attributes_for_role(entity)

        elif sql_intent == "GENERAL_ROLE_SEARCH" and hasattr(store, "query_role_database"):
            # A role question that didn't match specific intents; search keywords directly
            sql_answer = store.query_role_database([entity])

        # Final fallback — general keyword search across all role_mappings
        if not sql_answer and hasattr(store, "query_role_database"):
            sql_answer = store.query_role_database([entity])

        # If still nothing, return a clean "not found" answer instead of
        # sending the query to the LLM (which would hit rate limits and use
        # doc chunks that have nothing to do with role data)
        if not sql_answer:
            return ChatResponse(
                answer=f"No role or attribute matching **'{entity}'** was found in the PROJECT_NAME role database.\n\n"
                       f"Try:\n- Checking the exact role name spelling\n"
                       f"- Using the section search bar to browse all roles and attributes",
                sources=[],
                used_llm=False,
                note="role_not_found",
                processing_time_ms=(time.time() - start_time) * 1000,
                retrieval_time_ms=retrieval_time,
                num_sources_retrieved=0,
                num_sources_used=0,
                question_intent=sql_intent.lower(),
                retrieval_mode="sql_direct",
                options=[],
            )

    except Exception as e:
        print(f"[RAG] role SQL direct failed ({sql_intent}, '{entity}'): {e}")
        return None  # fall through to LLM only on unexpected error


    total_time = (time.time() - start_time) * 1000
    return ChatResponse(
        answer=sql_answer,
        sources=[],
        used_llm=False,
        note="role_sql_direct",
        processing_time_ms=total_time,
        retrieval_time_ms=retrieval_time,
        num_sources_retrieved=0,
        num_sources_used=0,
        question_intent=sql_intent.lower(),
        retrieval_mode="sql_direct",
        options=[],
    )


def ask(
    question: str,
    store: VectorStore | None = None,
    append_footer: bool = False,
    history: list[dict] | None = None,
    product_filter: str | None = None,
    file_filter: str | None = None,
) -> ChatResponse:

    from src.query_context import rewrite_affirmation_query
    question = rewrite_affirmation_query(question, history)

    start_time = time.time()

    store = (
        store
        or get_vector_store()
    )

    retrieval_start = time.time()

    # =====================================================
    # ROLE SQL SHORTCUT — no LLM, no token limits, instant
    # =====================================================
    # Run intent detection BEFORE touching the vector store.
    # If this is a role/attribute relational query, answer
    # directly from PostgreSQL and return immediately.
    _role_resp = _try_role_sql_direct(
        question=question,
        store=store,
        start_time=start_time,
        retrieval_start=retrieval_start,
        retrieval_time=0.0,
        intent="general",
        mode="sql_direct",
        product_filter=product_filter,
    )
    if _role_resp is not None:
        return _role_resp

    hits, plan = retrieve(
        question,
        store,
        history=history,
        product_filter=product_filter,
        file_filter=file_filter,
    )
    # =====================================================
    # AMBIGUOUS SECTION / ALTERNATE OPTIONS DETECTION
    # =====================================================
    options = []
    for hit in hits:
        amb_secs = hit.get("ambiguous_sections", [])
        top_heading = hit.get("section_title")
        for sec in amb_secs:
            h = sec["heading"]
            if h != top_heading and h not in options:
                options.append(h)

    if hits:
        best_score = hits[0].get("score", 0.0)
        for h in hits[1:]:
            h_score = h.get("score", 0.0)
            if h_score >= best_score * 0.85:
                label = h.get("section_title")
                if label and label not in options:
                    options.append(label)

    retrieval_time = (
        time.time()
        - retrieval_start
    ) * 1000

    intent = plan.intent

    mode = _retrieval_mode_label(
        plan.product_filter
    )

    # =====================================================
    # NO RESULTS
    # =====================================================

    if not hits:

        total_time = (
            time.time()
            - start_time
        ) * 1000

        return ChatResponse(
            answer=(
                "The indexed documents "
                "do not contain enough information."
            ),
            sources=[],
            used_llm=False,
            note="no_results",
            processing_time_ms=total_time,
            retrieval_time_ms=retrieval_time,
            num_sources_retrieved=0,
            question_intent=intent,
            retrieval_mode=mode,
            options=options,
        )

    # =====================================================
    # FORMAT CONTEXT
    # =====================================================

    context, sources = _format_context(
        hits
    )

    # =====================================================
    # OLLAMA OFFLINE
    # =====================================================

    if not ollama_available():

        total_time = (
            time.time()
            - start_time
        ) * 1000

        summary = (
            "Ollama is not running.\n\n"
            "Start Ollama:\n"
            "`ollama serve`\n\n"
            "Retrieved context:\n\n"
            + context
        )

        return ChatResponse(
            answer=summary,
            sources=sources,
            used_llm=False,
            note="ollama_offline",
            processing_time_ms=total_time,
            retrieval_time_ms=retrieval_time,
            num_sources_retrieved=len(
                hits
            ),
            num_sources_used=len(
                sources
            ),
            question_intent=intent,
            retrieval_mode=mode,
            options=options,
        )

    # =====================================================
    # GENERATION
    # =====================================================

    note: str | None = None

    try:

        answer = generate_answer(
            llm=None,
            question=question,
            hits=hits,
            plan=plan,
            history=history,
        )

        # final cleanup only
        answer = (
            clean_procedural_answer(
                answer
            )
        )

        answer = (
            _remove_inline_citations(
                answer
            )
        )

        # Do not run _remove_duplicate_content on the LLM's generated answer
        # (it removes procedural steps). Cleanup is handled by answer_formatter only.
        pass

    except OllamaTimeoutError as e:

        total_time = (
            time.time()
            - start_time
        ) * 1000

        summary = (
            f"{e}\n\n"
            "Showing retrieved excerpts instead:\n\n"
            + context
        )

        return ChatResponse(
            answer=summary,
            sources=sources,
            used_llm=False,
            note="ollama_timeout",
            processing_time_ms=total_time,
            retrieval_time_ms=retrieval_time,
            num_sources_retrieved=len(
                hits
            ),
            num_sources_used=len(
                sources
            ),
            question_intent=intent,
            retrieval_mode=mode,
            options=options,
        )

    # =====================================================
    # FINAL RESPONSE
    # =====================================================

    total_time = (
        time.time()
        - start_time
    ) * 1000

    return ChatResponse(
        answer=answer,
        sources=sources,
        used_llm=True,
        note=note,
        processing_time_ms=total_time,
        retrieval_time_ms=retrieval_time,
        num_sources_retrieved=len(
            hits
        ),
        num_sources_used=len(
            sources
        ),
        question_intent=intent,
        retrieval_mode=mode,
        options=options,
    )