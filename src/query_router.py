"""Single query-understanding step: subject, intent, metadata filters, search queries."""

from __future__ import annotations

import re
from typing import Any
from dataclasses import dataclass, field

from src.query_context import collect_subjects, is_follow_up, resolve_question
from src.context_focus import is_procedure_question, should_focus_context
from src.query_expand import (
    expanded_queries,
    is_architecture_question,
    is_definition_question,
    is_field_detail_question,
    is_version_history_question,
    is_comparison_question,
)

_SHORT_ACRONYM_RE = re.compile(r"^[A-Za-z]{2,8}\??$")


@dataclass
class QueryPlan:
    original_question: str
    search_question: str
    subjects: list[str]
    intent: str
    product_filter: str | None = None
    doc_type_filter: str | None = None
    exclude_demo: bool = True
    search_queries: list[str] = field(default_factory=list)
    chroma_where: dict | None = None
    focus_context: bool = False


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


def _detect_intent(question: str, search_q: str) -> str:
    if is_version_history_question(question) or is_version_history_question(search_q):
        return "version_history"
    if is_definition_question(question) or is_definition_question(search_q):
        return "definition"
    if is_field_detail_question(question) or is_field_detail_question(search_q):
        return "field_detail"
    if is_architecture_question(question) or is_architecture_question(search_q):
        return "architecture"
    if is_procedure_question(question) or is_procedure_question(search_q):
        return "how_to"
    if is_comparison_question(question) or is_comparison_question(search_q):
        return "comparison"
    return "general"


def _product_explicit_in_question(question: str) -> str | None:
    """Product named in the current message (word boundary)."""
    from src.doc_registry import get_active_products
    q = question.lower()
    active_products = get_active_products()
    for prod in active_products:
        if re.search(rf"\b{re.escape(prod)}\b", q):
            return prod
    return None


def resolve_primary_product(
    question: str,
    subjects: list[str],
    history: list[dict] | None = None,
    store_count: int = 0
) -> str | None:
    """
    Current question wins over chat history.
    
    If the question introduces a new acronym, we do not filter by history subjects.
    Otherwise we use history subjects if it's a follow-up.
    Runs a dynamic pre-retrieval search if no explicit product is specified.
    """
    from src.doc_registry import get_active_products
    from src.query_expand import extract_acronyms
    
    current_acronyms = extract_acronyms(question)
    active_products = get_active_products()
    
    # 1. Check if the current question explicitly mentions any active product
    mentioned_current = [ac.lower() for ac in current_acronyms if ac.lower() in active_products]
    if len(mentioned_current) == 1:
        return mentioned_current[0]
    elif len(mentioned_current) > 1:
        suites = {"project_name", "project_module", "wpp"}
        components = [p for p in mentioned_current if p not in suites]
        if len(components) == 1:
            return components[0]
        # Multiple products mentioned (e.g. comparing YOUR_PRODUCT) - do not filter by single product
        return None
            
    # 2. If the current question has some other explicit acronyms/subjects,
    # do NOT fall back to history product filters (since the user changed the subject)
    if current_acronyms:
        return None
        
    # 3. If no new acronyms are mentioned, fall back to history product
    if history:
        history_subjects = collect_subjects("", history)
        mentioned_history = [ac.lower() for ac in history_subjects if ac.lower() in active_products]
        if len(mentioned_history) == 1:
            return mentioned_history[0]
        elif len(mentioned_history) > 1:
            return None
                
    # 4. Pre-search fallback to dynamically resolve product for queries without explicit terms
    if store_count > 0:
        try:
            from src.bm25_store import get_bm25_store
            bm25 = get_bm25_store()
            if bm25.size > 0:
                hits = bm25.search(question, top_k=1)
                if hits:
                    top_product = hits[0].get("product")
                    if top_product and top_product not in ("unknown", "demo"):
                        # Double-check that we do not filter to a wrong product if an acronym was asked
                        if current_acronyms:
                            if not any(ac.lower() == top_product for ac in current_acronyms):
                                return None
                        return top_product
        except Exception:
            pass

    return None


def _intent_extra_queries(intent: str, subjects: list[str], search_q: str, history: list[dict] | None = None) -> list[str]:
    """Generic extra queries per intent (dynamic and scalable)."""
    extra: list[str] = []
    q_lower = search_q.lower()

    if intent == "version_history":
        extra.extend(
            [
                "Document Version History",
                "first version software release",
                "Product Version Year and Month of release",
            ]
        )
        for ac in subjects:
            extra.append(f"first version of the {ac.upper()} Security Management software release")

    elif intent == "definition":
        for ac in subjects:
            extra.extend([
                f"{ac} definition",
                f"what is {ac}",
                ac,
                f"full form of {ac}",
                f"{ac} stands for",
            ])

    elif intent == "field_detail":
        # Extract window/form name dynamically
        m = re.search(r"\b([A-Za-z0-9\s]+?)\s+(?:window|form|screen|dialog|tab|panel|table)\b", search_q, re.I)
        title = m.group(1).strip() if m else None
        if not title:
            m_quote = re.search(r'"([^"]+)"', search_q)
            title = m_quote.group(1).strip() if m_quote else None
        if not title:
            title = "user" if "user" in q_lower else "fields"
            
        extra.extend(
            [
                f"fields in the {title} window",
                f"{title} form columns details description",
                "User Name Expiry Date Password Language Classification", # general common fields
            ]
        )

    elif intent == "how_to":
        from src.vector_store import get_vector_store
        store = get_vector_store()
        product = resolve_primary_product(search_q, subjects, history, store.count)
        prod_name = product.upper() if product else "product"
        extra.extend(
            [
                f"{search_q} procedure",
                f"{search_q} steps",
            ]
        )
        if any(
            term in q_lower
            for term in (
                "install",
                "installation",
                "setup",
                "configure",
                "configuration",
                "deploy",
                "deployment",
            )
        ):
            extra.extend(
                [
                    f"{prod_name} installation steps",
                    f"how to install {prod_name} setup install configure",
                    f"{prod_name} deployment guide",
                ]
            )

    elif intent == "architecture":
        for ac in subjects:
            ac_upper = ac.upper()
            extra.extend(
                [
                    f"{ac_upper} Security Management architecture client-server",
                    f"{ac_upper} subsystem services layout structure",
                    "User Management Security Logging Security Integrity",
                ]
            )

    elif intent == "comparison":
        if len(subjects) >= 2:
            extra.extend(
                [
                    f"difference between {subjects[0]} and {subjects[1]}",
                    f"{subjects[0]} vs {subjects[1]}",
                    f"compare {subjects[0]} {subjects[1]}",
                ]
            )
        else:
            extra.extend(
                [
                    f"{search_q} differences",
                    f"compare {search_q}",
                ]
            )

    return extra


def _build_chroma_where(
    product: str | None,
    exclude_demo: bool,
    doc_type: str | None = None,
) -> dict | None:
    clauses: list[dict] = []
    if product and product not in ("unknown", "demo"):
        clauses.append({"product": {"$eq": product}})
    # doc_type is soft-boosted in retrieval rather than hard-filtered here
    if exclude_demo:
        clauses.append({"is_demo": {"$eq": False}})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _infer_product_and_doc_type(
    intent: str, subjects: list[str], question: str, history: list[dict] | None = None
) -> tuple[str | None, str | None]:
    from src.vector_store import get_vector_store
    store = get_vector_store()
    product = resolve_primary_product(question, subjects, history, store.count)
    doc_type: str | None = None
    q = question.lower()

    if intent == "how_to":
        install_terms = (
            "install",
            "installation",
            "configure",
            "configuration",
            "setup",
            "deploy",
            "deployment",
            "appsettings",
            ".config",
            "service",
            "server",
            "path",
            "poll interval",
            "restart",
        )
        user_manual_terms = (
            "menu",
            "window",
            "screen",
            "dropdown",
            "role",
            "mapping",
            "whitelist",
            "password handling",
        )
        if any(term in q for term in install_terms) and not any(
            term in q for term in user_manual_terms
        ):
            doc_type = "install_guide"
    elif intent == "field_detail":
        doc_type = "user_manual"

    return product, doc_type


def route_query(question: str, history: list[dict] | None = None) -> QueryPlan:
    """
    Produce a retrieval plan from the user question and optional chat history.
    """
    from src.query_context import rewrite_affirmation_query
    question = rewrite_affirmation_query(question, history)

    q = question.strip()
    subjects = collect_subjects(q, history)

    if _SHORT_ACRONYM_RE.match(q):
        ac = q.rstrip("?").upper()
        if ac not in subjects:
            subjects.append(ac)
        search_q = f"What is {ac}? Definition and overview."
    elif is_follow_up(q) and subjects:
        search_q, subjects = resolve_question(q, history)
    else:
        search_q = q

    intent = _detect_intent(q, search_q)
    product_filter, doc_type_filter = _infer_product_and_doc_type(
        intent, subjects, q, history
    )

    if product_filter:
        primary = product_filter.upper()
        subjects = [primary] + [s for s in subjects if s != primary]

    queries = expanded_queries(search_q, subjects=subjects)
    extra = _intent_extra_queries(intent, subjects, search_q, history)
    for eq in extra:
        if eq.lower() not in {x.lower() for x in queries}:
            queries.append(eq)

    return QueryPlan(
        original_question=q,
        search_question=search_q,
        subjects=subjects,
        intent=intent,
        product_filter=product_filter,
        exclude_demo=True,
        search_queries=queries,
        doc_type_filter=doc_type_filter,
        focus_context=should_focus_context(intent, q),
        chroma_where=_build_chroma_where(
            product_filter, exclude_demo=True, doc_type=doc_type_filter
        ),
    )
