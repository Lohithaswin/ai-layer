import psycopg2

def test():
    conn = psycopg2.connect(host="localhost", port=5433, database="rag_db", user="postgres", password="password")
    sql = """
        SELECT DISTINCT matches[2] as section_title, d.source_file
        FROM document_chunks c
        JOIN documents d ON c.document_id = d.id,
        regexp_matches(c.text, '(^|\n)\s*(\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{4,100})', 'g') as matches
        LIMIT 10;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        for row in cur.fetchall():
            print(row)

if __name__ == "__main__":
    test()
