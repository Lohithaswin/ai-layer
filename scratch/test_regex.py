import os
from src.postgres_store import PostgreSQLStore

def test():
    store = PostgreSQLStore()
    sql = """
        SELECT DISTINCT matches[2] as section_title, d.source_file
        FROM document_chunks c
        JOIN documents d ON c.document_id = d.id,
        regexp_matches(c.text, '(^|\n)\s*(\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{4,100})', 'g') as matches
        LIMIT 10;
    """
    conn = store._get_connection()
    with conn.cursor() as cur:
        cur.execute(sql)
        for row in cur.fetchall():
            print(row)

if __name__ == "__main__":
    test()
