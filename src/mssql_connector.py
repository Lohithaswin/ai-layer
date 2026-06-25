"""
mssql_connector.py
------------------
Connects to the remote Microsoft SQL Server (PROJECT_NAME database) and fetches
role-attribute data from the live tables:

    dbo.Role                 - role master (RoleId, RoleName, ...)
    dbo.RoleAttribute        - attribute master (AttributeId, AttributeName, Description, ...)
    dbo.RoleAttributeGroup   - attribute groups (GroupId, GroupName, ...)
    dbo.RoleAttributeMatrix  - role ↔ attribute mapping (RoleId, AttributeId, Comment)

Returns a normalised pandas DataFrame with columns:
    role_name, attribute_name, class_name, class_id, group_name, description

which is the same shape expected by role_ingestor.py so the rest of the
pipeline needs no changes.

Configuration (via .env):
    MSSQL_SERVER    - server hostname or IP  (default: 10.154.219.164)
    MSSQL_DATABASE  - database name          (default: PROJECT_NAME)
    MSSQL_DRIVER    - ODBC driver name       (default: ODBC Driver 17 for SQL Server)
    MSSQL_USER      - SQL login username     (leave blank for Windows Auth)
    MSSQL_PASSWORD  - SQL login password     (leave blank for Windows Auth)
    MSSQL_TIMEOUT   - connection timeout in seconds (default: 30)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Connection config from environment ────────────────────────────────────────
MSSQL_SERVER   = os.getenv("MSSQL_SERVER",   "YOUR_MSSQL_SERVER_IP")
MSSQL_DATABASE = os.getenv("MSSQL_DATABASE", "PROJECT_NAME")
MSSQL_USER     = os.getenv("MSSQL_USER",     "")
MSSQL_PASSWORD = os.getenv("MSSQL_PASSWORD", "")
MSSQL_TIMEOUT  = int(os.getenv("MSSQL_TIMEOUT", "30"))


def _best_available_driver() -> str:
    """
    Auto-select the best available ODBC driver for SQL Server.
    Priority: ODBC Driver 18 > 17 > 13 > legacy 'SQL Server' (Windows built-in).
    Override with the MSSQL_DRIVER env var if needed.
    """
    env_driver = os.getenv("MSSQL_DRIVER", "")
    if env_driver:
        return env_driver  # honour explicit override
    try:
        import pyodbc  # type: ignore
        installed = pyodbc.drivers()
        for preferred in (
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13 for SQL Server",
        ):
            if preferred in installed:
                logger.debug("Auto-selected ODBC driver: %s", preferred)
                return preferred
    except Exception:
        pass
    return "SQL Server"  # legacy Windows built-in fallback


MSSQL_DRIVER = _best_available_driver()


def _build_connection_string() -> str:
    """
    Build the pyodbc connection string.
    Uses SQL Server login when MSSQL_USER is set, otherwise
    falls back to Windows Authentication (Trusted_Connection=yes).
    """
    # NOTE: 'Connect Timeout' and 'TrustServerCertificate' are only valid for
    # ODBC Driver 17/18+. The legacy built-in 'SQL Server' driver rejects them
    # with 'Invalid connection string attribute'. Timeout is passed separately
    # via pyodbc.connect(timeout=N) instead.
    _modern_driver = any(
        kw in MSSQL_DRIVER
        for kw in ("ODBC Driver 17", "ODBC Driver 18", "ODBC Driver 13")
    )

    parts = [
        f"DRIVER={{{MSSQL_DRIVER}}}",
        f"SERVER={MSSQL_SERVER}",
        f"DATABASE={MSSQL_DATABASE}",
    ]

    if _modern_driver:
        parts.append("TrustServerCertificate=yes")   # only valid on modern drivers
        parts.append(f"Connect Timeout={MSSQL_TIMEOUT}")

    if MSSQL_USER and MSSQL_PASSWORD:
        parts += [
            f"UID={MSSQL_USER}",
            f"PWD={MSSQL_PASSWORD}",
        ]
    else:
        parts.append("Trusted_Connection=yes")

    return ";".join(parts)


def get_connection():
    """
    Open and return a live pyodbc connection to the MSSQL server.
    Raises RuntimeError with a helpful message if pyodbc is not installed
    or the connection cannot be established.
    """
    try:
        import pyodbc  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pyodbc is not installed. Install it with:\n"
            "  pip install pyodbc\n"
            "and make sure the ODBC driver is installed on the OS."
        ) from exc

    conn_str = _build_connection_string()
    # Log sanitised connection string (mask password)
    safe = conn_str.replace(MSSQL_PASSWORD, "***") if MSSQL_PASSWORD else conn_str
    logger.info("Connecting with: %s", safe)
    try:
        conn = pyodbc.connect(conn_str, timeout=MSSQL_TIMEOUT)
        logger.info("Connected to MSSQL: %s / %s", MSSQL_SERVER, MSSQL_DATABASE)
        return conn
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to SQL Server at '{MSSQL_SERVER}'.\n"
            f"Check MSSQL_SERVER, MSSQL_USER, MSSQL_PASSWORD in your .env file.\n"
            f"Error: {exc}"
        ) from exc


# ── Column discovery helpers ──────────────────────────────────────────────────

def _table_columns(cursor, table: str) -> list[str]:
    """Return the list of column names for a given table (dbo schema)."""
    cursor.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = ? "
        "ORDER BY ORDINAL_POSITION",
        (table,)
    )
    return [row[0] for row in cursor.fetchall()]


def _pick(columns: list[str], *candidates: str) -> str | None:
    """Return the first candidate column name that exists in 'columns'."""
    col_lower = {c.lower(): c for c in columns}
    for c in candidates:
        if c.lower() in col_lower:
            return col_lower[c.lower()]
    return None


# ── Main fetch function ───────────────────────────────────────────────────────

def fetch_role_data() -> pd.DataFrame:
    """
    Query the remote PROJECT_NAME SQL Server and return a DataFrame with columns:
        role_name, attribute_name, class_name, class_id, group_name, description

    The JOIN path is:
        Role ──(RoleId)──► RoleAttributeMatrix ──(AttributeId)──► RoleAttribute
                                                    └──(GroupId)──► RoleAttributeGroup
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # ── Discover columns so the query works even if schema shifts ────
            role_cols        = _table_columns(cur, "Role")
            attr_cols        = _table_columns(cur, "RoleAttribute")
            grp_cols         = _table_columns(cur, "RoleAttributeGroup")
            matrix_cols      = _table_columns(cur, "RoleAttributeMatrix")

            logger.debug("Role cols: %s", role_cols)
            logger.debug("RoleAttribute cols: %s", attr_cols)
            logger.debug("RoleAttributeGroup cols: %s", grp_cols)
            logger.debug("RoleAttributeMatrix cols: %s", matrix_cols)

            # Role table
            role_id_col   = _pick(role_cols, "RoleId", "Role_Id", "Id")
            role_name_col = _pick(role_cols, "RoleName", "Name", "Role_Name", "RoleDescription")
            role_class_col = _pick(role_cols, "ClassName", "Class", "RoleClass", "ClassId")
            role_classid_col = _pick(role_cols, "ClassId", "Class_Id")

            # RoleAttribute table
            attr_id_col   = _pick(attr_cols, "AttributeId", "Attribute_Id", "Id")
            attr_name_col = _pick(attr_cols, "AttributeName", "Name", "Attribute_Name", "RoleAttributeName")
            attr_desc_col = _pick(attr_cols, "Description", "Desc", "AttributeDescription")
            attr_grp_col  = _pick(attr_cols, "GroupId", "Group_Id", "RoleAttributeGroupId", "AttributeGroupId")

            # RoleAttributeGroup table
            grp_id_col   = _pick(grp_cols, "GroupId", "Group_Id", "Id")
            grp_name_col = _pick(grp_cols, "GroupName", "Name", "Group_Name", "RoleAttributeGroupName")

            # Validate mandatory columns
            missing: list[str] = []
            if not role_id_col:    missing.append("Role.RoleId")
            if not role_name_col:  missing.append("Role.RoleName")
            if not attr_id_col:    missing.append("RoleAttribute.AttributeId")
            if not attr_name_col:  missing.append("RoleAttribute.AttributeName")
            if missing:
                raise RuntimeError(
                    f"Could not find required columns in MSSQL tables: {missing}\n"
                    f"Role cols={role_cols}, RoleAttribute cols={attr_cols}"
                )

            # ── Build SELECT ─────────────────────────────────────────────────
            select_parts = [
                f"r.[{role_name_col}]   AS role_name",
                f"a.[{attr_name_col}]   AS attribute_name",
            ]

            # class_name / class_id: from Role table if available
            if role_class_col:
                select_parts.append(f"r.[{role_class_col}]   AS class_name")
            else:
                select_parts.append("NULL AS class_name")

            if role_classid_col:
                select_parts.append(f"r.[{role_classid_col}] AS class_id")
            else:
                select_parts.append("NULL AS class_id")

            # group_name: from RoleAttributeGroup if joinable
            if attr_grp_col and grp_id_col and grp_name_col:
                select_parts.append(f"g.[{grp_name_col}] AS group_name")
            else:
                select_parts.append("NULL AS group_name")

            # description from RoleAttribute
            if attr_desc_col:
                select_parts.append(f"a.[{attr_desc_col}] AS description")
            else:
                select_parts.append("NULL AS description")

            select_clause = ",\n       ".join(select_parts)

            # ── Build FROM / JOIN ────────────────────────────────────────────
            query = f"""
SELECT {select_clause}
FROM   [dbo].[RoleAttributeMatrix] m
JOIN   [dbo].[Role]          r ON r.[{role_id_col}]  = m.[RoleId]
JOIN   [dbo].[RoleAttribute] a ON a.[{attr_id_col}]  = m.[AttributeId]
"""
            if attr_grp_col and grp_id_col and grp_name_col:
                query += (
                    f"LEFT JOIN [dbo].[RoleAttributeGroup] g "
                    f"ON g.[{grp_id_col}] = a.[{attr_grp_col}]\n"
                )

            logger.debug("Executing query:\n%s", query)
            cur.execute(query)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

        df = pd.DataFrame.from_records(rows, columns=columns)
        logger.info(
            "Fetched %d role-attribute mappings from MSSQL (%s/%s)",
            len(df), MSSQL_SERVER, MSSQL_DATABASE
        )
        return df

    finally:
        conn.close()


def fetch_roles_summary() -> list[dict[str, Any]]:
    """
    Return a lightweight list of all roles (id + name) for validation
    or display purposes.  Used by the /api/roles endpoint.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            role_cols    = _table_columns(cur, "Role")
            role_id_col  = _pick(role_cols, "RoleId", "Role_Id", "Id")
            role_name_col = _pick(role_cols, "RoleName", "Name", "Role_Name")
            if not role_id_col or not role_name_col:
                return []
            cur.execute(
                f"SELECT [{role_id_col}], [{role_name_col}] FROM [dbo].[Role] ORDER BY [{role_name_col}]"
            )
            return [
                {"role_id": str(row[0]), "role_name": row[1]}
                for row in cur.fetchall()
            ]
    finally:
        conn.close()


def test_connection() -> dict[str, Any]:
    """
    Lightweight connectivity test. Returns a dict with:
        ok: bool, server, database, row_count (from RoleAttributeMatrix), error
    """
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM [dbo].[RoleAttributeMatrix]")
            count = cur.fetchone()[0]
        conn.close()
        return {
            "ok": True,
            "server": MSSQL_SERVER,
            "database": MSSQL_DATABASE,
            "role_attribute_matrix_rows": count,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "server": MSSQL_SERVER,
            "database": MSSQL_DATABASE,
            "role_attribute_matrix_rows": None,
            "error": str(exc),
        }
