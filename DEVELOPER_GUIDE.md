# Document Intelligence Bot — Developer & Administrator Guide

This document serves as the comprehensive "Total Guide" for the Document Intelligence Assistant, detailing the architecture, automated syncing mechanisms, administrator procedures, and a roadmap for future expansion.

---

## 📖 Table of Contents
1. [System Overview](#system-overview)
2. [Total Setup & Execution Guide](#total-setup--execution-guide)
3. [Architecture Deep Dive](#architecture-deep-dive)
4. [Administrator Guide: MSSQL Sync](#administrator-guide-mssql-sync)
5. [Future Expansion & Development](#future-expansion--development)

---

## 1. System Overview

The Document Intelligence Assistant is an enterprise RAG (Retrieval-Augmented Generation) chatbot. It is designed to be **highly deterministic for structured data** (Roles and Attributes) while being **context-aware for unstructured data** (PDF manuals, procedural guides).

### Core Philosophy
- **Zero Hallucination for Roles:** If a user asks about a role or an attribute, the query is intercepted by a local Intent Router and routed directly to a relational SQL database. The LLM is **bypassed entirely**.
- **Contextual Awareness:** For manual/procedural questions, the system resolves pronouns and conversation history before retrieving dense (pgvector) and sparse (BM25) chunks, which are then re-ranked and passed to the LLM.
- **Air-Gapped / Firewall Resilient:** Operates behind strict corporate firewalls using lightweight proxy APIs to sync live data across restricted network zones.

---

## 2. Total Setup & Execution Guide

### Prerequisites
- **Local Machine / VM:** Python 3.11+, Node.js 18+, Docker Desktop (running PostgreSQL with `pgvector`).
- **RDP Server:** Access to the MSSQL Database server, Python 3.11+.

### Component Initialization

#### A. Database (PostgreSQL)
Start the vector and relational database container:
```powershell
docker-compose up -d
```

#### B. The RDP Sync API (On the MSSQL Server)
Because corporate firewalls block direct port `1433` access from developer machines to the live MSSQL server, we use a lightweight proxy.
1. Log into the RDP Server.
2. Run the proxy API:
   ```cmd
   python scripts\role_sync_api.py
   ```
   *(See [Administrator Guide](#administrator-guide-mssql-sync) for how to set this to run automatically on boot).*

#### C. Nightly Data Ingestion (On the Hosting VM/Laptop)
Run the master pipeline to ingest PDFs and sync the live MSSQL data over the proxy API:
```powershell
.\scripts\nightly_ingest.ps1
```

#### D. Start the Application
1. **Backend:**
   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
   ```
2. **Frontend:**
   ```powershell
   cd frontend
   npm run dev
   ```

---

## 3. Architecture Deep Dive

### 3.1 The Intent Router (`src/intent_router.py`)
Every user prompt passes through a zero-cost, 0ms regex router before the database is touched.
- `_ATTRS_FOR_ROLE_RE`: Detects `"what attributes does X have?"`
- `_ROLES_FOR_ATTR_RE`: Detects `"which roles have X?"`
- `_DESCRIBE_RE`: Detects `"describe X"`
- `_ROLE_KEYWORD_RE`: A catch-all for any unstructured query mentioning "role", "attribute", or "permission".

**Bypass Mechanism:** If any role intent is detected, the `rag.py` pipeline halts LLM execution and queries the `role_mappings` PostgreSQL table directly.

### 3.2 Hybrid Retrieval (`src/retrieval.py`)
For general document queries, the system uses:
1. **Dense Retrieval:** `sentence-transformers/all-MiniLM-L6-v2` compares semantic meaning against `pgvector`.
2. **Sparse Retrieval:** PostgreSQL Full Text Search (`tsvector` / `websearch_to_tsquery`) ensures exact keyword hits.
3. **Cross-Encoder Reranking:** `BAAI/bge-reranker-base` re-scores the combined hits for ultimate precision.

### 3.3 LLM Orchestration (`src/llm.py`)
- Dynamically calculates the token budget to prevent HTTP 413 (Payload Too Large) errors.
- Handles HTTP 429 (Rate Limit) errors gracefully without crashing the UI.

---

## 4. Administrator Guide: MSSQL Sync

The hardest challenge in the current infrastructure is bridging the live MSSQL database with the RAG PostgreSQL database across strict internal firewalls.

### How the Automated Sync Works
1. **`scripts\role_sync_api.py`** runs as a persistent FastAPI server on the RDP machine (Port `8765`). It connects locally to MSSQL via Windows Authentication (`pyodbc`).
2. It caches the heavy SQL `JOIN` query for 1 hour to prevent DB spam.
3. **`scripts\sync_roles_from_api.py`** runs on the host VM/Laptop during the nightly ingest. It hits `http://<RDP-IP>:8765/roles` and performs a clean `TRUNCATE` and `INSERT` into the local PostgreSQL `role_mappings` table.

### Admin Maintenance: Keeping the Sync API Alive
If the RDP server restarts, the Sync API must start automatically.
As an Administrator on the RDP Server, run the included setup script once:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_sync_api_task.ps1
```
This registers a Windows Task Scheduler job that:
- Runs as the highest privilege interactive user.
- Starts at boot.
- Restarts automatically if it crashes.

### Troubleshooting Sync Issues
- **Timeout / Can't connect to 8765:** The corporate firewall may have reset. On the RDP server, re-run:
  `netsh advfirewall firewall add rule name="Role Sync API" dir=in action=allow protocol=TCP localport=8765`
- **Auth Error (401):** Ensure `SYNC_API_KEY` in the RDP's `.env` matches the Laptop/VM's `.env`.

---

## 5. Future Expansion & Development

As the chatbot scales from a Departmental Tool (Tier 1) to an Enterprise Deployment (Tier 2), the following architectural upgrades are recommended.

### 5.1 Real-Time MSSQL Webhooks (Moving away from nightly sync)
Currently, roles are synced nightly. In the future, the MSSQL database can trigger real-time updates.
- **Development Path:** Write an MSSQL Trigger on the role attributes table that fires an HTTP POST request to a new FastAPI endpoint (`POST /webhooks/roles/update`) on the RAG server whenever a role changes.
- **Benefit:** The chatbot knows about role changes instantly instead of waiting 24 hours.

### 5.2 Converting the RDP Sync API to a Windows Service
Task Scheduler is effective but lacks robust telemetry.
- **Development Path:** Wrap `role_sync_api.py` using `pywin32` (`win32serviceutil`). Install it as an official Windows Service (`services.msc`).
- **Benefit:** Native Windows event logging, graceful shutdown handling, and standard IT monitoring.

### 5.3 Azure Active Directory (Entra ID) Integration
Before launching organization-wide, the bot must restrict access.
- **Development Path:**
  1. Register an App in Azure Entra ID.
  2. Implement `@azure/msal-react` in the frontend for Single Sign-On (SSO).
  3. Pass the resulting Bearer Token to FastAPI and validate it using `fastapi-azure-auth`.
- **Benefit:** Only authorized users can access the UI, and queries can be tied to user identities.

### 5.4 PostgreSQL Chat Persistence & Analytics
Currently, chat history lives in the browser tab.
- **Development Path:**
  1. Create a `chat_sessions` and `chat_messages` table in PostgreSQL.
  2. Generate a UUID for each session in the React frontend.
  3. FastAPI saves user queries and LLM responses to the DB in real-time.
- **Benefit:** Admins can build a dashboard (e.g., Grafana) to track the most asked questions, failed queries, and user satisfaction metrics.

### 5.5 Moving to Azure OpenAI (Enterprise SLA)
Groq is used for high-speed development, but production requires strict data privacy.
- **Development Path:**
  - Provision an Azure OpenAI resource in your tenant.
  - Update `.env`:
    ```env
    GROQ_API_KEY=<azure-key>
    OLLAMA_BASE_URL=https://<resource>.openai.azure.com/openai/deployments/<model>
    OLLAMA_MODEL=gpt-4o-mini
    ```
- **Benefit:** 100% GDPR compliance, enterprise SLAs, and data never leaves your corporate perimeter.
