import json
import httpx
import src.config as _cfg
from src.llm import OllamaTimeoutError

def generate_stream(prompt: str, system: str | None = None):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {
        "model": _cfg.OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": 0.2,
        "max_tokens": _cfg.OLLAMA_NUM_PREDICT,
    }

    timeout = httpx.Timeout(_cfg.OLLAMA_TIMEOUT, connect=30.0)
    try:
        with httpx.Client(timeout=timeout, verify=False, headers={"Authorization": f"Bearer {_cfg.GROQ_API_KEY}"}) as client:
            with client.stream("POST", "https://api.groq.com/openai/v1/chat/completions", json=payload) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            yield content
    except httpx.ReadTimeout as e:
        raise OllamaTimeoutError(f"Groq API did not finish within {int(_cfg.OLLAMA_TIMEOUT)}s.") from e
