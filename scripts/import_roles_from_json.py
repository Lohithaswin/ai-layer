import sys
import json
from pathlib import Path

# Ensure project root is on the path so 'src' is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.postgres_store import PostgreSQLStore

def main():
    in_path = Path("roles_export.json")
    if not in_path.exists():
        print(f"ERROR: {in_path.absolute()} not found.")
        print("Please run export_roles_to_json.py on the RDP, and copy the resulting JSON file here.")
        sys.exit(1)
        
    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    if not data:
        print("No data found in JSON.")
        sys.exit(1)
        
    print(f"Loaded {len(data)} roles from JSON. Inserting into PostgreSQL...")
    
    store = PostgreSQLStore()
    conn = store._get_connection()
    
    try:
        with conn.cursor() as cur:
            # Clear old roles
            cur.execute("TRUNCATE TABLE role_mappings RESTART IDENTITY;")
            
            # Insert new roles
            args_list = [
                (
                    row.get('role_name'),
                    row.get('attribute_name'),
                    row.get('group_name'),
                    row.get('class_name'),
                    row.get('class_id'),
                    row.get('description')
                )
                for row in data
            ]
            
            query = """
                INSERT INTO role_mappings 
                (role_name, attribute_name, group_name, class_name, class_id, description)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            
            cur.executemany(query, args_list)
            conn.commit()
            print(f"SUCCESS! Inserted {len(args_list)} roles into local PostgreSQL.")
            
    except Exception as e:
        conn.rollback()
        print(f"Failed to insert: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
