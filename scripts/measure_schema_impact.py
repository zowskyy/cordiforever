import requests
import time

# Test 1: Current lite prompt with full schemas
payload1 = {
    "model": "qwen2.5-coder:1.5b",
    "messages": [
        {"role": "system", "content": "33k Tools: write_file(path,content) read_file(path) list_directory\nJSON: {\"tool_calls\":[{\"function\":{\"name\":\"write_file\",\"arguments\":{\"path\":\"a.txt\",\"content\":\"hi\"}}}]} ONE per turn."},
        {"role": "user", "content": "write hello to a.txt"}
    ],
    "stream": False,
    "tools": [
        {"type": "function", "function": {"name": "write_file", "description": "Write content to a UTF-8 text file in the workspace.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
        {"type": "function", "function": {"name": "read_file", "description": "Read a UTF-8 text file from the workspace.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": "list_directory", "description": "List files in the workspace directory.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}}},
    ]
}

# Test 2: Ultra-compact - no schemas, just names
payload2 = {
    "model": "qwen2.5-coder:1.5b",
    "messages": [
        {"role": "system", "content": "Tools: write_file(path,content), read_file(path), list_directory(path). Call exactly one tool per response."},
        {"role": "user", "content": "write hello to a.txt"}
    ],
    "stream": False,
}

# Test 3: No tools at all, just prompt engineering
payload3 = {
    "model": "qwen2.5-coder:1.5b",
    "messages": [
        {"role": "system", "content": "You have access to write_file(path,content), read_file(path), list_directory(path). Respond with only: {\"tool_calls\":[{\"function\":{\"name\":\"write_file\",\"arguments\":{\"path\":\"a.txt\",\"content\":\"hello\"}}}]}"},
        {"role": "user", "content": "write hello to a.txt"}
    ],
    "stream": False,
}

for i, payload in enumerate([payload1, payload2, payload3], 1):
    start = time.time()
    r = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120)
    data = r.json()
    elapsed = time.time() - start
    print(f"Payload {i}: prompt={data.get('prompt_eval_count', 'N/A')}, output={data.get('eval_count', 'N/A')}, time={elapsed:.2f}s")
    print(f"  Response: {str(data.get('message', {}).get('content', ''))[:120]}")
