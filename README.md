# Document Intelligence Assistant — RAG Chatbot

An enterprise-grade, layout-aware **Retrieval-Augmented Generation (RAG)** system designed to ingest, parse, search, and answer technical questions from product manuals, release documents, and Role Attribute matrices — with exact page-level citations and a relational SQL layer for 100% accurate role/attribute queries.

> 📚 **Looking for the Total Guide?** See the [Developer & Administrator Guide](DEVELOPER_GUIDE.md) for a deep dive into the architecture, automated MSSQL syncing procedures, and the roadmap for future enterprise expansion.

---

## ✨ What This System Does

- **Chat with your PDFs** — Ask any question about your product documentation and get sourced answers with page references
- **Role Attributes Matrix** — Any role/attribute query is intercepted **before the LLM** and answered directly from PostgreSQL — zero hallucination, zero latency
- **Automated MSSQL Sync** — Role definitions are automatically pulled from a live SQL Server via a lightweight RDP Sync API
- **Section Search Bar** — Click any Role or Attribute name to instantly see its description, classes, groups, and assigned roles
- **Streaming Responses** — Answers stream token-by-token via SSE for a fast, responsive feel
- **Follow-Up Awareness** — Pronouns ("it", "that"), affirmations ("yes"), and vague references ("how do I do that?") are resolved from conversation history
- **Clarification System** — Vague or incomplete queries trigger a clarification prompt instead of guessing
- **Incremental Ingestion** — New documents auto-detected and indexed (watcher disabled during bot runtime to prevent slowdowns)

---

## 🏗 System Architecture

```
User Query
    │
    ▼
Intent Router (local regex, 0ms, no API call)
    │
    ├─── Role/Attribute Query?
    │         │
    │         ▼
    │    PostgreSQL role_mappings table
    │    (GET_ATTRIBUTES_FOR_ROLE / GET_ROLES_FOR_ATTRIBUTE /
    │     COUNT_ATTRIBUTES / DESCRIBE_ATTRIBUTE)
    │         │
    │         ▼
    │    Direct Answer ✅  ← No LLM, no token limits, < 1 second
    │
    └─── General Query?
              │
              ▼
         Hybrid Search (Dense pgvector + BM25 FTS)
              │
              ▼
         BGE Reranker (BAAI/bge-reranker-base)
              │
              ▼
         LLM — llama-3.1-8b-instant (streaming)
              │
              ▼
         React Chat UI
```

**Key design principle:** Role/attribute queries **never reach the LLM**. They are answered directly from SQL — instant, accurate, and immune to token-limit errors (HTTP 413).

---

## 📁 File Structure

```
ai-layer/
├── api.py                        # FastAPI backend — REST + SSE streaming endpoints
├── frontend/src/ChatUI.jsx       # React chat interface with streaming + section search
├── src/
│   ├── config.py                 # All env vars, model names, limits
│   ├── postgres_store.py         # pgvector dense store + role SQL methods (deduplicated)
│   ├── intent_router.py          # Zero-cost local regex intent router (LLM bypass)
│   ├── rag.py                    # RAG pipeline — includes _try_role_sql_direct() shortcut
│   ├── retrieval.py              # Hybrid search orchestration
│   ├── llm.py                    # LLM integration (token-budget aware)
│   ├── llm_stream.py             # Streaming LLM response handler
│   ├── ingest_batch.py           # Parallel PDF ingestion
│   ├── query_router.py           # Intent detection + product routing
│   ├── query_context.py          # Follow-up resolution + affirmation rewriter
│   ├── context_focus.py          # Page-collapse for dense procedural answers
│   ├── answer_formatter.py       # Post-processing + boilerplate strip
│   └── verifier.py               # Answer grounding verifier
├── scripts/
│   ├── role_sync_api.py          # RDP FastAPI server (exposes MSSQL data locally)
│   ├── setup_sync_api_task.ps1   # Registers the RDP Sync API on Windows boot
│   ├── sync_roles_from_api.py    # Client script (fetches from RDP API -> PostgreSQL)
│   └── nightly_ingest.ps1        # Master ingest script (Docs + Roles via API)
├── data/
│   └── sample_roles.json         # Sample role data for testing (anonymized)
├── requirements.txt
├── docker-compose.prod.yml       # Production deployment (Single VM)
├── Dockerfile                    # Multi-stage production container build
├── k8s/                          # Kubernetes (AKS) deployment manifests
├── .github/workflows/deploy.yml  # CI/CD pipeline
├── .env.production               # Production environment template
└── .env.example                  # Development environment template (copy to .env)
```

---

## ⚡ Key Features

### 1. SQL-Direct Role Query Bypass (No LLM)

The function `_try_role_sql_direct()` in `src/rag.py` intercepts role/attribute queries **before** any vector retrieval or LLM call:

| Query Pattern | Intent Detected | SQL Method Called |
|---|---|---|
| `"list all attrs for [role]"` | `GET_ATTRIBUTES_FOR_ROLE` | `get_attributes_for_role()` |
| `"what roles have [attribute]?"` | `GET_ROLES_FOR_ATTRIBUTE` | `get_roles_for_attribute()` |
| `"how many attributes does [role] have?"` | `COUNT_ATTRIBUTES` | `count_role_attributes()` |
| `"describe [attribute]"` | `DESCRIBE_ATTRIBUTE` | `describe_attribute()` / fallback to role |
| *Any unstructured mention of roles* | `GENERAL_ROLE_SEARCH` | `query_role_database()` |

**Result:** < 1 second responses, zero LLM API calls, zero 413 errors, zero hallucination. All role questions bypass the LLM and the VectorStore entirely.

### 2. Deduplicated SQL Results

All role SQL methods use `GROUP BY role_name, attribute_name` with `MIN()` aggregation — not `SELECT DISTINCT` on all columns — to correctly collapse entries where the same attribute has multiple description variants in the database.

### 3. Hybrid Search (Dense + Sparse)

| Layer | Technology | Purpose |
|---|---|---|
| Dense | pgvector cosine similarity | Semantic meaning |
| Sparse | PostgreSQL FTS (`tsvector`) | Keyword precision |
| Reranker | BAAI/bge-reranker-base | Cross-encoder re-scoring |

### 4. Token-Budget Aware LLM Calls

`src/llm.py` dynamically computes `max_tokens` based on prompt size to stay within the context window. Graceful fallback messages are returned instead of HTTP 500 for rate-limit (429) and payload-too-large (413) errors.

### 5. Follow-Up & Context Resolution

- Pronouns (`it`, `this`, `that`) are resolved to the previous topic
- Affirmations (`yes`, `sure`, `ok`) are rewritten to the last suggested topic
- Vague queries (`"how do I do that?"`) use conversation history to infer intent

### 6. Parent-Child Chunking

Child chunks (~200 chars) are indexed for retrieval precision. Parent chunks (~3000 chars) are passed to the LLM — preserving full tables and section context for complete answers.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker Desktop (for PostgreSQL + pgvector)
- Node.js 18+ (for frontend)

### 1. Setup Environment

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install Python dependencies
pip install -r requirements.txt

# Copy and configure environment variables
copy .env.example .env
# Edit .env: set your GROQ_API_KEY / Azure OpenAI key and DB credentials
```

### 2. Start PostgreSQL

```powershell
docker-compose up -d
```

### 3. Ingest Documents *(run once, then nightly)*

We use an automated pipeline for both PDFs and live MSSQL role data. The role data relies on `role_sync_api.py` running on the RDP server to bypass corporate firewall restrictions.

```powershell
# Run the master ingest script (updates VectorStore docs + Postgres roles)
.\scripts\nightly_ingest.ps1
```

### 4. Start the Backend API

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

### 5. Start the Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open **http://localhost:5174** (or `5173` depending on port availability).

---

## 🛠️ Developer Guide & Contributing Workflow

To help future engineers navigate, debug, and expand this repository, here is a complete guide to the development workflow.

### 1. Technology Stack Overview
- **Backend**: Python 3.11+, FastAPI (REST and SSE streaming), `psycopg2` (PostgreSQL), `pgvector` (vector similarity search).
- **Frontend**: React 19, Vite, Lucide React (for icons).
- **LLM Engine**: Groq or Azure OpenAI, integrated via custom `llm.py` and `llm_stream.py` wrappers.
- **Data Sync Pipeline**: MS SQL via RDP proxy API → PostgreSQL.

### 2. Modifying the Backend Core Logic
The intelligence of the RAG system is housed in the `src/` directory. If you are modifying how the chatbot thinks, retrieves, or answers, look here:
- **`src/intent_router.py`**: Start here if you want to add new "Zero-Cost" SQL bypass rules (e.g., matching a new regex pattern to bypass the LLM entirely).
- **`src/rag.py`**: The main orchestration pipeline. It decides whether to route to SQL directly or perform a hybrid search.
- **`src/retrieval.py`**: Modifies the Hybrid Search weights (Dense pgvector + Sparse BM25) or the Reranker (BAAI/bge-reranker-base).
- **`api.py`**: Add new FastAPI REST endpoints here. Ensure you follow the SSE (Server-Sent Events) pattern for streaming endpoints.

### 3. Modifying the Frontend UI
The UI is a single-page React application built with Vite.
- **Location**: `frontend/src/ChatUI.jsx` contains the main interface.
- **Dependencies**: React 19 and `lucide-react` for icons.
- **Streaming State**: The frontend handles token-by-token streaming via the `fetch` API and a `ReadableStream` reader. If you modify the backend streaming format in `api.py`, ensure `ChatUI.jsx` is updated to parse it correctly.

### 4. Running the Test Suite
Before committing any changes to the RAG logic or API, you must ensure you haven't broken the deterministic SQL lookups or general Q&A parsing.
The repository includes a comprehensive test suite covering 46+ edge cases.
```powershell
# Ensure the backend (api.py) is running on port 8000 first!
.\.venv\Scripts\python.exe full_test_suite.py
```
This will output a live test run to the terminal and generate a `full_test_results.json` artifact for review.

### 5. Debugging Tips
- **Role Queries Failing?**: Check the live Sync API on the RDP server. The firewall might be blocking port 8765. (See `scripts/role_sync_api.py`)
- **LLM Rate Limits (429) or Payload Too Large (413)?**: Adjust the `MAX_CONTEXT_CHARS` in `.env`. The backend `llm.py` dynamically calculates budgets, but oversized parent chunks can still push it to the edge.

### 6. Adding New Documents to the Knowledge Base
To add new manuals or procedural guides for the bot to read:
1. Place the new PDFs in the `docs/` directory.
2. Run the `.\scripts\nightly_ingest.ps1` script to chunk, embed, and index them into PostgreSQL. Note that incremental ingestion is CPU-heavy and should ideally be done when the bot is not under heavy load (e.g., via a scheduled nightly task).

### 7. MSSQL Database Role Sync Setup
Because corporate firewalls block direct connection from your developer laptop to the live MSSQL server, we use a lightweight proxy API. Follow these steps to set up the data import:

**On the MSSQL Server (RDP Machine):**
1. Log into the server via RDP.
2. Run the proxy API to expose the MSSQL data:
   ```cmd
   python scripts\role_sync_api.py
   ```
   *(This starts a FastAPI server on port 8765. To make this persistent on boot, run `powershell -ExecutionPolicy Bypass -File scripts\setup_sync_api_task.ps1` as an Administrator).*

**On your Local Machine (Dev Environment):**
1. Ensure your local `.env` has a `SYNC_API_KEY` that matches the server's `.env`.
2. Run the sync script to pull the data from the server's proxy API into your local PostgreSQL:
   ```powershell
   .\.venv\Scripts\python.exe scripts\sync_roles_from_api.py
   ```
   *(Note: This is automatically executed if you run the master `.\scripts\nightly_ingest.ps1` script).*

> 📚 **Deep Dive:** For profound architectural changes, Kubernetes manifests (`k8s/`), and CI/CD details, always refer to the [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).

---

## 🔒 Security Configuration

For local development vs. production, the `.env` file uses these secure defaults:

- `SSL_VERIFY=false`: Used locally if behind a corporate proxy with SSL interception. On production, set to `true` or point to your CA bundle.
- `CORS_ORIGINS`: Restricts API access. Local defaults to `http://localhost:5173,http://localhost:5174`. Production should point to your internal domain.
- `PG_PASSWORD`: No default. Production deployments will fail to start if this is not securely configured.

---

## ⚙️ Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | LLM API key (Groq or Azure OpenAI) |
| `PG_HOST` | `localhost` | PostgreSQL host |
| `PG_PORT` | `5432` | PostgreSQL port |
| `PG_DB` | `rag_db` | Database name |
| `PG_USER` | `postgres` | Database user |
| `PG_PASSWORD` | — | Database password (required) |
| `OLLAMA_MODEL` | `llama-3.1-8b-instant` | LLM model name |
| `MAX_CONTEXT_CHARS` | `14000` | Max chars of context sent to LLM |
| `TOP_K` | `5` | Number of vector chunks retrieved |
| `OLLAMA_TIMEOUT` | `120` | LLM API timeout in seconds |
| `MSSQL_SERVER` | — | SQL Server host (if using mssql mode) |
| `MSSQL_USER` | — | SQL Server login |
| `MSSQL_PASSWORD` | — | SQL Server password |
| `SYNC_API_KEY` | — | Shared secret for RDP proxy API |

---

## 🗄️ Knowledge Base (Indexed)

| Metric | Value |
|---|---|
| Embedding Model | `sentence-transformers/all-MiniLM-L6-v2` (384-dim) |
| Reranker | `BAAI/bge-reranker-base` |
| Storage | PostgreSQL with pgvector extension |
| Role Mappings | Loaded from Excel or live MSSQL into `role_mappings` table |

---

## 🧪 Test Results (46 Queries — 96% Pass Rate)

| Category | Tests | Pass | Notes |
|---|---|---|---|
| Role/Attribute SQL Queries | 5 | 5 ✅ | SQL-direct, no LLM, instant |
| Definitions & Acronyms | 6 | 6 ✅ | |
| Field / UI Detail | 4 | 4 ✅ | |
| Architecture & Components | 4 | 4 ✅ | |
| Version History | 4 | 4 ✅ | |
| Comparison | 3 | 3 ✅ | |
| Follow-Up / Contextual | 3 | 3 ✅ | Pronoun + affirmation resolution |
| Clarification | 2 | 2 ✅ | Vague query detection |
| API Utility Endpoints | 5 | 5 ✅ | |
| Procedural / How-To | 6 | 4 ✅ | 2 need broader context |
| Edge Cases | 4 | 4 ✅ | |
| **Total** | **46** | **44** | **~96%** |

---

## 🌙 Nightly Ingestion

The watcher is **disabled** during bot runtime to prevent slowdowns. Run ingestion on a schedule:

**Windows Task Scheduler** — Run at midnight:
```powershell
.\.venv\Scripts\python.exe -m src.ingest_batch
.\.venv\Scripts\python.exe src\ingest_roles.py
```

---

## 🏢 Production Deployment

> ⚠️ **NOTE:** The default configuration uses Groq for quick setup. For production with confidential documents, migrate to a private LLM provider:

| Option | Recommendation |
|---|---|
| **Azure OpenAI** | ✅ Best — data stays in your Azure tenant, enterprise SLA, GDPR compliant |
| **On-prem Ollama** | ✅ Most secure — zero internet, air-gapped, no data leaves building |
| **Groq Paid** | ⚠️ Development/demo only — data leaves your network |

### How to Switch to Azure OpenAI

```env
# 1. Your Azure OpenAI API Key
GROQ_API_KEY=<your-azure-openai-key>

# 2. Your Azure Endpoint URL
OLLAMA_BASE_URL=https://<resource-name>.openai.azure.com/openai/deployments/<deployment-name>

# 3. Model Name (must match your Azure deployment name)
OLLAMA_MODEL=gpt-4o-mini
```

### Deployment Tiers Included

1. **Tier 1 (Department VM)**: Use `docker-compose.prod.yml`. It runs the backend, PostgreSQL, and a separate background ingestion job.
2. **Tier 2 (Enterprise Kubernetes)**: Use the `k8s/` folder. It contains a Deployment, Service, HPA (Horizontal Pod Autoscaler), and Ingress configured for Azure Application Gateway.

---

## 🚀 Future Expansion & Improvements

1. **Azure Active Directory (Entra ID) Authentication**:
   - Integrate MSAL (Microsoft Authentication Library) in the React frontend.
   - Add OAuth2 bearer token verification in FastAPI (`api.py`) to restrict bot access to authorized users only.
2. **Conversation Persistence & Analytics**:
   - Currently, chat history is held in browser memory. Add a PostgreSQL table to store chat sessions.
   - Allows users to resume chats and gives admins a dashboard to see which questions are asked most frequently.
3. **Application Insights / Monitoring**:
   - Add the `azure-monitor-opentelemetry` package to log API response times, LLM latency, and user errors to Azure Monitor.

---

## ❓ FAQ

**Q: Role queries were duplicating the same attribute hundreds of times — is this fixed?**
A: Yes. The root cause was `SELECT DISTINCT` on 4 columns including `description`, which produced one row per unique description variant. Fixed using `GROUP BY role_name, attribute_name` + `MIN(description)`.

**Q: Role queries were returning HTTP 500 — is this fixed?**
A: Yes. Role queries now bypass the LLM entirely via `_try_role_sql_direct()` in `rag.py`. SQL results are returned directly in < 1 second. The LLM 413 token-limit error can no longer be triggered by role queries.

**Q: The bot found the right document but said "I cannot find information" — why?**
A: The context window was too small and cutting off table content. `MAX_CONTEXT_CHARS` is 14000 and the LLM system prompt explicitly instructs the model to output brief descriptions rather than claiming they are missing.

**Q: Queries work for one product but give wrong answers for another — why?**
A: Short queries were being treated as follow-ups to previous queries. Fixed — only explicit pronouns (`it/this/that`) now trigger follow-up resolution.

**Q: Can I ask role queries without any special filter?**
A: Yes — role/attribute queries are automatically detected by the local intent router regardless of which filter is selected. The SQL shortcut fires on query content alone.

**Q: Why is the watcher disabled during bot runtime?**
A: Incremental ingestion is CPU/IO intensive and increases response latency. Run it nightly via Task Scheduler instead.

**Q: What happens if the LLM API rate-limits us?**
A: The LLM layer now catches HTTP 429 (rate limit) and 413 (payload too large) and returns a clean, user-facing message instead of crashing with HTTP 500.
