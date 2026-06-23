#!/usr/bin/env bash
# ============================================================
# PROJECT_NAME Bot — Nightly Ingestion Script
# ============================================================
# Run this nightly via cron or systemd timer to re-index any
# new/updated documents and role attribute files.
#
# Cron (add via: crontab -e):
#   0 2 * * * /opt/project_name-bot/scripts/nightly_ingest.sh >> /var/log/project_name/ingest.log 2>&1
#
# Or with Docker Compose:
#   docker compose -f docker-compose.prod.yml --profile ingest up
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_ROOT/.venv"
LOG_DIR="/var/log/project_name"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "========================================"
echo "[$TIMESTAMP] Starting nightly ingestion"
echo "========================================"

# Activate virtual environment
if [[ -f "$VENV/bin/activate" ]]; then
    source "$VENV/bin/activate"
elif [[ -f "$VENV/Scripts/activate" ]]; then
    # Windows Git Bash / Cygwin
    source "$VENV/Scripts/activate"
else
    echo "[ERROR] Virtual environment not found at $VENV"
    exit 1
fi

cd "$PROJECT_ROOT"

# ── Step 1: Ingest PDFs + Word docs ──────────────────────────
echo ""
echo "[1/2] Ingesting release documents..."
if python -m src.ingest_batch; then
    echo "[1/2] ✅ Document ingestion complete"
else
    echo "[1/2] ❌ Document ingestion failed (exit code: $?)"
    exit 1
fi

# ── Step 2: Ingest Role Attributes Excel ─────────────────────
echo ""
echo "[2/2] Ingesting role attributes..."
ROLE_SCRIPT="$PROJECT_ROOT/src/role_ingestor.py"
if [[ ! -f "$ROLE_SCRIPT" ]]; then
    ROLE_SCRIPT="$PROJECT_ROOT/scripts/ingest_roles.py"
fi

if [[ -f "$ROLE_SCRIPT" ]]; then
    if python "$ROLE_SCRIPT"; then
        echo "[2/2] ✅ Role ingestion complete"
    else
        echo "[2/2] ❌ Role ingestion failed"
        exit 1
    fi
else
    echo "[2/2] ⚠️  Role ingestion script not found — skipping"
fi

echo ""
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Nightly ingestion complete"
echo "========================================"
