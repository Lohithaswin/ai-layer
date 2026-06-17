"""REST API for the local PDF chatbot."""

import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.rag import ChatResponse, Source, ask

app = FastAPI(title="Local PDF RAG Chatbot", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    print("[API] Starting up. Background ingestion disabled to prevent slow downs.")

@app.on_event("shutdown")
def shutdown_event():
    print("[API] Shutting down.")


class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[HistoryMessage] = []
    product_filter: str | None = None
    file_filter: str | None = None


class SettingsRequest(BaseModel):
    model: str | None = None
    num_predict: int | None = None
    num_ctx: int | None = None


class SourceOut(BaseModel):
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


class ChatResponseOut(BaseModel):
    answer: str
    sources: list[SourceOut]
    used_llm: bool
    note: str | None = None
    processing_time_ms: float
    retrieval_time_ms: float
    num_sources_retrieved: int
    num_sources_used: int
    question_intent: str
    retrieval_mode: str = ""
    options: list[str] = []


def _to_out(resp: ChatResponse) -> ChatResponseOut:
    return ChatResponseOut(
        answer=resp.answer,
        sources=[
            SourceOut(
                ref=s.ref,
                source_file=s.source_file,
                page=s.page,
                excerpt=s.excerpt,
                score=s.score,
                section=s.section,
                source_type=s.source_type,
                product=s.product,
                context_before=s.context_before,
                context_after=s.context_after,
            )
            for s in resp.sources
        ],
        used_llm=resp.used_llm,
        note=resp.note,
        processing_time_ms=resp.processing_time_ms,
        retrieval_time_ms=resp.retrieval_time_ms,
        num_sources_retrieved=resp.num_sources_retrieved,
        num_sources_used=resp.num_sources_used,
        question_intent=resp.question_intent,
        retrieval_mode=resp.retrieval_mode,
        options=resp.options,
    )


@app.get("/health")
def health():
    from src.config import RERANKER_MODEL, USE_HYBRID_SEARCH, USE_RERANKER

    return {
        "status": "ok",
        "hybrid_search": USE_HYBRID_SEARCH,
        "reranker": USE_RERANKER,
        "reranker_model": RERANKER_MODEL,
    }


@app.get("/documents")
def list_docs():
    from src.vector_store import get_vector_store

    store = get_vector_store()

    return {
        "files": store.get_unique_files(),
        "products": store.get_unique_products(),
        "collection_size": store.count,
    }


@app.get("/products")
def list_products():
    """Return unique product names indexed in the vector store."""
    from src.vector_store import get_vector_store
    from src.doc_registry import get_active_products

    store = get_vector_store()
    store_products = store.get_unique_products() if hasattr(store, "get_unique_products") else []
    active = get_active_products()

    # Merge: store products take priority, active products fill in any gaps
    merged = list(dict.fromkeys(
        [p for p in store_products if p and p not in ("unknown", "demo")]
        + [p for p in active if p and p not in ("unknown", "demo")]
    ))
    return {"products": sorted(merged)}


@app.get("/models")
def list_models():
    """Return available models from the Groq API."""
    import httpx
    import src.config as cfg
    try:
        r = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}"},
            timeout=5.0
        )
        if r.status_code == 200:
            models = [m["id"] for m in r.json().get("data", [])]
            # Optional: sort alphabetically
            models.sort()
            return {"models": models, "active": cfg.OLLAMA_MODEL}
    except Exception:
        pass
    return {"models": [cfg.OLLAMA_MODEL], "active": cfg.OLLAMA_MODEL}


@app.post("/settings")
def update_settings(body: SettingsRequest):
    """Update active model and generation settings at runtime without restart."""
    import src.config as cfg
    import src.llm as llm_mod
    import src.llm_stream as stream_mod

    if body.model:
        cfg.OLLAMA_MODEL = body.model
    if body.num_predict:
        cfg.OLLAMA_NUM_PREDICT = body.num_predict
    if body.num_ctx:
        pass  # stored per-request

    return {
        "model": cfg.OLLAMA_MODEL,
        "num_predict": cfg.OLLAMA_NUM_PREDICT,
    }


@app.get("/sections")
def list_sections():
    """Return all role attribute names from the role_mappings SQL table."""
    from src.vector_store import get_vector_store
    store = get_vector_store()
    try:
        if hasattr(store, "get_role_attribute_names"):
            attrs = store.get_role_attribute_names()
            return {"sections": [{"section_title": attr, "source_file": "Role Attributes"} for attr in attrs]}
    except Exception:
        pass
    return {"sections": []}


@app.get("/section-content")
def get_section_content(section: str, source_file: str):
    """Return role, class, class_id and group for the selected attribute (no LLM)."""
    from src.vector_store import get_vector_store
    store = get_vector_store()
    try:
        if hasattr(store, "get_attribute_details"):
            return store.get_attribute_details(section)
    except Exception as e:
        return {"content": f"Error retrieving attribute: {str(e)}"}
    return {"content": ""}


@app.post("/chat", response_model=ChatResponseOut)
def chat(body: ChatRequest):
    hist = [{"role": m.role, "content": m.content} for m in body.history]
    from src.query_context import rewrite_affirmation_query
    question = rewrite_affirmation_query(body.question, hist)
    return _to_out(ask(
        question,
        history=hist,
        product_filter=body.product_filter,
        file_filter=body.file_filter
    ))


from src.retrieval import retrieve
from src.vector_store import get_vector_store
from src.rag import _format_context
from src.llm import SYSTEM_PROMPT, _build_prompt
from src.llm_stream import generate_stream
from src.clarifier import should_clarify, generate_clarification, satisfaction_followup


@app.post("/chat/stream")
def chat_stream(body: ChatRequest):
    def event_stream():
        hist = [{"role": m.role, "content": m.content} for m in body.history]
        from src.query_context import rewrite_affirmation_query
        question = rewrite_affirmation_query(body.question, hist)
        store = get_vector_store()

        # -------------------------------------------------------
        # STEP 1: Route the query to understand intent + product
        # -------------------------------------------------------
        from src.query_router import route_query
        plan = route_query(question, hist)

        # Override plan with explicit user filters from the request
        if body.product_filter:
            plan.product_filter = body.product_filter
            from src.query_router import _build_chroma_where
            plan.chroma_where = _build_chroma_where(body.product_filter, exclude_demo=True)

        if body.file_filter:
            plan.chroma_where = {"source_file": {"$eq": body.file_filter}}

        # -------------------------------------------------------
        # STEP 2: Clarification check (LLM-based + rule-based)
        # -------------------------------------------------------
        # Only clarify if the user did NOT already specify a product filter
        if not body.product_filter and not body.file_filter:
            try:
                needs_clarify = should_clarify(question, hist, plan)
            except Exception:
                needs_clarify = False

            if needs_clarify:
                try:
                    store_products = store.get_unique_products() if hasattr(store, "get_unique_products") else []
                    clarification_q = generate_clarification(
                        question,
                        products=[p for p in store_products if p not in ("unknown", "demo")],
                        history=hist,
                    )
                except Exception:
                    clarification_q = (
                        "Could you clarify which product you need help with? "
                        "For example, are you asking about YOUR_PRODUCT?"
                    )

                yield f"data: {json.dumps({'chunk': clarification_q})}\n\n"
                yield f"data: {json.dumps({'done': True, 'sources': [], 'clarification': True})}\n\n"
                return

        # -------------------------------------------------------
        # STEP 3: Retrieve documents
        # -------------------------------------------------------
        hits, plan = retrieve(
            question,
            store,
            history=hist,
            plan=plan,
            product_filter=body.product_filter,
            file_filter=body.file_filter,
            final_k=15, # Increased from default 7 to 15 to guarantee enough chunks for all 30+ role attributes
        )

        if not hits:
            yield f"data: {json.dumps({'chunk': 'The indexed documents do not contain enough information to answer this question. Could you rephrase or clarify what you are looking for?'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': []})}\n\n"
            return

        context, sources = _format_context(hits)
        
        # SQL Database Relational Interception
        # Sole trigger: the user selected 'Role Attributes' in the filter dropdown.
        # No query keyword checks needed — the filter IS the differentiator.
        q_lower = question.lower()
        is_role_filter_active = bool(
            body.file_filter and "role" in body.file_filter.lower()
        ) or bool(
            body.product_filter and "role" in body.product_filter.lower()
        )
        if is_role_filter_active:
            from src.intent_router import route_role_intent
            
            router_result = route_role_intent(q_lower)
            intent = router_result["intent"]
            entity = router_result["entity"]
            
            sql_blocks = []
            if entity and hasattr(store, "query_role_database"):
                if intent == "COUNT_ATTRIBUTES" and hasattr(store, "count_role_attributes"):
                    res = store.count_role_attributes(entity)
                    if res: sql_blocks.append(res)
                elif intent == "GET_ROLES_FOR_ATTRIBUTE" and hasattr(store, "get_roles_for_attribute"):
                    res = store.get_roles_for_attribute(entity)
                    if res: sql_blocks.append(res)
                elif intent == "GET_ATTRIBUTES_FOR_ROLE" and hasattr(store, "get_attributes_for_role"):
                    res = store.get_attributes_for_role(entity)
                    if res: sql_blocks.append(res)
                elif intent == "DESCRIBE_ATTRIBUTE" and hasattr(store, "describe_attribute"):
                    res = store.describe_attribute(entity)
                    if res: sql_blocks.append(res)
                
                # If a specific intent was detected but the specialized SQL returned nothing, fallback to general SQL search
                if not sql_blocks and intent != "GENERAL_SEARCH":
                    res = store.query_role_database([entity])
                    if res: sql_blocks.append(res)

            if sql_blocks:
                sql_context = "\n\n".join(sql_blocks)
                # Discard semantic search results completely for exact role queries
                hits.clear()
                context = f"=== EXACT DATABASE MATCHES FOR ROLES & ATTRIBUTES ===\n{sql_context}"
        
        # Aggressively compress Excel boilerplate to fit more rows into Groq's strict payload limit
        context = context.replace("Item details: ", "")
        context = context.replace("Role Attribute Name is ", "Attr:")
        context = context.replace("RoleName is ", "Role:")
        context = context.replace("Description is ", "Desc:")
        context = context.replace("Roles to which It is assigned is ", "Roles:")
        
        from src.config import MAX_CONTEXT_CHARS
        if len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS]

        history_str = ""
        if hist:
            for msg in hist[-5:]:
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

        # -------------------------------------------------------
        # STEP 4: Stream the LLM answer
        # -------------------------------------------------------
        for chunk in generate_stream(prompt, system=SYSTEM_PROMPT):
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"

        # Append satisfaction follow-up
        followup = satisfaction_followup()
        yield f"data: {json.dumps({'chunk': followup})}\n\n"

        sources_out = [
            {
                "ref": s.ref,
                "source_file": s.source_file,
                "page": s.page,
                "excerpt": s.excerpt,
                "score": s.score,
                "section": s.section,
                "source_type": s.source_type,
                "product": s.product,
            }
            for s in sources
        ]

        yield f"data: {json.dumps({'done': True, 'sources': sources_out})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
