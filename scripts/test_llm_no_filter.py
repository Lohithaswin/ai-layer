import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.retrieval import retrieve
from src.postgres_store import PostgreSQLStore
from src.llm import generate_answer

def main():
    store = PostgreSQLStore()
    
    question = "explain the role att commission"
    print(f"Retrieving for: {question} (NO PRODUCT FILTER)")
    
    # Do not pass product_filter
    hits, plan = retrieve(question, store)
    
    print(f"Routed Product Filter: {plan.product_filter}")
    for i, h in enumerate(hits[:5]):
        print(f"Rank {i+1} [{h['score']:.4f}]: {h['text'][:150]}...")
        
    print("\nGenerating Answer...")
    ans = generate_answer(None, question, hits, plan)
    print("\n--- LLM ANSWER ---")
    print(ans)

if __name__ == "__main__":
    main()
