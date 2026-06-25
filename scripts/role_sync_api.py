"""
PROJECT_NAME Role Sync API
==================
Run this on the RDP server (where MSSQL is accessible).
Exposes role-attribute data from PROJECT_NAME SQL Server over HTTP so
the laptop can sync automatically without a direct DB connection.

Start manually:
    python role_sync_api.py

Register as a Windows Task (run once as Admin):
    powershell -ExecutionPolicy Bypass -File setup_sync_api_task.ps1

Endpoints:
    GET /health         — liveness check
    GET /roles          — full role-attribute export (JSON)
    POST /sync          — force a fresh DB pull (cache-busting)
"""

import os
import time
import logging
import pyodbc
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

# ── Config ────────────────────────────────────────────────────────────────────
SERVER   = os.getenv("MSSQL_SERVER",   "PRODEUM132PINB4")
DATABASE = os.getenv("MSSQL_DATABASE", "PROJECT_NAME")
DRIVER   = os.getenv("MSSQL_DRIVER",   "SQL Server")
PORT     = int(os.getenv("SYNC_API_PORT", "8765"))

# Optional simple API key — set SYNC_API_KEY in .env on BOTH machines.
# Leave blank to disable auth (fine on a closed corporate network).
API_KEY  = os.getenv("SYNC_API_KEY", "")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("role_sync_api")

# ── In-memory cache ───────────────────────────────────────────────────────────
_cache: dict = {"data": None, "fetched_at": None, "count": 0}
CACHE_TTL_SECONDS = 3600  # re-query MSSQL at most once per hour

app = FastAPI(title="PROJECT_NAME Role Sync API", version="1.0.0")


# ── Auth helper ───────────────────────────────────────────────────────────────
def _check_auth(x_api_key: Optional[str]):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


# ── DB query ──────────────────────────────────────────────────────────────────
def _fetch_from_mssql() -> list[dict]:
    conn_str = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"Trusted_Connection=yes;"
    )
    log.info("Connecting to MSSQL: %s / %s", SERVER, DATABASE)
    conn = pyodbc.connect(conn_str, timeout=15)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            r.Name              AS role_name,
            ra.Name             AS attribute_name,
            rag.Name            AS group_name,
            ra.StructuredName   AS structured_name,
            ra.Description      AS description,
            r.Description       AS role_description,
            CAST(r.IsHighRiskRole AS int) AS is_high_risk,
            r.RoleStatus        AS role_status
        FROM dbo.RoleAttributeMatrixs ram
        JOIN dbo.Role r
            ON r.Id = ram.RoleId
        JOIN dbo.RoleAttribute ra
            ON ra.Id = ram.AttributeId
        LEFT JOIN dbo.RoleAttributeGroup rag
            ON rag.Id = ra.AttributeGroupId
        WHERE ra.IsActive = 1
        ORDER BY r.Name, rag.Name, ra.Name
    """)
    cols = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    data = []
    for row in rows:
        record = dict(zip(cols, row))
        record["is_high_risk"] = bool(record.get("is_high_risk"))
        data.append(record)
    log.info("Fetched %d role-attribute mappings from MSSQL", len(data))
    return data


def _get_roles(force: bool = False) -> dict:
    now = time.time()
    cached_at = _cache["fetched_at"]
    if not force and _cache["data"] and cached_at and (now - cached_at) < CACHE_TTL_SECONDS:
        log.info("Returning cached data (%d records, age %.0fs)", _cache["count"], now - cached_at)
        return _cache

    data = _fetch_from_mssql()
    _cache["data"]       = data
    _cache["fetched_at"] = now
    _cache["count"]      = len(data)
    return _cache


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status":       "ok",
        "server":       SERVER,
        "database":     DATABASE,
        "cached_roles": _cache["count"],
        "cache_age_s":  round(time.time() - _cache["fetched_at"], 1) if _cache["fetched_at"] else None,
        "timestamp":    datetime.utcnow().isoformat() + "Z",
    }


@app.get("/roles")
def get_roles(x_api_key: Optional[str] = Header(default=None)):
    _check_auth(x_api_key)
    try:
        cache = _get_roles()
        return JSONResponse(content={
            "count":      cache["count"],
            "fetched_at": cache["fetched_at"],
            "roles":      cache["data"],
        })
    except Exception as e:
        log.error("Failed to fetch roles: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sync")
def force_sync(x_api_key: Optional[str] = Header(default=None)):
    """Force a fresh pull from MSSQL, bypassing the cache."""
    _check_auth(x_api_key)
    try:
        cache = _get_roles(force=True)
        return {"status": "synced", "count": cache["count"]}
    except Exception as e:
        log.error("Sync failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    log.info("Starting Role Sync API on port %d", PORT)
    log.info("MSSQL: %s / %s", SERVER, DATABASE)
    if API_KEY:
        log.info("API key auth: ENABLED")
    else:
        log.warning("API key auth: DISABLED — set SYNC_API_KEY in .env to enable")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
