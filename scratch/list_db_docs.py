import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5433"))  # Test both ports
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "password")
PG_DB = os.getenv("PG_DB", "rag_db")

for port in [5433, 5432]:
    print(f"Connecting to port {port}...")
    try:
        conn = psycopg2.connect(
            host=PG_HOST,
            port=port,
            database=PG_DB,
            user=PG_USER,
            password=PG_PASSWORD,
            connect_timeout=3
        )
        print("Connected!")
        with conn.cursor() as cur:
            cur.execute("SELECT id, source_file, product, doc_type, is_demo, manual_version FROM documents;")
            rows = cur.fetchall()
            print(f"Found {len(rows)} documents in 'documents' table:")
            for row in rows:
                print(f"  - ID: {row[0]}, File: {row[1]}, Product: {row[2]}, Type: {row[3]}, Demo: {row[4]}, Version: {row[5]}")
                
            cur.execute("SELECT COUNT(*) FROM document_chunks;")
            chunk_count = cur.fetchone()[0]
            print(f"Total chunks: {chunk_count}")
        conn.close()
        break
    except Exception as e:
        print(f"Failed on port {port}: {e}")
