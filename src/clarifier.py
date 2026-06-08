"""Score-based clarification detection — no hardcoded topic lists.

Design: measure the CLARITY of a query using linguistic signals.
If the clarity score is below a threshold → ask for clarification.
This scales automatically to new products, topics, and query styles.

Clarity signals:
  + Has a known product name        → +4  (dynamic from vector store)
  + Has a question word             → +2  (what/how/why/where/which)
  + Has a specific action verb      → +1  (install/configure/create/...)
  + Query is long enough (≥ 6 words)→ +2  (more words = more context)
  + Query is somewhat long (≥ 4)    → +1
  + History has product context     → +3  (user already established scope)
  + History has prior user turn     → +1  (some conversational context)
  + Has a version/number reference  → +2  (specific artifact)
  + Has file/path reference         → +1

Threshold: score ≥ 3 → CLEAR (do not clarify), score < 3 → ask
"""

from __future__ import annotations

import re


# =========================================================
# ACTION VERBS PATTERN (covers any tech procedure intent)
# =========================================================

_ACTION_VERB_RE = re.compile(
    r"\b(install|configure|create|add|delete|remove|update|setup|deploy|enable|disable|"
    r"open|start|stop|restart|generate|register|login|connect|test|verify|check|find|"
    r"list|show|get|set|run|execute|download|upload|export|import|back|restore|"
    r"troubleshoot|debug|migrate|upgrade|uninstall|reset|change|edit|modify|view|"
    r"what|how|why|where|which|when|who|can|does|is|are|give|tell|explain|describe)\b",
    re.I,
)

_QUESTION_WORD_RE = re.compile(
    r"^(what|how|why|where|which|when|who|can|does|is|are)\b",
    re.I,
)

_VERSION_OR_NUMBER_RE = re.compile(
    r"\b\d+[\.\-]\d+\b|\bv\d+\b|\b\d{4}\b"
)

_PATH_OR_FILE_RE = re.compile(
    r"[A-Za-z]:\\|/[a-z]+/|\.[a-zA-Z]{2,5}\b"
)


# =========================================================
# HELPERS
# =========================================================

def _active_products() -> list[str]:
    try:
        from src.doc_registry import get_active_products
        return get_active_products()
    except Exception:
        return []


def _query_clarity_score(question: str, history: list[dict] | None) -> int:
    """
    Score how clear/specific a query is.
    Higher = more clear. Returns int score.
    """
    q_lower = question.lower()
    words = q_lower.split()
    products = _active_products()
    score = 0

    # ── Signal 1: Product name in current question (most important)
    for prod in products:
        if re.search(rf"\b{re.escape(prod)}\b", q_lower):
            score += 4
            break

    # ── Signal 2: Question word (what/how/why/where)
    if _QUESTION_WORD_RE.match(q_lower.strip()):
        score += 2

    # ── Signal 3: Specific action verb or tech verb
    if _ACTION_VERB_RE.search(q_lower):
        score += 1

    # ── Signal 4: Query length
    if len(words) >= 6:
        score += 2
    elif len(words) >= 4:
        score += 1

    # ── Signal 5: Version/number reference (specific artifact)
    if _VERSION_OR_NUMBER_RE.search(question):
        score += 2

    # ── Signal 6: File path reference
    if _PATH_OR_FILE_RE.search(question):
        score += 1

    # ── Signal 7: History has a product name (user established product scope)
    if history:
        for msg in history[-6:]:
            content = msg.get("content", "").lower()
            for prod in products:
                if re.search(rf"\b{re.escape(prod)}\b", content):
                    score += 3
                    break
            else:
                continue
            break

    # ── Signal 8: History has prior user turns (conversational context exists)
    if history:
        prior_user = [m for m in history if m.get("role") == "user"]
        if len(prior_user) >= 1:
            score += 1

    return score


def _build_clarification_message(question: str, history: list[dict] | None) -> str:
    """
    Build a targeted clarification question based on what signals are missing.
    No hardcoded topic list — derived entirely from what the query is missing.
    """
    q_lower = question.lower()
    products = _active_products()
    available = [p for p in products if p not in ("unknown", "demo")]

    has_product = any(
        re.search(rf"\b{re.escape(p)}\b", q_lower) for p in products
    )
    has_history_context = bool(history and len([m for m in history if m.get("role") == "user"]) >= 1)
    is_short = len(question.split()) <= 3

    if not has_product and available:
        product_list = " / ".join(p.upper() for p in available[:6])
        if is_short and not has_history_context:
            return (
                f"Could you give me a bit more context? "
                f"Which product are you asking about ({product_list}), "
                f"and what specifically would you like to know?"
            )
        return (
            f"Which product are you asking about — {product_list}? "
            f"That'll help me search the right documentation for you."
        )

    if is_short and not has_history_context:
        return (
            f"Could you provide more detail about what you need for **{question.strip()}**? "
            f"For example, are you looking for installation steps, configuration, troubleshooting, or something else?"
        )

    return (
        f"I want to make sure I give you the right answer. "
        f"Could you clarify what specifically you need regarding **{question.strip()}**?"
    )


# =========================================================
# PUBLIC API
# =========================================================

_CLARITY_THRESHOLD = 3  # queries scoring below this need clarification


def should_clarify(
    question: str,
    history: list[dict] | None = None,
    plan=None,
) -> bool:
    """
    Decide if we need to ask the user for clarification.
    Score-based, no hardcoded topic lists — instant, no Ollama call.
    """
    # If a product filter is already active from the header dropdown, skip clarification
    if plan is not None and getattr(plan, "product_filter", None):
        return False

    score = _query_clarity_score(question, history)
    return score < _CLARITY_THRESHOLD


def generate_clarification(
    question: str,
    products: list[str] | None = None,
    history: list[dict] | None = None,
) -> str:
    """
    Generate a targeted clarification question based on missing signals.
    Instant — no Ollama call.
    """
    return _build_clarification_message(question, history)


def satisfaction_followup() -> str:
    """Standard satisfaction follow-up appended after every answer."""
    return (
        "\n\n---\n"
        "*Does this answer your question? If you need more detail on any step, just ask.*"
    )
