"""
role_ingestor.py
----------------
Ingests role-attribute data into the local PostgreSQL 'role_mappings' table.

Supports two data sources (controlled by the ROLE_DATA_SOURCE env var):

    ROLE_DATA_SOURCE=excel  (default)
        Reads from Excel files:
            • <ROLE_ATTR_DIR>/Role Attributes Doc.xlsx
            • <ROLE_ATTR_DIR>/RoleAttDescriptions.xlsx

    ROLE_DATA_SOURCE=mssql
        Reads live from the remote PROJECT_NAME SQL Server via src.mssql_connector.
        Requires MSSQL_* env vars to be set in .env.

Both paths produce the same normalised DataFrame and insert it into the
PostgreSQL 'role_mappings' table, so the RAG pipeline is unchanged.
"""

import os
import pandas as pd
from src.postgres_store import PostgreSQLStore
from src.config import ROLE_ATTR_DIR

# Which source to use: "excel" (default) or "mssql"
ROLE_DATA_SOURCE = os.getenv("ROLE_DATA_SOURCE", "excel").lower().strip()


# ── Excel source (original path) ──────────────────────────────────────────────

def _load_from_excel() -> pd.DataFrame:
    """Load role-attribute data from local Excel files and return normalised DataFrame."""
    import shutil
    import tempfile

    role_doc_path = ROLE_ATTR_DIR / "Role Attributes Doc.xlsx"
    desc_doc_path = ROLE_ATTR_DIR / "RoleAttDescriptions.xlsx"

    if not role_doc_path.exists() or not desc_doc_path.exists():
        raise FileNotFoundError(
            f"Excel files not found in {ROLE_ATTR_DIR}.\n"
            "Set ROLE_ATTR_DIR in your .env or switch to ROLE_DATA_SOURCE=mssql."
        )

    # Use temp files to bypass PermissionError if user has them open in Excel
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_role = os.path.join(tmpdir, "roles.xlsx")
        tmp_desc = os.path.join(tmpdir, "desc.xlsx")
        shutil.copy2(role_doc_path, tmp_role)
        shutil.copy2(desc_doc_path, tmp_desc)

        try:
            df_matrix = pd.read_excel(tmp_role, sheet_name="RoleClassAttributes")
        except Exception:
            df_matrix = pd.read_excel(tmp_role)
        df_desc = pd.read_excel(tmp_desc)

    print(f"Loaded {len(df_matrix)} role assignments and {len(df_desc)} descriptions from Excel.")

    # Strip + normalise column names
    df_matrix.columns = df_matrix.columns.str.strip()
    df_desc.columns = df_desc.columns.str.strip()

    col_mapping_matrix = {
        "RoleName": "role_name",
        "RoleAttName": "attribute_name",
        "Role Attr Group": "group_name",
        "Role": "role_name",
        "RoleAttributeName": "attribute_name",
        "Class": "class_name",
        "Class ID": "class_id",
    }
    col_mapping_desc = {
        "Role Attribute Name": "attribute_name",
        "RoleAttributeName": "attribute_name",
        "Description": "description",
    }

    df_matrix = df_matrix.rename(columns=col_mapping_matrix)
    df_desc   = df_desc.rename(columns=col_mapping_desc)

    if "attribute_name" not in df_matrix.columns:
        raise ValueError("attribute_name column not found in matrix Excel sheet.")
    if "attribute_name" not in df_desc.columns:
        raise ValueError("attribute_name column not found in descriptions Excel sheet.")

    df_matrix = df_matrix.dropna(subset=["attribute_name"])
    df_desc   = df_desc.dropna(subset=["attribute_name"])

    df_matrix["attribute_name"] = df_matrix["attribute_name"].astype(str).str.strip()
    df_desc["attribute_name"]   = df_desc["attribute_name"].astype(str).str.strip()

    merged = pd.merge(
        df_matrix,
        df_desc[["attribute_name", "description"]],
        on="attribute_name",
        how="left",
    )
    return merged


# ── MSSQL source (new path) ────────────────────────────────────────────────────

def _load_from_mssql() -> pd.DataFrame:
    """Fetch role-attribute data from the remote PROJECT_NAME SQL Server."""
    from src.mssql_connector import fetch_role_data
    print("Fetching role-attribute data from remote MSSQL (PROJECT_NAME)...")
    df = fetch_role_data()
    print(f"Fetched {len(df)} role-attribute mappings from MSSQL.")
    return df


# ── Normalise + insert into PostgreSQL ────────────────────────────────────────

def _normalise(merged: pd.DataFrame) -> pd.DataFrame:
    """Ensure required columns exist and are clean."""
    merged["description"] = merged.get("description", "").fillna("").astype(str)
    merged["group_name"]  = merged.get("group_name", "").fillna("").astype(str)
    merged["role_name"]   = merged["role_name"].astype(str).str.strip()

    if "class_name" not in merged.columns:
        merged["class_name"] = ""
    if "class_id" not in merged.columns:
        merged["class_id"] = ""

    merged["class_name"] = merged["class_name"].fillna("").astype(str).str.strip()
    merged["class_id"]   = merged["class_id"].fillna("").astype(str).str.strip()

    return merged


def _insert_into_postgres(merged: pd.DataFrame) -> None:
    """Truncate and re-insert all rows into the role_mappings table."""
    from psycopg2.extras import execute_values

    store = PostgreSQLStore()
    conn  = store._get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE role_mappings;")
            rows = [
                (
                    row["role_name"],
                    row["attribute_name"],
                    row["class_name"],
                    row["class_id"],
                    row["group_name"],
                    row["description"],
                )
                for _, row in merged.iterrows()
            ]
            execute_values(
                cur,
                "INSERT INTO role_mappings "
                "(role_name, attribute_name, class_name, class_id, group_name, description) "
                "VALUES %s",
                rows,
            )
            conn.commit()
            print(
                f"Successfully inserted {len(rows)} role mappings into "
                "PostgreSQL table 'role_mappings'."
            )
    except Exception as e:
        print(f"Database error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Public entry point ────────────────────────────────────────────────────────

def run_ingestion(source: str | None = None) -> None:
    """
    Run the full ingestion pipeline.

    Args:
        source: Override the ROLE_DATA_SOURCE env var.
                Pass "excel" or "mssql".  If None, uses the env var.
    """
    effective_source = (source or ROLE_DATA_SOURCE).lower().strip()
    print(f"[role_ingestor] Starting ingestion — source: {effective_source}")

    if effective_source == "mssql":
        merged = _load_from_mssql()
    else:
        if effective_source not in ("excel",):
            print(
                f"[role_ingestor] Unknown ROLE_DATA_SOURCE='{effective_source}'. "
                "Falling back to 'excel'."
            )
        merged = _load_from_excel()

    merged = _normalise(merged)
    print(f"[role_ingestor] Preparing {len(merged)} rows for PostgreSQL insertion...")
    _insert_into_postgres(merged)
    print("[role_ingestor] Ingestion complete.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest role-attribute data into PostgreSQL.")
    parser.add_argument(
        "--source",
        choices=["excel", "mssql"],
        default=None,
        help="Data source override (default: read from ROLE_DATA_SOURCE env var)",
    )
    args = parser.parse_args()
    run_ingestion(source=args.source)
