# Document Intelligence Assistant — YOUR_PRODUCT RAG Chatbot

An enterprise-grade, layout-aware **Retrieval-Augmented Generation (RAG)** system designed for YourOrganization to ingest, parse, search, and answer technical questions from YOUR_PRODUCT manuals, SFS release documents, and Role Attribute matrices — with exact page-level citations and a relational SQL layer for 100% accurate role/attribute queries.

> 📚 **Looking for the Total Guide?** See the [Developer & Administrator Guide](DEVELOPER_GUIDE.md) for a deep dive into the architecture, automated MSSQL syncing procedures, and the roadmap for future enterprise expansion.

---

## ✨ What This System Does

- **Chat with your PDFs** — Ask any question about YOUR_PRODUCT, MFA, SFS, PKI, LDAP and get sourced answers with page references
- **Role Attributes Matrix** — Any role/attribute query is intercepted **before the LLM** and answered directly from PostgreSQL — zero hallucination, zero latency
- **Automated MSSQL Sync** — Role definitions are automatically pulled from the live PROJECT_NAME SQL Server via a lightweight RDP Sync API
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
         Groq LLM — llama-3.1-8b-instant (streaming)
              │
              ▼
         React Chat UI
```

**Key design principle:** Role/attribute queries **never reach the LLM**. They are answered directly from SQL — instant, accurate, and immune to token-limit errors (HTTP 413).

---

## 📁 File Structure

```
ai layer/
├── api.py                        # FastAPI backend — REST + SSE streaming endpoints
├── frontend/src/ChatUI.jsx       # React chat interface with streaming + section search
├── src/
│   ├── config.py                 # All env vars, model names, limits
│   ├── postgres_store.py         # pgvector dense store + role SQL methods (deduplicated)
│   ├── intent_router.py          # Zero-cost local regex intent router (LLM bypass)
│   ├── rag.py                    # RAG pipeline — includes _try_role_sql_direct() shortcut
│   ├── retrieval.py              # Hybrid search orchestration
│   ├── llm.py                    # Groq LLM integration (token-budget aware)
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
│   ├── sync_roles_from_api.py    # Laptop client (fetches from RDP API -> PostgreSQL)
│   └── nightly_ingest.ps1        # Master ingest script (Docs + Roles via API)
├── requirements.txt
├── docker-compose.prod.yml       # Production Tier 1 deployment (Single VM)
├── Dockerfile                    # Multi-stage production container build
├── k8s/                          # Kubernetes (AKS) deployment manifests
├── .github/workflows/deploy.yml  # CI/CD pipeline for GitHub/Azure DevOps
├── .env.production               # Secure production environment template
└── .env                          # API keys and config (do NOT commit)
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

**Result:** < 1 second responses, zero Groq API calls, zero 413 errors, zero hallucination. All role questions bypass the LLM and the VectorStore entirely.

### 2. Deduplicated SQL Results

All role SQL methods use `GROUP BY role_name, attribute_name` with `MIN()` aggregation — not `SELECT DISTINCT` on all columns — to correctly collapse entries where the same attribute has multiple description variants in the database.

### 3. Hybrid Search (Dense + Sparse)

| Layer | Technology | Purpose |
|---|---|---|
| Dense | pgvector cosine similarity | Semantic meaning |
| Sparse | PostgreSQL FTS (`tsvector`) | Keyword precision |
| Reranker | BAAI/bge-reranker-base | Cross-encoder re-scoring |

### 4. Token-Budget Aware LLM Calls

`src/llm.py` dynamically computes `max_tokens` based on prompt size to stay within the 8192-token Groq context window. Graceful fallback messages are returned instead of HTTP 500 for rate-limit (429) and payload-too-large (413) errors.

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
# Edit .env: set GROQ_API_KEY and DB credentials
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

## 🔒 Security Configuration

For local development vs. production, the `.env` file uses these secure defaults:

- `SSL_VERIFY=false`: Used locally due to your corporate proxy SSL interception. On Azure production, set to `true` or point to a CA bundle.
- `CORS_ORIGINS`: Restricts API access. Local defaults to `http://localhost:5173,http://localhost:5174`. Production should be `https://project_name-bot.your-company.internal`.
- `PG_PASSWORD`: No default. Production deployments will fail to start if this is not securely configured.

---

## ⚙️ Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | Groq API key for LLM inference |
| `PG_HOST` | `localhost` | PostgreSQL host |
| `PG_PORT` | `5432` | PostgreSQL port |
| `PG_DB` | `rag_db` | Database name |
| `PG_USER` | `postgres` | Database user |
| `PG_PASSWORD` | `password` | Database password |
| `OLLAMA_MODEL` | `llama-3.1-8b-instant` | Groq model name |
| `MAX_CONTEXT_CHARS` | `14000` | Max chars of context sent to LLM |
| `TOP_K` | `5` | Number of vector chunks retrieved |
| `OLLAMA_TIMEOUT` | `120` | Groq API timeout in seconds |

---

## 🗄️ Knowledge Base (Indexed)

| Metric | Value |
|---|---|
| Total Chunks | 62,774 |
| Total Documents | 407 files |
| Products Indexed | 13 (project_name, project_module, mfa, sfs, pki, ldap, iam, backup, web, whitelist, wpp + 2 others) |
| Embedding Model | `sentence-transformers/all-MiniLM-L6-v2` (384-dim) |
| Reranker | `BAAI/bge-reranker-base` |
| Role Mappings | Loaded from Excel into `role_mappings` PostgreSQL table |

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

> ⚠️ Groq free/paid tier is suitable for development only. For production with confidential documents:

| Option | Recommendation |
|---|---|
| **Azure OpenAI** | ✅ Best — data stays in Your Azure tenant, enterprise SLA, GDPR compliant |
| **On-prem Ollama** | ✅ Most secure — zero internet, air-gapped, no data leaves building |
| **Groq Paid** | ⚠️ Development/demo only — data leaves network |

### How to Switch to Azure OpenAI
If you obtain an Azure OpenAI Studio API Key, you do not need to rewrite any code. The application uses `httpx` and `openai` compliant paths. Just update your `.env` file:

```env
# 1. Your Azure OpenAI API Key
GROQ_API_KEY=<your-azure-openai-key>

# 2. Your Azure Endpoint URL
# Must follow this format: https://<resource-name>.openai.azure.com/openai/deployments/<deployment-name>
OLLAMA_BASE_URL=https://your-resource.openai.azure.com/openai/deployments/gpt-4o-mini

# 3. Model Name (must match your Azure deployment name)
OLLAMA_MODEL=gpt-4o-mini
```

### Deployment Tiers Included

1. **Tier 1 (Department VM)**: Use `docker-compose.prod.yml`. It runs the backend, PostgreSQL, and a separate background ingestion job.
2. **Tier 2 (Enterprise AKS)**: Use the `k8s/` folder. It contains a Deployment, Service, HPA (Horizontal Pod Autoscaler), and Ingress configured for Azure Application Gateway.

---

## 🚀 Future Improvements

While the core RAG engine is fully robust, these improvements are recommended before a Tier 2 Enterprise rollout:

1. **Azure Active Directory (Entra ID) Authentication**: 
   - Integrate MSAL (Microsoft Authentication Library) in the React frontend.
   - Add OAuth2 bearer token verification in FastAPI (`api.py`) to restrict bot access to authorized your employees only.
2. **Conversation Persistence & Analytics**:
   - Currently, chat history is held in browser memory. Add a PostgreSQL table to store chat sessions.
   - This allows users to resume chats and gives admins a dashboard to see which questions are asked most frequently.
3. **Application Insights / Monitoring**:
   - Add the `azure-monitor-opentelemetry` package to automatically log API response times, LLM latency, and user errors directly to Azure Monitor.

---

## ❓ FAQ

**Q: Role queries were duplicating the same attribute hundreds of times — is this fixed?**
A: Yes. The root cause was `SELECT DISTINCT` on 4 columns including `description`, which produced one row per unique description variant. Fixed using `GROUP BY role_name, attribute_name` + `MIN(description)`.

**Q: Role queries were returning HTTP 500 — is this fixed?**
A: Yes. Role queries now bypass the LLM entirely via `_try_role_sql_direct()` in `rag.py`. SQL results are returned directly in < 1 second. The Groq 413 token-limit error can no longer be triggered by role queries.

**Q: The bot found the right document but said "I cannot find information" — why?**
A: The context window was too small and cutting off table content. `MAX_CONTEXT_CHARS` is 14000 and the LLM system prompt explicitly instructs the model to output brief descriptions rather than claiming they are missing.

**Q: Queries work for PROJECT_NAME but give wrong answers for MFA — why?**
A: Short queries like `"mfa config"` were being treated as follow-ups to previous queries. Fixed — only explicit pronouns (`it/this/that`) now trigger follow-up resolution.

**Q: Can I ask role queries without any special filter?**
A: Yes — as of the latest update, role/attribute queries are automatically detected by the local intent router regardless of which filter is selected. The SQL shortcut fires on query content alone.

**Q: Why is the watcher disabled during bot runtime?**
A: Incremental ingestion is CPU/IO intensive and increases response latency. Run it nightly via Task Scheduler instead.

**Q: What happens if the Groq API rate-limits us?**
A: The LLM layer now catches HTTP 429 (rate limit) and 413 (payload too large) and returns a clean, user-facing message instead of crashing with HTTP 500.
