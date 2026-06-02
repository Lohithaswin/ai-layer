"""
Enterprise LLM orchestration
for section-aware manual RAG.
"""

from __future__ import annotations

import re

import httpx

from src.answer_formatter import (
    clean_procedural_answer,
)
from src.config import (
    MAX_CONTEXT_CHARS,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_PREDICT,
    OLLAMA_TIMEOUT,
)
from src.verifier import (
    apply_verifier,
)


# =========================================================
# OLLAMA SUPPORT
# =========================================================

class OllamaTimeoutError(Exception):
    """Raised when Ollama does not respond within timeout."""


def ollama_available() -> bool:
    try:
        r = httpx.get(
            f"{OLLAMA_BASE_URL}/api/tags",
            timeout=5.0,
        )
        return r.status_code == 200
    except Exception:
        return False


def generate(
    prompt: str,
    system: str | None = None,
) -> str:

    payload: dict = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    }

    if system:
        payload["system"] = system

    timeout = httpx.Timeout(
        OLLAMA_TIMEOUT,
        connect=30.0,
    )

    try:

        with httpx.Client(
            timeout=timeout
        ) as client:

            r = client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
            )

            r.raise_for_status()

            return (
                r.json()
                .get("response", "")
                .strip()
            )

    except httpx.ReadTimeout as e:

        raise OllamaTimeoutError(
            f"Ollama did not finish within "
            f"{int(OLLAMA_TIMEOUT)}s."
        ) from e


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are an enterprise technical documentation assistant.

Your responsibilities:
- Answer ONLY using provided context
- NEVER invent steps, buttons, UI, menus, or configuration values
- NEVER hallucinate missing information
- NEVER merge unrelated sections
- NEVER repeat information
- NEVER mention PDF/page/chunk/retrieval details
- NEVER output citations like [1]
- NEVER say "following figure"
- NEVER summarize procedures unless explicitly asked
- Preserve numbered procedural steps exactly
- If procedural steps continue, continue until the next section begins
- Keep section continuity intact
- Prefer exact terminology from the manuals
- If answer is missing from context, clearly say so

Procedural rules:
- Keep original order
- Preserve step numbering
- Do not omit intermediate steps
- Do not compress configuration procedures
- Include all required values/settings if present

Formatting rules:
- Clean readable markdown
- No duplicated paragraphs
- No repeated steps
- No source references
- No retrieval metadata
- No page references
"""


# =========================================================
# CONTEXT BUILDING
# =========================================================

def _build_context(
    hits: list[dict],
) -> str:

    sections = []

    seen = set()

    for hit in hits:

        body = (
            hit.get("parent_text")
            or hit.get("text", "")
        ).strip()

        if not body:
            continue

        normalized = re.sub(
            r"\s+",
            " ",
            body.lower(),
        )

        if normalized in seen:
            continue

        seen.add(normalized)

        sections.append(body)

    context = "\n\n".join(
        sections
    )

    return context[
        :MAX_CONTEXT_CHARS
    ]


# =========================================================
# PROMPT BUILDING
# =========================================================

def _build_prompt(
    question: str,
    context: str,
    intent: str,
) -> str:

    procedural = (
        intent == "how_to"
    )

    instructions = []

    if procedural:

        instructions.extend(
            [
                "Return COMPLETE procedures.",
                "Continue until next section begins.",
                "Preserve numbering exactly.",
                "Do not summarize steps.",
                "Do not omit settings or values.",
            ]
        )

    else:

        instructions.extend(
            [
                "Answer precisely.",
                "Use exact terminology from context.",
            ]
        )

    joined = "\n".join(
        f"- {x}"
        for x in instructions
    )

    return f"""
Question:
{question}

Instructions:
{joined}

Context:
{context}

Answer:
""".strip()


# =========================================================
# MAIN GENERATION
# =========================================================

def generate_answer(
    llm,
    question: str,
    hits: list[dict],
    plan,
):

    context = _build_context(
        hits
    )

    if not context.strip():

        return (
            "The indexed documents do not contain "
            "enough information."
        )

    prompt = _build_prompt(
        question,
        context,
        plan.intent,
    )

    raw = generate(
        prompt=prompt,
        system=SYSTEM_PROMPT,
    )

    cleaned = (
        clean_procedural_answer(
            raw
        )
    )

    verified, _ = apply_verifier(
        answer=cleaned,
        hits=hits,
        intent=plan.intent,
        subjects=plan.subjects,
        context=context,
        question=question,
    )

    verified = (
        clean_procedural_answer(
            verified
        )
    )

    if not verified.strip():

        return (
            "The indexed documents do not contain "
            "enough information."
        )

    return verified.strip()