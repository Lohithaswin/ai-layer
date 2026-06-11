import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.postgres_store import PostgreSQLStore

def main():
    store = PostgreSQLStore()
    
    query1 = "explain the role att commission"
    print(f"--- Dense search for: {query1} ---")
    hits = store.search(query1, top_k=3, where={"$eq": {"product": "role"}})
    for h in hits:
        print(f"Score: {h['score']:.4f} | {h['text'][:100]}...")

    query2 = "commission"
    print(f"\n--- Sparse search for: {query2} ---")
    hits = store.search_sparse(query2, top_k=3, filters={"product": "role"})
    for h in hits:
        print(f"Score: {h['score']:.4f} | {h['text'][:100]}...")

if __name__ == "__main__":
    main()
