import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.query_context import resolve_question

def main():
    history = [
        {"role": "user", "content": "explain the role att Activate profile, which roles have it and what can it do?"},
        {"role": "assistant", "content": "The role attribute \"Activate Profile\" allows users to activate (configure) Profiles in the PROJECT_NAME - Configuration Management application..."},
    ]
    question = "explain the role att commission"
    
    print("Resolving question with history...")
    search_q, subjects = resolve_question(question, history)
    print(f"Rewritten Search Question: {search_q}")
    print(f"Subjects: {subjects}")

if __name__ == "__main__":
    main()
