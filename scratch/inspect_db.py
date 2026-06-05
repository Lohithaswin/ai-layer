import sys
sys.path.append(r"C:\path\to\ai-layer")

from src.vector_store import get_vector_store

store = get_vector_store()
print("Total Chunks:", store.count)
print("Unique Files:", len(store.get_unique_files()))
print("Unique Products:", store.get_unique_products())

# Let's inspect a few documents
conn = store._get_connection()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT product, COUNT(*) FROM documents GROUP BY product;")
        print("\nDocument counts by product:")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]} documents")
            
        cur.execute("SELECT source_file, product FROM documents WHERE product = 'project_module' LIMIT 5;")
        print("\nSample PROJECT_MODULE documents in DB:")
        for row in cur.fetchall():
            print(f"  {row[0]} (product={row[1]})")
finally:
    conn.close()
