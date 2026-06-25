# ============================================================
# Document Intelligence Bot Bot — Production Dockerfile
# ============================================================
# Multi-stage build:
#   Stage 1 (builder): install C extensions for psycopg2, pyodbc, etc.
#   Stage 2 (runtime): lean runtime image, non-root user
# ============================================================

# ── Stage 1: build ──────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for psycopg2 (libpq), pyodbc (unixodbc), and sentence-transformers
# Also installs Microsoft ODBC Driver 17 for SQL Server (needed by pyodbc at build time)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    apt-transport-https \
    libpq-dev \
    gcc \
    g++ \
    unixodbc-dev \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Pre-download embedding model into the image so the container
# starts instantly without downloading 90 MB at runtime.
RUN PYTHONPATH=/install/lib/python3.11/site-packages \
    python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# ── Stage 2: runtime ────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system dependencies:
#   libpq5          — PostgreSQL client lib
#   unixodbc        — ODBC runtime
#   msodbcsql17     — Microsoft SQL Server ODBC Driver 17 (for live PROJECT_NAME DB queries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    apt-transport-https \
    libpq5 \
    unixodbc \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages and pre-downloaded model from builder
COPY --from=builder /install /usr/local
COPY --from=builder /root/.cache /root/.cache

# Copy application source (exclude data/, .env, node_modules via .dockerignore)
COPY api.py .
COPY src/ ./src/
COPY scripts/ ./scripts/

# Non-root user for security
RUN useradd -m -u 1001 project_name && chown -R project_name:project_name /app
USER project_name

EXPOSE 8000

# Health check — used by Docker / Kubernetes
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/health', timeout=5); exit(0 if r.status_code == 200 else 1)"

# 2 workers by default; override with UVICORN_WORKERS env var
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
