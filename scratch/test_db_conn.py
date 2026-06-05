import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "password")
PG_DB = os.getenv("PG_DB", "rag_db")

for port in [5432, 5433]:
    print(f"Testing port {port}...")
    try:
        conn = psycopg2.connect(
            host=PG_HOST,
            port=port,
            database=PG_DB,
            user=PG_USER,
            password=PG_PASSWORD,
            connect_timeout=3
        )
        print(f"SUCCESS: Connected on port {port}!")
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            print("Version:", cur.fetchone()[0])
        conn.close()
        break
    except Exception as e:
        print(f"FAILED on port {port}: {e}")
