import sys
sys.path.append(r"C:\path\to\ai-layer")

from src.retrieval import retrieve
from src.vector_store import get_vector_store
from src.llm import _build_context, _build_prompt, generate_answer
from src.query_router import QueryPlan

store = get_vector_store()
hits, plan = retrieve("give project_module fat format", store)
context = _build_context(hits)

print("=== CONTEXT SENT TO LLM ===")
print(context)
print("\n=== GENERATED ANSWER ===")
ans = generate_answer(None, "give project_module fat format", hits, plan)
print(ans)
