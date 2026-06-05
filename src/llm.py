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
1. Answer the question directly and professionally. Do not copy irrelevant background information, unrelated tables, or boilerplate text from the context.
2. If the user asks for a procedure, format, checklist, or "how-to", output only the specific, actionable steps or format details needed to complete that task.
3. Be helpful, conversational, and professional. Use the conversation history to resolve referential terms or follow-up context.
4. Stay strictly grounded in the context. Do not invent steps, configurations, directories, or facts. Do not bring in any external knowledge, brand names, company names (such as YourCompany, etc.), or product names unless they are explicitly mentioned in the context.
5. Never expand acronyms (like PROJECT_MODULE, PROJECT_NAME, WPP, SFS, PKI) using external knowledge or guessing. If the full name of an acronym is not explicitly written in the context, leave it as the acronym only.
6. For comparative, conceptual, or definition questions, synthesize a summarized brief answer or comparison using only the facts, roles, and descriptions of the components/products provided in the context.
7. Never substitute an unrelated procedure (e.g., uninstallation, installation, setup) when a specific test format, checklist, or procedure (such as a Factory Acceptance Test (FAT) format) is requested but not present in the context.
8. If the context does not contain the requested procedure/format/checklist, or lacks any relevant information to define or compare the subjects, you MUST return exactly: "I cannot find the instructions in the provided documents."
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
    history_str: str = "",
) -> str:
    history_section = f"\nConversation History:\n{history_str}" if history_str else ""
    
    q_lower = question.lower()
    is_comparison = any(w in q_lower for w in ("compare", "difference", "versus", "vs", "distinguish", "relationship", "comparison"))
    
    if is_comparison or intent in ("definition", "architecture", "general"):
        instruction_block = """- Answer the question by summarizing, defining, or comparing the subjects using only the facts described in the Context.
- Do not use any external knowledge. Never mention company names (such as YourCompany), brand names, or external facts not in the context.
- Never expand acronyms (e.g., PROJECT_MODULE, PROJECT_NAME, WPP) unless the context explicitly defines their full form. If not defined, leave them as acronyms.
- Synthesize a comparative summary or explain relationships between components (e.g., YOUR_PRODUCT) using only the details, roles, and descriptions provided in the text.
- If the context does not contain any relevant information about the requested components or subjects, say "I cannot find the instructions in the provided documents." """
    else:
        instruction_block = """- Extract only the specific, actionable steps, format details, or configurations requested. Do not copy unrelated tables, lists of ports, or background details.
- Stay strictly grounded in the provided Context. Do not invent steps, configurations, buttons, or directories. Do not mention brands or company names unless explicitly mentioned.
- Never substitute an unrelated procedure (e.g., uninstallation, installation, setup) when a specific test format, checklist, or procedure (such as a Factory Acceptance Test (FAT) format) is requested.
- If the context does not contain the exact instructions, format, or procedure, say "I cannot find the instructions in the provided documents." """

    return f"""
Context:
{context}
{history_section}

Question:
{question}

Instructions:
- Answer the question directly and concisely in natural human language. Use the Conversation History to understand follow-up references (e.g. pronouns like "its", "this", "it").
{instruction_block}

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
    history: list[dict] | None = None,
):

    context = _build_context(
        hits
    )

    if not context.strip():

        return (
            "The indexed documents do not contain "
            "enough information."
        )

    history_str = ""
    if history:
        for msg in history[-5:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            history_str += f"{role}: {msg.get('content')}\n"

    prompt = _build_prompt(
        question,
        context,
        plan.intent,
        history_str=history_str,
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