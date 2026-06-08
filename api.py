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


class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[HistoryMessage] = []
    product_filter: str | None = None
    file_filter: str | None = None


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
        )

        if not hits:
            yield f"data: {json.dumps({'chunk': 'The indexed documents do not contain enough information to answer this question. Could you rephrase or clarify what you are looking for?'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': []})}\n\n"
            return

        context, sources = _format_context(hits)

        history_str = ""
        if hist:
            for msg in hist[-5:]:
                role = "User" if msg.get("role") == "user" else "Assistant"
                history_str += f"{role}: {msg.get('content')}\n"

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
