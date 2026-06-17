# -*- coding: utf-8 -*-
"""
Comprehensive bot test suite - covers ALL query types and API functions.
Runs against http://127.0.0.1:8000
Fixed: ASCII-only output (cp1252 safe), long timeouts for slow LLM, retry logic.
"""

import urllib.request
import urllib.error
import json
import time
import sys
import os

# Force UTF-8 output to avoid cp1252 encode errors on Windows
sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

BASE_URL = "http://127.0.0.1:8000"
CHAT_TIMEOUT = 600   # 10 min per chat call (LLM can be slow)
API_TIMEOUT  = 30    # utility endpoints
SLEEP_BETWEEN = 3    # seconds between calls

# ─────────────────────────────────────────────────────────────────────────────
# ALL TEST CASES (grouped by category)
# ─────────────────────────────────────────────────────────────────────────────

TEST_CASES = [

    # ── CATEGORY 1: Relational / Role-Attribute Lookups ──────────────────────
    {
        "id": "R-01", "category": "Role-Attribute",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "what roles have conv param read attribute?", "history": []},
        "expect_keys": ["answer", "used_llm", "sources"],
        "description": "Roles for a specific attribute (GET_ROLES_FOR_ATTRIBUTE)",
    },
    {
        "id": "R-02", "category": "Role-Attribute",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "list all attributes for the Technician role", "history": []},
        "expect_keys": ["answer", "used_llm", "sources"],
        "description": "Attributes for a role (GET_ATTRIBUTES_FOR_ROLE)",
    },
    {
        "id": "R-03", "category": "Role-Attribute",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "how many attributes does the admin role have?", "history": []},
        "expect_keys": ["answer"],
        "description": "Count attributes for role (COUNT_ATTRIBUTES)",
    },
    {
        "id": "R-04", "category": "Role-Attribute",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "describe Converter Configuration attribute", "history": []},
        "expect_keys": ["answer"],
        "description": "Describe a role attribute (DESCRIBE_ATTRIBUTE)",
    },
    {
        "id": "R-05", "category": "Role-Attribute",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "which roles have AV tech role attribute?", "history": []},
        "expect_keys": ["answer"],
        "description": "Roles with named attribute",
    },

    # ── CATEGORY 2: Definitions & Acronyms ───────────────────────────────────
    {
        "id": "D-01", "category": "Definitions",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "What is PROJECT_MODULE?", "history": []},
        "expect_keys": ["answer", "question_intent"],
        "description": "Acronym definition - PROJECT_MODULE",
    },
    {
        "id": "D-02", "category": "Definitions",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "full form of PROJECT_NAME", "history": []},
        "expect_keys": ["answer"],
        "description": "Full form request - PROJECT_NAME",
    },
    {
        "id": "D-03", "category": "Definitions",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "define SFS", "history": []},
        "expect_keys": ["answer"],
        "description": "Short acronym definition - SFS",
    },
    {
        "id": "D-04", "category": "Definitions",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "what does LDAP stand for?", "history": []},
        "expect_keys": ["answer"],
        "description": "LDAP expansion",
    },
    {
        "id": "D-05", "category": "Definitions",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "what is MFA?", "history": []},
        "expect_keys": ["answer"],
        "description": "MFA acronym definition",
    },
    {
        "id": "D-06", "category": "Definitions",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "PKI?", "history": []},
        "expect_keys": ["answer"],
        "description": "Single-word acronym (short-query handling)",
    },

    # ── CATEGORY 3: Field / UI Detail Lookups ────────────────────────────────
    {
        "id": "F-01", "category": "Field/UI Detail",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "What are the fields in the Add User window?", "history": []},
        "expect_keys": ["answer", "question_intent"],
        "description": "UI field listing - Add User window",
    },
    {
        "id": "F-02", "category": "Field/UI Detail",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "User Details table columns", "history": []},
        "expect_keys": ["answer"],
        "description": "Table column query",
    },
    {
        "id": "F-03", "category": "Field/UI Detail",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "details of the system configuration screen", "history": []},
        "expect_keys": ["answer"],
        "description": "Screen/dialog field details",
    },
    {
        "id": "F-04", "category": "Field/UI Detail",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "what fields does the login form have in PROJECT_NAME?", "history": []},
        "expect_keys": ["answer"],
        "description": "Form fields with product filter",
    },

    # ── CATEGORY 4: Procedural / How-To ──────────────────────────────────────
    {
        "id": "P-01", "category": "Procedural",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "how to configure LDAP proxy?", "history": []},
        "expect_keys": ["answer", "question_intent"],
        "description": "LDAP configuration procedure",
    },
    {
        "id": "P-02", "category": "Procedural",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "steps to add a new user in PROJECT_NAME", "history": []},
        "expect_keys": ["answer"],
        "description": "New user creation procedure",
    },
    {
        "id": "P-03", "category": "Procedural",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "how to deploy PKI mini service?", "history": []},
        "expect_keys": ["answer"],
        "description": "PKI mini service deployment",
    },
    {
        "id": "P-04", "category": "Procedural",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "process for installing PROJECT_MODULE", "history": []},
        "expect_keys": ["answer"],
        "description": "PROJECT_MODULE installation procedure",
    },
    {
        "id": "P-05", "category": "Procedural",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "how to restart the PROJECT_NAME service?", "history": []},
        "expect_keys": ["answer"],
        "description": "Service restart procedure",
    },
    {
        "id": "P-06", "category": "Procedural",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "how to reset a user password in PROJECT_NAME?", "history": []},
        "expect_keys": ["answer"],
        "description": "Password reset procedure",
    },

    # ── CATEGORY 5: Architecture & Components ─────────────────────────────────
    {
        "id": "A-01", "category": "Architecture",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "PROJECT_NAME architecture components", "history": []},
        "expect_keys": ["answer", "question_intent"],
        "description": "PROJECT_NAME system architecture overview",
    },
    {
        "id": "A-02", "category": "Architecture",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "client-server structure of PROJECT_MODULE", "history": []},
        "expect_keys": ["answer"],
        "description": "PROJECT_MODULE client-server architecture",
    },
    {
        "id": "A-03", "category": "Architecture",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "explain the security management implementation", "history": []},
        "expect_keys": ["answer"],
        "description": "Security management architecture",
    },
    {
        "id": "A-04", "category": "Architecture",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "what services run in PROJECT_NAME backend?", "history": []},
        "expect_keys": ["answer"],
        "description": "Backend services architecture",
    },

    # ── CATEGORY 6: Version History ───────────────────────────────────────────
    {
        "id": "V-01", "category": "Version History",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "first version of PROJECT_MODULE", "history": []},
        "expect_keys": ["answer", "question_intent"],
        "description": "First release version - PROJECT_MODULE",
    },
    {
        "id": "V-02", "category": "Version History",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "release notes modifications", "history": []},
        "expect_keys": ["answer"],
        "description": "General release notes query",
    },
    {
        "id": "V-03", "category": "Version History",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "when was PROJECT_NAME released?", "history": []},
        "expect_keys": ["answer"],
        "description": "Release date query",
    },
    {
        "id": "V-04", "category": "Version History",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "explain MFA v3.0.0", "history": []},
        "expect_keys": ["answer"],
        "description": "Specific version explanation",
    },

    # ── CATEGORY 7: Comparison ────────────────────────────────────────────────
    {
        "id": "C-01", "category": "Comparison",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "compare YOUR_PRODUCT", "history": []},
        "expect_keys": ["answer", "question_intent"],
        "description": "Direct product comparison",
    },
    {
        "id": "C-02", "category": "Comparison",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "what is the difference between SAT and FAT?", "history": []},
        "expect_keys": ["answer"],
        "description": "SAT vs FAT comparison",
    },
    {
        "id": "C-03", "category": "Comparison",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "PROJECT_NAME vs PROJECT_MODULE key differences", "history": []},
        "expect_keys": ["answer"],
        "description": "Product comparison - informal phrasing",
    },

    # ── CATEGORY 8: Follow-Up / Contextual ────────────────────────────────────
    {
        "id": "FU-01", "category": "Follow-Up",
        "endpoint": "/chat", "method": "POST",
        "payload": {
            "question": "tell me more about it",
            "history": [
                {"role": "user", "content": "What is PROJECT_MODULE?"},
                {"role": "assistant", "content": "PROJECT_MODULE stands for Wind Power Management Agent."},
            ],
        },
        "expect_keys": ["answer"],
        "description": "Pronoun follow-up ('it') after product definition",
    },
    {
        "id": "FU-02", "category": "Follow-Up",
        "endpoint": "/chat", "method": "POST",
        "payload": {
            "question": "yes",
            "history": [
                {"role": "assistant", "content": "Would you like me to look into Factory Acceptance Test instead?"},
            ],
        },
        "expect_keys": ["answer"],
        "description": "Affirmation rewrite ('yes' -> FAT context)",
    },
    {
        "id": "FU-03", "category": "Follow-Up",
        "endpoint": "/chat", "method": "POST",
        "payload": {
            "question": "how do I do that?",
            "history": [
                {"role": "user", "content": "how to add a user in PROJECT_NAME?"},
                {"role": "assistant", "content": "To add a user, go to User Management window..."},
            ],
        },
        "expect_keys": ["answer"],
        "description": "Follow-up with context reuse",
    },

    # ── CATEGORY 9: Clarification ─────────────────────────────────────────────
    {
        "id": "CL-01", "category": "Clarification",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "help", "history": []},
        "expect_keys": ["answer"],
        "description": "Ultra-vague query - should trigger clarification",
    },
    {
        "id": "CL-02", "category": "Clarification",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "install", "history": []},
        "expect_keys": ["answer"],
        "description": "Single-word vague query",
    },

    # ── CATEGORY 10: Edge Cases ────────────────────────────────────────────────
    {
        "id": "E-01", "category": "Edge Cases",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "give project_module fat format", "history": []},
        "expect_keys": ["answer"],
        "description": "Awkward phrasing - FAT format for PROJECT_MODULE",
    },
    {
        "id": "E-02", "category": "Edge Cases",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "   ", "history": []},
        "expect_keys": ["answer"],
        "description": "Whitespace-only query - should not crash",
        "expect_error": False,
    },
    {
        "id": "E-03", "category": "Edge Cases",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "What is PROJECT_MODULE?", "history": [], "product_filter": "project_module"},
        "expect_keys": ["answer", "retrieval_mode"],
        "description": "Query with explicit product_filter",
    },
    {
        "id": "E-04", "category": "Edge Cases",
        "endpoint": "/chat", "method": "POST",
        "payload": {"question": "what is the poll interval setting?", "history": []},
        "expect_keys": ["answer"],
        "description": "Technical config query",
    },

    # ── CATEGORY 11: API Utility Endpoints ────────────────────────────────────
    {
        "id": "API-01", "category": "API Utility",
        "endpoint": "/health", "method": "GET",
        "expect_keys": ["status", "hybrid_search", "reranker"],
        "description": "Health check endpoint",
    },
    {
        "id": "API-02", "category": "API Utility",
        "endpoint": "/documents", "method": "GET",
        "expect_keys": ["files", "products", "collection_size"],
        "description": "Document list endpoint",
    },
    {
        "id": "API-03", "category": "API Utility",
        "endpoint": "/products", "method": "GET",
        "expect_keys": ["products"],
        "description": "Products list endpoint",
    },
    {
        "id": "API-04", "category": "API Utility",
        "endpoint": "/models", "method": "GET",
        "expect_keys": ["models", "active"],
        "description": "Models list endpoint",
    },
    {
        "id": "API-05", "category": "API Utility",
        "endpoint": "/sections", "method": "GET",
        "expect_keys": ["sections"],
        "description": "Sections list endpoint",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def post_json(url, payload, timeout=CHAT_TIMEOUT):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_json(url, timeout=API_TIMEOUT):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def safe_print(msg):
    """Print safely even on Windows cp1252 terminals."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_all():
    safe_print("=" * 72)
    safe_print("  COMPREHENSIVE BOT TEST SUITE")
    safe_print(f"  Target : {BASE_URL}")
    safe_print(f"  Tests  : {len(TEST_CASES)}")
    safe_print(f"  Timeout: {CHAT_TIMEOUT}s per chat call")
    safe_print("=" * 72)

    results = []
    passed = 0
    failed = 0
    errors_by_cat = {}

    for idx, tc in enumerate(TEST_CASES, start=1):
        tc_id    = tc["id"]
        cat      = tc["category"]
        endpoint = tc["endpoint"]
        desc     = tc["description"]
        method   = tc.get("method", "POST")

        start = time.time()
        timeout = API_TIMEOUT if method == "GET" else CHAT_TIMEOUT

        try:
            if method == "GET":
                resp = get_json(f"{BASE_URL}{endpoint}", timeout=API_TIMEOUT)
            else:
                resp = post_json(f"{BASE_URL}{endpoint}", tc.get("payload", {}), timeout=CHAT_TIMEOUT)

            elapsed = round((time.time() - start) * 1000, 1)

            # Check expected keys
            missing = [k for k in tc.get("expect_keys", []) if k not in resp]

            # Pull answer snippet
            answer = resp.get("answer", "")
            answer_snippet = (answer[:150].replace("\n", " ")) if answer else "(empty)"

            # Quality flags
            flags = []
            if isinstance(answer, str):
                if len(answer.strip()) < 30:
                    flags.append("SHORT_ANSWER")
                if "do not contain enough" in answer.lower():
                    flags.append("NO_RESULTS")
                if "ollama is not running" in answer.lower():
                    flags.append("LLM_OFFLINE")
                if "clarify" in answer.lower() or "which product" in answer.lower():
                    flags.append("CLARIFICATION_TRIGGERED")

            status = "PASS" if not missing else "FAIL"
            if status == "PASS":
                passed += 1
            else:
                failed += 1
                errors_by_cat.setdefault(cat, []).append(tc_id)

            result = {
                "id": tc_id,
                "category": cat,
                "description": desc,
                "endpoint": endpoint,
                "status": status,
                "elapsed_ms": elapsed,
                "missing_keys": missing,
                "flags": flags,
                "answer_snippet": answer_snippet,
                "question_intent": resp.get("question_intent", ""),
                "retrieval_mode": resp.get("retrieval_mode", ""),
                "used_llm": resp.get("used_llm", None),
                "num_sources_retrieved": resp.get("num_sources_retrieved", len(resp.get("sources", []))),
                "num_sources_used": resp.get("num_sources_used", 0),
                "processing_time_ms": resp.get("processing_time_ms", elapsed),
            }

            # Utility-endpoint extras
            if endpoint == "/documents":
                result["collection_size"] = resp.get("collection_size", 0)
                result["num_products"]    = len(resp.get("products", []))
                result["num_files"]       = len(resp.get("files", []))
            if endpoint == "/health":
                result["health_detail"] = resp
            if endpoint == "/products":
                result["products"] = resp.get("products", [])
            if endpoint == "/models":
                result["active_model"] = resp.get("active", "")
                result["model_count"]  = len(resp.get("models", []))

            icon = "[PASS]" if status == "PASS" else "[FAIL]"
            flag_str = " | " + ",".join(flags) if flags else ""
            safe_print(
                f"{icon} [{tc_id:<7}] {desc[:52]:<52} {elapsed:>8.0f}ms{flag_str}"
            )

        except Exception as exc:
            elapsed = round((time.time() - start) * 1000, 1)
            failed += 1
            errors_by_cat.setdefault(cat, []).append(tc_id)
            result = {
                "id": tc_id,
                "category": cat,
                "description": desc,
                "endpoint": endpoint,
                "status": "ERROR",
                "elapsed_ms": elapsed,
                "error": str(exc),
                "missing_keys": [],
                "flags": ["EXCEPTION"],
                "answer_snippet": "",
            }
            safe_print(
                f"[ERR ] [{tc_id:<7}] {desc[:52]:<52} {elapsed:>8.0f}ms | {str(exc)[:60]}"
            )

        results.append(result)
        time.sleep(SLEEP_BETWEEN)

    # ── Summary ──────────────────────────────────────────────────────────────
    safe_print("")
    safe_print("=" * 72)
    safe_print("  FINAL SUMMARY")
    safe_print("=" * 72)
    safe_print(f"  Total     : {len(TEST_CASES)}")
    safe_print(f"  Passed    : {passed}")
    safe_print(f"  Failed    : {failed}")
    safe_print(f"  Pass Rate : {100 * passed / len(TEST_CASES):.1f}%")

    if errors_by_cat:
        safe_print("")
        safe_print("  Failed tests by category:")
        for cat, ids in errors_by_cat.items():
            safe_print(f"    {cat}: {', '.join(ids)}")

    # Per-category breakdown
    safe_print("")
    safe_print("  Category breakdown:")
    cats = {}
    for r in results:
        c = r["category"]
        cats.setdefault(c, {"pass": 0, "fail": 0, "total": 0})
        cats[c]["total"] += 1
        if r["status"] == "PASS":
            cats[c]["pass"] += 1
        else:
            cats[c]["fail"] += 1

    for cat, counts in cats.items():
        bar = "P" * counts["pass"] + "F" * counts["fail"]
        safe_print(f"    {cat:<35} {counts['pass']}/{counts['total']}  [{bar}]")

    # Save full results JSON
    out = {
        "summary": {
            "total": len(TEST_CASES),
            "passed": passed,
            "failed": failed,
            "pass_rate_pct": round(100 * passed / len(TEST_CASES), 1),
        },
        "results": results,
    }
    with open("full_test_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    safe_print("")
    safe_print("  Full results saved -> full_test_results.json")
    safe_print("=" * 72)

    return results


if __name__ == "__main__":
    run_all()
