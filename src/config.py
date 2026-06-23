import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

# ── Document paths — read from env; NO hardcoded user-specific paths ──────────
# Set DOCS_DIR and ROLE_ATTR_DIR in your .env file (or OS env) to the actual
# folder locations on the deployment server / developer machine.
DOCS_DIR = Path(
    os.getenv(
        "DOCS_DIR",
        str(ROOT / "docs_input"),  # fallback: <project_root>/docs_input/
    )
)
ROLE_ATTR_DIR = Path(
    os.getenv(
        "ROLE_ATTR_DIR",
        str(ROOT / "role_attrs"),  # fallback: <project_root>/role_attrs/
    )
)
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", ROOT / "data" / "chroma"))
BM25_PATH = Path(os.getenv("BM25_PATH", ROOT / "data" / "bm25_index.pkl"))

# ── CORS origins — restrict in production (BUG-002) ───────────────────────────
# Set CORS_ORIGINS in .env as a comma-separated list, e.g.:
#   CORS_ORIGINS=https://project_name-bot.your-company.internal,http://localhost:5173
CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS", "http://localhost:5173")
CORS_ORIGINS: list[str] = [o.strip() for o in CORS_ORIGINS_RAW.split(",") if o.strip()]

# ── SSL verification — always True in production (BUG-004) ───────────────────
# To use a corporate CA bundle: SSL_VERIFY=/path/to/your-ca-bundle.pem
_ssl_env = os.getenv("SSL_VERIFY", "true")
if _ssl_env.lower() in ("0", "false", "no"):
    SSL_VERIFY: bool | str = False
elif Path(_ssl_env).exists():
    SSL_VERIFY = _ssl_env  # path to CA bundle
else:
    SSL_VERIFY = True

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
        "14000"
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
