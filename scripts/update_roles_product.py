import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.postgres_store import PostgreSQLStore

def main():
    store = PostgreSQLStore()
    conn = store._get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE documents 
                SET product = 'role' 
                WHERE source_file ILIKE '%Role Attributes%' 
                   OR source_file ILIKE '%RoleAttDescriptions%'
                   OR source_file ILIKE '%.xlsx'
                   OR source_file ILIKE '%.docx';
            """)
            print(f"Updated {cur.rowcount} rows to product='role'.")
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
