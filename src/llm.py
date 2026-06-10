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
    import src.config as _cfg
    if not _cfg.GROQ_API_KEY:
        return False
    try:
        r = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {_cfg.GROQ_API_KEY}"},
            timeout=5.0,
        )
        return r.status_code == 200
    except Exception:
        return False


def generate(
    prompt: str,
    system: str | None = None,
) -> str:
    import src.config as _cfg

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {
        "model": _cfg.OLLAMA_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": _cfg.OLLAMA_NUM_PREDICT,
        "stream": False,
    }

    timeout = httpx.Timeout(
        _cfg.OLLAMA_TIMEOUT,
        connect=30.0,
    )

    try:

        with httpx.Client(
            timeout=timeout,
            verify=False,
            headers={"Authorization": f"Bearer {_cfg.GROQ_API_KEY}"}
        ) as client:

            r = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
            )

            r.raise_for_status()

            return (
                r.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

    except httpx.ReadTimeout as e:

        raise OllamaTimeoutError(
            f"Groq API did not finish within "
            f"{int(_cfg.OLLAMA_TIMEOUT)}s."
        ) from e


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are an enterprise technical support chatbot for YOUR_PRODUCT, SFS, MFA and related products.
Your goal is to answer the user's question directly, clearly, and completely in natural human language, based ONLY on the provided context.

Follow these rules STRICTLY:
1. Answer the question directly and professionally. Do not include irrelevant background information.
2. If the user asks for a procedure or "how-to", scan the ENTIRE context from top to bottom and output ALL numbered steps in sequential order (1, 2, 3, 4...). Steps may be split across separate context blocks or pages — collect them all. If the user asks for a format, table, or checklist, provide the exact format without forcing it into numbered steps.
3. Be helpful, conversational, and professional. Use the conversation history to resolve referential terms or follow-up context (e.g. "give steps" refers to the previous topic discussed).
4. Stay strictly grounded in the context. Do not invent steps, configurations, directories, or facts. Do not bring in any external knowledge, brand names, company names, or product names unless explicitly mentioned in the context.
5. Never expand acronyms (like PROJECT_MODULE, PROJECT_NAME, WPP, SFS, PKI, MFA) using external knowledge. If the full name is not written in the context, leave it as the acronym.
6. For comparative, conceptual, or definition questions, synthesize a summarized answer using ONLY the facts in the provided context.
7. CRITICAL — Never substitute a different procedure: if the user asks for a specific format/checklist (e.g., "FAT format"), do NOT answer with a different procedure (e.g., SAT steps). If the exact content is not in the context, say you cannot find it.
8. If the provided context contains a table (indicated by TABLE: tags or tabular columns), ALWAYS format your output as a proper Markdown table.
9. CRITICAL — If the context does not contain the requested procedure/format/checklist, or lacks relevant information, return exactly: "I cannot find the requested information in the provided documents."
"""


# =========================================================
# CONTEXT BUILDING
# =========================================================

_BOILERPLATE_RE = re.compile(
    r"^("
    r"PROJECT_NAME.*v\d+.*|PROJECT_MODULE.*v\d+.*|"
    r"PROJECT_MODULE\s+\w.*(?:Guide|Manual)|"
    r"PROJECT_NAME\s+\w.*(?:Guide|Manual)|"
    r"\u00a9.*|©.*|"
    r".*All\s+rights\s+reserved.*|"
    r"Restricted|Confidential|"
    r"Page\s+\d+|"
    r"Figure\s+\d+[.:]?|"
    r"Table\s+\d+[.:]?"
    r")$",
    re.I,
)


def _strip_boilerplate_lines(text: str) -> str:
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if _BOILERPLATE_RE.match(s):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _build_context(
    hits: list[dict],
) -> str:

    seen_files: list[str] = []
    file_hits: dict[str, list[dict]] = {}
    for hit in hits:
        sf = hit.get("source_file", "")
        if sf not in file_hits:
            seen_files.append(sf)
            file_hits[sf] = []
        file_hits[sf].append(hit)

    for sf in seen_files:
        file_hits[sf].sort(key=lambda h: int(h.get("page", 0)))

    ordered_hits: list[dict] = []
    for sf in seen_files:
        ordered_hits.extend(file_hits[sf])

    sections = []
    seen = set()

    for hit in ordered_hits:

        body = (
            hit.get("parent_text")
            or hit.get("text", "")
        ).strip()

        if not body:
            continue

        body = _strip_boilerplate_lines(body)

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
- Do not use any external knowledge. Never mention company names, brand names, or external facts not in the context.
- Never expand acronyms (e.g., PROJECT_MODULE, PROJECT_NAME, WPP, MFA, SFS) unless the context explicitly defines their full form.
- If the context does not contain any relevant information, say "I cannot find the requested information in the provided documents." """
    else:
        instruction_block = """- If the user asks for steps or a procedure, the context may contain steps split across multiple blocks or pages. Scan the ENTIRE context from top to bottom and collect ALL numbered steps in sequential order (1, 2, 3, 4, 5...).
- If the context contains duplicate or highly similar steps across different sections, MERGE them into a single, clean procedure. STRICTLY deduplicate overlapping instructions so that a step is not repeated twice. Do NOT say "From the first section..." or use conversational filler like "Here is the merged procedure". Start the list immediately.
- Stay strictly grounded in the provided Context. If the context uses a specific example (e.g., "RadiusTestUser", "192.168.x.x"), generalize it to "the appropriate user" or "the IP address" unless the user explicitly asks for the example. Do not mix troubleshooting steps for unrelated components (like STC-1) unless they directly answer the user's question.
- CRITICAL: If the user asked for a specific format, table, or checklist (e.g., FAT format, SAT checklist), only provide that exact format from context. Do not append unrelated numbered steps.
- If the context does not contain the exact instructions, format, or procedure, say "I cannot find the requested information in the provided documents." """

    return f"""
Context:
{context}
{history_section}

Question:
{question}

Instructions:
- Answer the question directly and completely in natural human language. Use the Conversation History to understand follow-up references (e.g. pronouns like "its", "this", "it", or commands like "give steps" which refer to the previous topic).
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
            content = msg.get('content', '')
            if role == "Assistant" and len(content) > 500:
                content = content[:500] + "... [truncated]"
            history_str += f"{role}: {content}\n"

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