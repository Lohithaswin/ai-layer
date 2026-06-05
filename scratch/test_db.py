import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='rag_db', user='postgres', password='password')
cur = conn.cursor()
cur.execute("SELECT d.source_file, c.page, c.text FROM document_chunks c JOIN documents d ON c.document_id = d.id WHERE c.text ILIKE '%project_module%' AND c.text ILIKE '%project_name%'")
rows = cur.fetchall()
print(f"Total matching chunks: {len(rows)}")
if rows:
    print(rows[0])
