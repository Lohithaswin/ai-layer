"""
Sync roles from the RDP Sync API into local PostgreSQL.
Run this on your LAPTOP — it calls the API running on the RDP server.

Usage:
    python sync_roles_from_api.py              # uses SYNC_API_URL from .env
    python sync_roles_from_api.py --test       # just check connectivity
    python sync_roles_from_api.py --force      # force DB refresh on server side first
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from dotenv import load_dotenv
load_dotenv()

from src.postgres_store import PostgreSQLStore

# ── Config ────────────────────────────────────────────────────────────────────
SYNC_API_URL = os.getenv("SYNC_API_URL", "").rstrip("/")
API_KEY      = os.getenv("SYNC_API_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] sync_api — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sync_api")


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def test_connection() -> bool:
    if not SYNC_API_URL:
        log.error("SYNC_API_URL is not set in .env — cannot connect")
        return False
    url = f"{SYNC_API_URL}/health"
    log.info("Testing connection to: %s", url)
    try:
        resp = httpx.get(url, headers=_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            log.info(
                "Connected! Server: %s / %s  |  Cached: %s roles  |  Cache age: %ss",
                data.get("server"), data.get("database"),
                data.get("cached_roles"), data.get("cache_age_s"),
            )
            return True
        log.error("Health check failed: HTTP %s", resp.status_code)
        return False
    except Exception as e:
        log.error("Cannot reach sync API at %s: %s", SYNC_API_URL, e)
        log.error("Make sure role_sync_api.py is running on the RDP server.")
        return False


def fetch_roles(force: bool = False) -> list[dict] | None:
    if not SYNC_API_URL:
        log.error("SYNC_API_URL is not set in .env")
        return None

    # Optionally force a fresh MSSQL pull on the server
    if force:
        log.info("Forcing fresh sync on server side...")
        try:
            resp = httpx.post(f"{SYNC_API_URL}/sync", headers=_headers(), timeout=60)
            log.info("Server sync result: %s", resp.json())
        except Exception as e:
            log.warning("Force sync failed (continuing anyway): %s", e)

    log.info("Fetching roles from %s/roles ...", SYNC_API_URL)
    try:
        resp = httpx.get(f"{SYNC_API_URL}/roles", headers=_headers(), timeout=120)
        if resp.status_code == 401:
            log.error("Auth failed — check SYNC_API_KEY in .env matches the server")
            return None
        if resp.status_code != 200:
            log.error("API returned HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        payload = resp.json()
        roles = payload.get("roles", [])
        log.info("Received %d role-attribute mappings", len(roles))
        return roles
    except Exception as e:
        log.error("Failed to fetch roles: %s", e)
        return None


def insert_into_postgres(data: list[dict]) -> bool:
    log.info("Inserting %d rows into local PostgreSQL role_mappings...", len(data))
    try:
        store = PostgreSQLStore()
        conn  = store._get_connection()
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE role_mappings RESTART IDENTITY;")
            args = [
                (
                    row.get("role_name"),
                    row.get("attribute_name"),
                    row.get("group_name"),
                    None,   # class_name (not in API response)
                    None,   # class_id
                    row.get("description"),
                )
                for row in data
            ]
            cur.executemany(
                """INSERT INTO role_mappings
                   (role_name, attribute_name, group_name, class_name, class_id, description)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                args,
            )
            conn.commit()
        log.info("SUCCESS — %d role mappings synced into PostgreSQL", len(data))
        return True
    except Exception as e:
        log.error("PostgreSQL insert failed: %s", e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Sync MSSQL roles via RDP Sync API")
    parser.add_argument("--test",  action="store_true", help="Just test connectivity, don't sync")
    parser.add_argument("--force", action="store_true", help="Force fresh MSSQL pull on server")
    args = parser.parse_args()

    if not test_connection():
        sys.exit(1)

    if args.test:
        log.info("Connection test passed. Use without --test to sync.")
        return

    data = fetch_roles(force=args.force)
    if not data:
        sys.exit(1)

    if not insert_into_postgres(data):
        sys.exit(1)

    log.info("Role sync complete!")


if __name__ == "__main__":
    main()
