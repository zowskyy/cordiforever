import requests
import time

# Test: compact schemas with example in prompt (no descriptions)
payload = {
    "model": "qwen2.5-coder:1.5b",
    "messages": [
        {"role": "system", "content": "Tools: write_file(path,content), read_file(path), list_directory(path). Example: {\"tool_calls\":[{\"function\":{\"name\":\"write_file\",\"arguments\":{\"path\":\"a.txt\",\"content\":\"hello\"}}}]}"},
        {"role": "user", "content": "write hello to a.txt"}
    ],
    "stream": False,
}

start = time.time()
r = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120)
data = r.json()
elapsed = time.time() - start
print(f"prompt={data.get('prompt_eval_count', 'N/A')}, output={data.get('eval_count', 'N/A')}, time={elapsed:.2f}s")
print(f"Response: {str(data.get('message', {}).get('content', ''))[:200]}")
