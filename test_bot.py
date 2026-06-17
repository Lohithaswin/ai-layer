import urllib.request
import json
import time

QUERIES = [
    # 1. Relational Lookups
    "what roles have conv param read attribute?",
    "list all roles for Converter Configuration",
    "roles with AV tech role",
    
    # 2. Describe Attributes
    "describe Converter",
    "explain PROJECT_NAME Roles",
    "definition of Converter Configuration",
    
    # 3. Acronyms & Definitions
    "What is PROJECT_MODULE?",
    "full form of PROJECT_NAME",
    "define SFS",
    "what does LDAP stand for?",
    
    # 4. Field / UI Detail Lookups
    "What are the fields in the Add User window?",
    "User Details table columns",
    "details of the system configuration screen",
    
    # 5. Procedural / How-To Queries
    "how to configure LDAP proxy?",
    "steps to add a new user",
    "how to deploy PKI mini service?",
    "process for installing PROJECT_MODULE",
    "how to restart the system",
    
    # 6. Architecture & Component Queries
    "PROJECT_NAME architecture components",
    "client-server structure of PROJECT_MODULE",
    "explain the security management implementation",
    
    # 7. Version History Queries
    "first version of PROJECT_MODULE",
    "release notes modifications",
    "when was PROJECT_NAME released?",
    
    # 8. Follow-ups / Contextual Queries (sending history)
    {"query": "tell me more about it", "history": [{"role": "user", "content": "What is PROJECT_MODULE?"}, {"role": "assistant", "content": "PROJECT_MODULE is Wind Power Management Agent."}]},
    {"query": "yes", "history": [{"role": "assistant", "content": "Would you like me to look into Factory Acceptance Test instead?"}]},
    
    # 9. Difficult / Edge Cases
    "give project_module fat format",
    "compare YOUR_PRODUCT",
    "what is the difference between SAT and FAT?",
    "explain MFA v3.0.0"
]

def run_tests():
    url = "http://127.0.0.1:8000/chat"
    headers = {"Content-Type": "application/json"}
    
    print("Waiting 5 seconds for API server to start...")
    time.sleep(5)
    
    results = []
    
    print(f"Running {len(QUERIES)} test queries...")
    for i, q_obj in enumerate(QUERIES):
        history = []
        if isinstance(q_obj, dict):
            question = q_obj["query"]
            history = q_obj["history"]
        else:
            question = q_obj
            
        payload = {
            "question": question,
            "history": history
        }
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        
        max_retries = 2
        for attempt in range(max_retries):
            try:
                start_t = time.time()
                with urllib.request.urlopen(req, timeout=180) as response:
                    resp_data = json.loads(response.read().decode('utf-8'))
                    elapsed = time.time() - start_t
                    
                    results.append({
                        "id": i + 1,
                        "question": question,
                        "answer": resp_data.get("answer", ""),
                        "used_llm": resp_data.get("used_llm", True),
                        "note": resp_data.get("note", ""),
                        "processing_time": round(elapsed, 2),
                        "status": "SUCCESS"
                    })
                    print(f"[{i+1}/{len(QUERIES)}] SUCCESS: {question[:50]}... (used_llm: {resp_data.get('used_llm')})")
                    time.sleep(2)  # small delay to prevent rapid limits
                    break
            except urllib.error.HTTPError as e:
                if attempt < max_retries - 1 and e.code in [429, 500]:
                    print(f"[{i+1}/{len(QUERIES)}] Rate limit hit (HTTP {e.code}). Sleeping 60s...")
                    time.sleep(60)
                else:
                    results.append({"id": i + 1, "question": question, "error": str(e), "status": "FAILED"})
                    print(f"[{i+1}/{len(QUERIES)}] FAILED: {question[:50]}... - {e}")
            except Exception as e:
                if attempt < max_retries - 1 and "timeout" in str(e).lower():
                    print(f"[{i+1}/{len(QUERIES)}] Timeout error. Sleeping 60s and retrying...")
                    time.sleep(60)
                else:
                    results.append({"id": i + 1, "question": question, "error": str(e), "status": "FAILED"})
                    print(f"[{i+1}/{len(QUERIES)}] FAILED: {question[:50]}... - {e}")
                    break
            
    with open("test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    print(f"Completed! Results saved to test_results.json")

if __name__ == "__main__":
    run_tests()
