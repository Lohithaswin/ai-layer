import json
import httpx
import src.config as _cfg
from src.llm import OllamaTimeoutError

def generate_stream(prompt: str, system: str | None = None):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Estimate prompt tokens (roughly 4 chars per token)
    prompt_chars = len(system or "") + len(prompt)
    estimated_prompt_tokens = prompt_chars // 4
    
    # Llama 3.1 8B on Groq has an 8192 token limit.
    # We must ensure estimated_prompt_tokens + max_tokens <= 8192
    available_tokens = 8192 - estimated_prompt_tokens - 100 # 100 token safety buffer
    
    # Ensure max_tokens is at least 300 (so the model can answer), but cap at OLLAMA_NUM_PREDICT
    max_tokens = max(300, min(available_tokens, _cfg.OLLAMA_NUM_PREDICT))

    payload: dict = {
        "model": _cfg.OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": 0.2,
        "max_tokens": max_tokens,
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
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (413, 429):
            yield "\n\n[API Error: The Groq free tier limit was exceeded (too many rapid requests or payload too large). Please wait 60 seconds and try again.]"
        else:
            yield f"\n\n[API Error: {e.response.status_code} - {e.response.text}]"
    except httpx.ConnectError:
        yield "\n\n[API Error: Could not connect to the Groq API. Please check your internet connection.]"
    except httpx.ReadTimeout as e:
        raise OllamaTimeoutError(f"Groq API did not finish within {int(_cfg.OLLAMA_TIMEOUT)}s.") from e
