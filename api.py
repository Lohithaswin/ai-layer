"""REST API for the local PDF chatbot."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.rag import ChatResponse, Source, ask

app = FastAPI(title="Local PDF RAG Chatbot", version="0.1.0")

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


@app.post("/chat", response_model=ChatResponseOut)
def chat(body: ChatRequest):
    hist = [{"role": m.role, "content": m.content} for m in body.history]
    return _to_out(ask(
        body.question,
        history=hist,
        product_filter=body.product_filter,
        file_filter=body.file_filter
    ))

import json
from fastapi.responses import StreamingResponse
from src.retrieval import retrieve
from src.vector_store import get_vector_store
from src.rag import _format_context
from src.llm import SYSTEM_PROMPT, _build_prompt
from src.llm_stream import generate_stream

@app.post("/chat/stream")
def chat_stream(body: ChatRequest):
    def event_stream():
        hist = [{"role": m.role, "content": m.content} for m in body.history]
        store = get_vector_store()
        hits, plan = retrieve(
            body.question,
            store,
            history=hist,
            product_filter=body.product_filter,
            file_filter=body.file_filter,
        )

        if not hits:
            yield f"data: {json.dumps({'chunk': 'The indexed documents do not contain enough information.'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': []})}\n\n"
            return

        context, sources = _format_context(hits)
        
        history_str = ""
        if hist:
            for msg in hist[-5:]:
                role = "User" if msg.get("role") == "user" else "Assistant"
                history_str += f"{role}: {msg.get('content')}\n"

        prompt = _build_prompt(
            body.question,
            context,
            plan.intent,
            history_str=history_str,
        )

        for chunk in generate_stream(prompt, system=SYSTEM_PROMPT):
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            
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
