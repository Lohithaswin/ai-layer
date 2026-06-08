import json
import httpx
from src.config import OLLAMA_MODEL, OLLAMA_NUM_PREDICT, OLLAMA_TIMEOUT, OLLAMA_BASE_URL
from src.llm import OllamaTimeoutError

def generate_stream(prompt: str, system: str | None = None):
    payload: dict = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.2,
            "num_predict": OLLAMA_NUM_PREDICT,
            "num_ctx": 4096,
        },
    }
    if system:
        payload["system"] = system

    timeout = httpx.Timeout(OLLAMA_TIMEOUT, connect=30.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", f"{OLLAMA_BASE_URL}/api/generate", json=payload) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        yield chunk.get("response", "")
    except httpx.ReadTimeout as e:
        raise OllamaTimeoutError(f"Ollama did not finish within {int(OLLAMA_TIMEOUT)}s.") from e
