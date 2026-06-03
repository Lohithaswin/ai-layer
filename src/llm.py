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
You are an enterprise technical support chatbot.
Your goal is to answer the user's question directly, clearly, and concisely in natural human language, based ONLY on the provided context.

Follow these rules:
1. Answer the question directly. Do not copy irrelevant background information, unrelated tables, or boilerplate text from the context.
2. If the user asks for a procedure or "how-to", output only the specific, actionable steps needed to complete that task.
3. Be helpful, concise, and professional. Write like a human assistant, not like a document search dump.
4. Stay strictly grounded in the context. Do not invent steps, configurations, buttons, or directories. If the context does not contain the answer, say: "I cannot find the instructions in the provided documents."
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
    return f"""
Context:
{context}

Question:
{question}

Instructions:
- Answer the question directly and concisely in natural human language.
- Extract only the relevant information or configuration steps asked for. Do not include unrelated tables, network ports, or background details.
- Stay strictly grounded in the provided Context. If the context does not contain the exact instructions or answer, say "I cannot find the instructions in the provided documents."

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