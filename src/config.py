import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = Path("C:/path/to/your/Release-Documents")
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", ROOT / "data" / "chroma"))
BM25_PATH = Path(os.getenv("BM25_PATH", ROOT / "data" / "bm25_index.pkl"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
EXTRACT_TABLES = os.getenv("EXTRACT_TABLES", "true").lower() in ("1", "true", "yes")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama-3.1-8b-instant")
OLLAMA_TIMEOUT = max(float(os.getenv("OLLAMA_TIMEOUT", "900")), 900.0)
OLLAMA_NUM_PREDICT = max(int(os.getenv("OLLAMA_NUM_PREDICT", "1800")), 1800)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL", "BAAI/bge-reranker-base"
)

TOP_K = int(os.getenv("TOP_K", "7"))
RETRIEVAL_CANDIDATES = int(os.getenv("RETRIEVAL_CANDIDATES", "15"))
HYBRID_DENSE_WEIGHT = float(os.getenv("HYBRID_DENSE_WEIGHT", "0.5"))
HYBRID_SPARSE_WEIGHT = float(os.getenv("HYBRID_SPARSE_WEIGHT", "0.5"))
RRF_K = int(os.getenv("RRF_K", "60"))

COLLECTION_NAME = "local_docs"

# Parent-child chunking (child = search index, parent = LLM context)
CHILD_CHUNK_SIZE = int(os.getenv("CHILD_CHUNK_SIZE", "200"))
CHILD_CHUNK_OVERLAP = int(os.getenv("CHILD_CHUNK_OVERLAP", "40"))
PARENT_MAX_CHARS = int(os.getenv("PARENT_MAX_CHARS", "3000"))

# Legacy aliases (used if parent-child disabled)
CHUNK_SIZE = CHILD_CHUNK_SIZE
CHUNK_OVERLAP = CHILD_CHUNK_OVERLAP

USE_HYBRID_SEARCH = os.getenv("USE_HYBRID_SEARCH", "true").lower() in ("1", "true", "yes")
USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() in ("1", "true", "yes")
MAX_EXPANDED_QUERIES = int(os.getenv("MAX_EXPANDED_QUERIES", "5"))

# Collapse retrieval to one page/section for procedural questions (scalable, not per-topic)
CONTEXT_FOCUS_ENABLED = os.getenv("CONTEXT_FOCUS_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
CONTEXT_FOCUS_MAX_SOURCES = int(os.getenv("CONTEXT_FOCUS_MAX_SOURCES", "10"))
CONTEXT_FOCUS_PAGE_GAP = float(os.getenv("CONTEXT_FOCUS_PAGE_GAP", "0.35"))
MAX_CONTEXT_CHARS = int(
    os.getenv(
        "MAX_CONTEXT_CHARS",
        "10000"
    )
)
MAX_SECTION_PAGES = int(os.getenv("MAX_SECTION_PAGES", "25"))
# Demo/sample PDFs (generic payment/API content — deprioritized for YOUR_PRODUCT questions)
DEMO_PDF_NAMES = frozenset(
    {
        "architecture-overview.pdf",
        "api-security.pdf",
        "deployment-guide.pdf",
    }
)
