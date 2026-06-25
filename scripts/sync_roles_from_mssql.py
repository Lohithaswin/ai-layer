#!/usr/bin/env python
"""
sync_roles_from_mssql.py
------------------------
Standalone script: pulls role-attribute data from the remote PROJECT_NAME SQL Server
and syncs it into the local PostgreSQL 'role_mappings' table.

Run manually:
    python scripts/sync_roles_from_mssql.py

Or schedule via Windows Task Scheduler / cron for automatic periodic sync.

Exit codes:
    0  - success
    1  - connectivity test failed
    2  - ingestion error
"""

import sys
import os
import logging
from pathlib import Path

# Allow imports from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env from project root
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_roles")


def main() -> int:
    from src.mssql_connector import test_connection, MSSQL_SERVER, MSSQL_DATABASE

    # ── Step 1: connectivity check ─────────────────────────────────────────
    logger.info("Testing MSSQL connectivity: %s / %s", MSSQL_SERVER, MSSQL_DATABASE)
    result = test_connection()

    if not result["ok"]:
        logger.error("MSSQL connection FAILED: %s", result["error"])
        logger.error(
            "Check MSSQL_SERVER, MSSQL_USER, MSSQL_PASSWORD in your .env file."
        )
        return 1

    logger.info(
        "Connection OK — RoleAttributeMatrix has %d rows.",
        result["role_attribute_matrix_rows"],
    )

    # ── Step 2: run ingestion ──────────────────────────────────────────────
    try:
        from src.role_ingestor import run_ingestion
        run_ingestion(source="mssql")
        logger.info("Sync complete.")
        return 0
    except Exception as exc:
        logger.exception("Ingestion failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
