"""Interactive terminal chat."""

from __future__ import annotations

from src.rag import ask


def main() -> None:
    print("Local PDF chatbot (open source). Type 'quit' to exit.\n")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not question:
            continue
        if question.lower() in {"quit", "exit", "q"}:
            print("Bye.")
            break

        response = ask(question, append_footer=True)
        print(f"\nAssistant:\n{response.answer}\n")


if __name__ == "__main__":
    main()
