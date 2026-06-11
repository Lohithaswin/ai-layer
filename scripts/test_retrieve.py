import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.retrieval import retrieve
from src.postgres_store import PostgreSQLStore

def main():
    store = PostgreSQLStore()
    
    question = "explain the role att commission"
    print(f"Retrieving for: {question}")
    
    hits, plan = retrieve(question, store, product_filter="role")
    
    for h in hits:
        print(f"Score: {h['score']:.4f} | Source: {h['source_file']} | Text: {h['text'][:100]}...")

if __name__ == "__main__":
    main()
