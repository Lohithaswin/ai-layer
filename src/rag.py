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


def _remove_duplicate_content(
    text: str,
) -> str:
    """
    Remove semantic duplicates.
    """

    lines = text.split("\n")

    unique: list[str] = []

    for line in lines:

        stripped = line.strip()

        if not stripped:
            continue

        duplicate = False

        for existing in unique:

            similarity = _similar(
                stripped,
                existing,
            )

            if similarity > 0.88:

                duplicate = True

                # keep richer line
                if (
                    len(stripped)
                    > len(existing)
                ):
                    unique.remove(
                        existing
                    )

                    unique.append(
                        stripped
                    )

                break

        if not duplicate:
            unique.append(stripped)

    return "\n".join(unique)


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

        clean_body = (
            _remove_duplicate_content(
                clean_body
            )
        )

        section_name = (
            hit.get("section_title")
            or hit.get("section_match")
            or ""
        )

        if section_name:
            excerpt = (
                f"[SECTION: {section_name}]\n"
                + clean_body[:400]
            )
        else:
            excerpt = clean_body[:400]

        if len(clean_body) > 400:
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

        # clean manual text only
        if section_name:
            blocks.append(
                f"[SECTION: {section_name}]\n{clean_body}"
            )
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

def ask(
    question: str,
    store: VectorStore | None = None,
    append_footer: bool = False,
    history: list[dict] | None = None,
    product_filter: str | None = None,
    file_filter: str | None = None,
) -> ChatResponse:

    start_time = time.time()

    store = (
        store
        or get_vector_store()
    )

    retrieval_start = time.time()

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

        # Do not clean PDF-level boilerplate headers/footers on the LLM's generated response
        pass

        answer = (
            _remove_duplicate_content(
                answer
            )
        )

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