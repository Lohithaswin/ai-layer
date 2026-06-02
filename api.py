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


class SourceOut(BaseModel):
    ref: int
    source_file: str
    page: int
    excerpt: str
    score: float
    section: str = ""
    source_type: str = "Local"
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
    from src.config import DOCS_DIR
    from src.vector_store import get_vector_store
    
    store = get_vector_store()
    files = []
    if DOCS_DIR.exists():
        files = [f.name for f in DOCS_DIR.glob("*.pdf")]
    return {
        "files": files,
        "collection_size": store.count,
    }


@app.post("/chat", response_model=ChatResponseOut)
def chat(body: ChatRequest):
    hist = [{"role": m.role, "content": m.content} for m in body.history]
    return _to_out(ask(body.question, history=hist))
