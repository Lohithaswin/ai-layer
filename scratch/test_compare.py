import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(r"C:\path\to\ai-layer")

from src.vector_store import get_vector_store

store = get_vector_store()
dense = store.search("PROJECT_NAME overview definition", top_k=3)
for i, h in enumerate(dense):
    print(f"--- Dense {i+1} ---")
    print(f"Source: {h.get('source_file')} (Page {h.get('page')})")
    print(f"Score: {h.get('score')}")
    print(f"Text: {h.get('text')[:300]}")
    
dense = store.search("compare project_module and project_name", top_k=3)
for i, h in enumerate(dense):
    print(f"--- Dense 2 {i+1} ---")
    print(f"Source: {h.get('source_file')} (Page {h.get('page')})")
    print(f"Score: {h.get('score')}")
    print(f"Text: {h.get('text')[:300]}")
