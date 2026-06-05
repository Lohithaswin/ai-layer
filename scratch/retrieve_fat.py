import sys
sys.path.append(r"C:\path\to\ai-layer")

from src.retrieval import retrieve
from src.vector_store import get_vector_store

store = get_vector_store()
hits, plan = retrieve("give project_module FAT format", store)

print(f"Plan Intent: {plan.intent}")
print(f"Plan search queries: {plan.search_queries}")
print(f"Plan product filter: {plan.product_filter}")
print(f"Total hits retrieved: {len(hits)}")
for i, h in enumerate(hits):
    print(f"\n--- Hit {i+1} ---")
    print(f"Source: {h.get('source_file')} (Page {h.get('page')})")
    print(f"Score: {h.get('score')}")
    print(f"Section: {h.get('section_title')}")
    print(f"Text:\n{h.get('text')[:300]}...")
