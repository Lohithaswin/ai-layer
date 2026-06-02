"""
Golden retrieval regression tests.

Run (after ingest, reranker optional):
  python -m pytest tests/test_golden_retrieval.py -v
  python tests/test_golden_retrieval.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Fast tests: skip cross-encoder
os.environ.setdefault("USE_RERANKER", "false")

GOLDEN_PATH = Path(__file__).parent / "golden" / "questions.json"


def _load_cases() -> list[dict]:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return data["cases"]


def _context_blob(hits: list[dict]) -> str:
    return "\n".join(h.get("parent_text") or h.get("text", "") for h in hits)


def test_golden_retrieval_recall():
    from src.query_router import route_query
    from src.retrieval import retrieve
    from src.vector_store import get_vector_store

    store = get_vector_store()
    if store.count == 0:
        raise RuntimeError("Index empty — run: python -m src.ingest")

    failures: list[str] = []

    for case in _load_cases():
        cid = case["id"]
        history = case.get("history")
        plan = route_query(case["question"], history)
        hits, plan2 = retrieve(
            case["question"],
            store,
            history=history,
            plan=plan,
        )

        if plan2.product_filter != case.get("product_filter") and case.get(
            "product_filter"
        ):
            failures.append(
                f"{cid}: product_filter expected {case['product_filter']}, "
                f"got {plan2.product_filter}"
            )

        if case.get("intent") and plan2.intent != case["intent"]:
            failures.append(
                f"{cid}: intent expected {case['intent']}, got {plan2.intent}"
            )

        if case.get("focus_context") is True and not plan2.focus_context:
            failures.append(f"{cid}: expected focus_context=True, got False")

        if case.get("doc_type_filter") and plan2.doc_type_filter != case.get(
            "doc_type_filter"
        ):
            failures.append(
                f"{cid}: doc_type_filter expected {case['doc_type_filter']}, "
                f"got {plan2.doc_type_filter}"
            )

        ctx = _context_blob(hits)
        for phrase in case.get("context_must_include", []):
            if phrase.lower() not in ctx.lower():
                failures.append(
                    f"{cid}: missing '{phrase}' in retrieved context "
                    f"(top pages: {[h['page'] for h in hits[:3]]})"
                )

        files = {h["source_file"] for h in hits}
        for bad in case.get("forbidden_files", []):
            if bad in files:
                failures.append(f"{cid}: forbidden file in results: {bad}")

        for bad_phrase in case.get("forbidden_phrases_in_context", []):
            if bad_phrase.lower() in ctx.lower():
                failures.append(
                    f"{cid}: forbidden phrase in context: {bad_phrase}"
                )

        max_pages = case.get("max_distinct_pages")
        if max_pages is not None:
            pages = {(h["source_file"], h["page"]) for h in hits}
            if len(pages) > max_pages:
                failures.append(
                    f"{cid}: too many pages in context ({len(pages)}), "
                    f"max {max_pages}: {sorted(pages)}"
                )

        if not hits:
            failures.append(f"{cid}: no hits returned")

    if failures:
        raise AssertionError("\n".join(failures))


if __name__ == "__main__":
    try:
        test_golden_retrieval_recall()
        print("All golden retrieval tests passed.")
    except AssertionError as e:
        print("FAILED:\n", e)
        sys.exit(1)
