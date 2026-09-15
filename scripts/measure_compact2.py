import requests
import time

# Minimal schemas + strong system prompt enforcing tool-only output
payload = {
    "model": "qwen2.5-coder:1.5b",
    "messages": [
        {"role": "system", "content": "You are a tool router. Call EXACTLY ONE tool. Output ONLY JSON tool_calls, nothing else."},
        {"role": "user", "content": "write hello to a.txt"}
    ],
    "stream": False,
    "tools": [
        {"type": "function", "function": {"name": "write_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    ],
}

start = time.time()
r = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120)
data = r.json()
elapsed = time.time() - start
print(f"prompt={data.get('prompt_eval_count', 'N/A')}, output={data.get('eval_count', 'N/A')}, time={elapsed:.2f}s")
print(f"Response: {str(data.get('message', {}).get('content', ''))[:200]}")
