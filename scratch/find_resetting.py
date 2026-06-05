import sys
sys.path.append(r"C:\path\to\ai-layer")

from src.vector_store import get_vector_store

store = get_vector_store()
conn = store._get_connection()
try:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.source_file, c.page, c.chunk_index, c.text
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.text LIKE '%Resetting Passwords%' OR c.parent_text LIKE '%Resetting Passwords%'
            LIMIT 10;
            """
        )
        rows = cur.fetchall()
        print(f"Total matching chunks in DB: {len(rows)}")
        for r in rows:
            print(f"File: {r[0]} | Page: {r[1]} | Chunk: {r[2]}")
            print(f"Text:\n{r[3][:300]}\n")
finally:
    conn.close()
