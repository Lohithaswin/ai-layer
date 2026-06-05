import sys
sys.path.append(r"C:\path\to\ai-layer")

from pathlib import Path
from src.vector_store import get_vector_store
from src.doc_registry import classify_pdf

store = get_vector_store()
conn = store._get_connection()
try:
    with conn.cursor() as cur:
        # Get all unique documents in the database
        cur.execute("SELECT id, source_file FROM documents;")
        rows = cur.fetchall()
        print(f"Found {len(rows)} documents to update in database...")
        
        updated_count = 0
        for doc_id, source_file in rows:
            # Classify dynamically using filename
            meta = classify_pdf(Path(source_file))
            
            # Update the database in-place
            cur.execute("""
                UPDATE documents 
                SET product = %s, doc_type = %s, manual_version = %s
                WHERE id = %s;
            """, (meta.product, meta.doc_type, meta.manual_version, doc_id))
            updated_count += 1
            
        conn.commit()
        print(f"Successfully updated metadata for {updated_count} documents in-place!")
        
        # Verify unique products now
        cur.execute("SELECT DISTINCT product FROM documents;")
        print("Updated unique products in DB:", [r[0] for r in cur.fetchall()])
finally:
    conn.close()
