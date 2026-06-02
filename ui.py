"""Simple Gradio web UI."""

import gradio as gr

from src.rag import ask
from src.vector_store import get_vector_store

# Load embedding model once at startup (not on every message)
get_vector_store()


def chat_fn(message: str, history: list) -> str:
    if not message.strip():
        return ""
    return ask(message, append_footer=True).answer


demo = gr.ChatInterface(
    fn=chat_fn,
    title="Local PDF Chatbot",
    description=(
        "Ask questions about PDFs in the `docs/` folder. "
        "Answers cite source file and page. "
        "Run `python -m src.ingest` after adding or changing PDFs."
    ),
    examples=[
        "What is the deployment process?",
        "Summarize the API authentication section.",
        "Which components are listed in the architecture doc?",
    ],
)

if __name__ == "__main__":
    demo.launch()
