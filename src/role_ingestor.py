import os
import pandas as pd
from src.postgres_store import PostgreSQLStore
from src.config import ROLE_ATTR_DIR

def run_ingestion():
    print("Loading Role Excel files...")
    role_doc_path = ROLE_ATTR_DIR / "Role Attributes Doc.xlsx"
    desc_doc_path = ROLE_ATTR_DIR / "RoleAttDescriptions.xlsx"

    if not role_doc_path.exists() or not desc_doc_path.exists():
        print(f"Excel files not found in {ROLE_ATTR_DIR}. Aborting.")
        return

    import shutil
    import tempfile
    
    # Use temp files to bypass PermissionError if user has them open in Excel
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_role = os.path.join(tmpdir, "roles.xlsx")
        tmp_desc = os.path.join(tmpdir, "desc.xlsx")
        
        shutil.copy2(role_doc_path, tmp_role)
        shutil.copy2(desc_doc_path, tmp_desc)

        # Load matrix (one row per role-attribute assignment)
        try:
            df_matrix = pd.read_excel(tmp_role, sheet_name="RoleClassAttributes")
        except Exception:
            # Fallback if the sheet name is different
            df_matrix = pd.read_excel(tmp_role)
        
        # Load descriptions
        df_desc = pd.read_excel(tmp_desc)

    print(f"Loaded {len(df_matrix)} role assignments and {len(df_desc)} descriptions.")

    print(f"Matrix columns: {df_matrix.columns.tolist()}")
    print(f"Desc columns: {df_desc.columns.tolist()}")

    # Strip column names
    df_matrix.columns = df_matrix.columns.str.strip()
    df_desc.columns = df_desc.columns.str.strip()

    # Normalize column names for safe merging
    # Handle possible variations in column names
    col_mapping_matrix = {
        "RoleName": "role_name",
        "RoleAttName": "attribute_name",
        "Role Attr Group": "group_name",
        "Role": "role_name",
        "RoleAttributeName": "attribute_name",
        "Class": "class_name",
        "Class ID": "class_id"
    }
    col_mapping_desc = {
        "Role Attribute Name": "attribute_name",
        "RoleAttributeName": "attribute_name",
        "Description": "description"
    }
    
    df_matrix = df_matrix.rename(columns=col_mapping_matrix)
    df_desc = df_desc.rename(columns=col_mapping_desc)
    
    if "attribute_name" not in df_matrix.columns:
        print("Error: attribute_name column not found in matrix.")
        return
    if "attribute_name" not in df_desc.columns:
        print("Error: attribute_name column not found in desc.")
        return

    # Drop any null attributes
    df_matrix = df_matrix.dropna(subset=["attribute_name"])
    df_desc = df_desc.dropna(subset=["attribute_name"])

    # Clean whitespace
    df_matrix["attribute_name"] = df_matrix["attribute_name"].astype(str).str.strip()
    df_desc["attribute_name"] = df_desc["attribute_name"].astype(str).str.strip()

    # Merge descriptions into the matrix based on attribute_name
    merged = pd.merge(df_matrix, df_desc[["attribute_name", "description"]], on="attribute_name", how="left")
    
    # Fill missing descriptions with empty string
    merged["description"] = merged["description"].fillna("").astype(str)
    merged["group_name"] = merged["group_name"].fillna("").astype(str)
    merged["role_name"] = merged["role_name"].astype(str).str.strip()
    
    if "class_name" not in merged.columns:
        merged["class_name"] = ""
    if "class_id" not in merged.columns:
        merged["class_id"] = ""
        
    merged["class_name"] = merged["class_name"].fillna("").astype(str).str.strip()
    merged["class_id"] = merged["class_id"].fillna("").astype(str).str.strip()

    print(f"Merged successfully. Preparing {len(merged)} rows for PostgreSQL insertion...")

    # Insert into PostgreSQL
    store = PostgreSQLStore()
    conn = store._get_connection()
    try:
        with conn.cursor() as cur:
            # Clear existing mappings
            cur.execute("TRUNCATE TABLE role_mappings;")
            
            # Prepare rows
            rows = [
                (row["role_name"], row["attribute_name"], row["class_name"], row["class_id"], row["group_name"], row["description"])
                for _, row in merged.iterrows()
            ]
            
            from psycopg2.extras import execute_values
            execute_values(
                cur,
                "INSERT INTO role_mappings (role_name, attribute_name, class_name, class_id, group_name, description) VALUES %s",
                rows
            )
            conn.commit()
            print(f"Successfully inserted {len(rows)} role mappings into PostgreSQL table 'role_mappings'.")
    except Exception as e:
        print(f"Database error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    run_ingestion()
