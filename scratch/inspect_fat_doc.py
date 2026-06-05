import sys
sys.path.append(r"C:\path\to\ai-layer")

from src.vector_store import get_vector_store

store = get_vector_store()
conn = store._get_connection()
try:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.page, c.chunk_index, c.text, c.parent_text 
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.source_file LIKE '%PROJECT_MODULE FAT document.pdf' 
              AND c.page IN (6, 7)
            ORDER BY c.page, c.chunk_index;
            """
        )
        rows = cur.fetchall()
        print(f"Total chunks on pages 6-7: {len(rows)}")
        for row in rows:
            print(f"=== Page {row[0]} Chunk {row[1]} ===")
            print(f"TEXT:\n{row[2]}")
            print(f"PARENT_TEXT:\n{row[3][:800]}")
            print("=" * 60)
finally:
    conn.close()
