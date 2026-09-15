import requests
import json
import time

payload = {
    "model": "qwen2.5-coder:1.5b",
    "messages": [
        {
            "role": "system",
            "content": "33k Tools: write_file(path,content) read_file(path) list_directory\nJSON: {\"tool_calls\":[{\"function\":{\"name\":\"write_file\",\"arguments\":{\"path\":\"a.txt\",\"content\":\"hi\"}}}]} ONE per turn."
        },
        {
            "role": "user",
            "content": "write hello to a.txt"
        }
    ],
    "stream": False,
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a UTF-8 text file in the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["path", "content"]
                }
            }
        }
    ]
}

start = time.time()
r = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120)
data = r.json()
elapsed = time.time() - start

print("=== Real Token Costs for Simple Task ===")
print(f"prompt_eval_count: {data.get('prompt_eval_count', 'N/A')}")
print(f"eval_count: {data.get('eval_count', 'N/A')}")
print(f"total_duration_ns: {data.get('total_duration', 'N/A')}")
print(f"elapsed_seconds: {elapsed:.2f}")
print(f"message: {str(data.get('message', {}).get('content', ''))[:200]}")
