import requests
import time

# Minimal schema format: just name + required params (no descriptions)
minimal_tools = [
    {"type": "function", "function": {"name": "write_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "list_directory", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}}},
]

payloads = [
    ("full schemas", {
        "model": "qwen2.5-coder:1.5b",
        "messages": [
            {"role": "system", "content": "33k Tools: write_file(path,content) read_file(path) list_directory\nJSON: {\"tool_calls\":[{\"function\":{\"name\":\"write_file\",\"arguments\":{\"path\":\"a.txt\",\"content\":\"hi\"}}}]} ONE per turn."},
            {"role": "user", "content": "write hello to a.txt"}
        ],
        "stream": False,
        "tools": minimal_tools,
    }),
    ("minimal schemas", {
        "model": "qwen2.5-coder:1.5b",
        "messages": [
            {"role": "system", "content": "Use tools: write_file, read_file, list_directory. Call one tool per response in JSON format."},
            {"role": "user", "content": "write hello to a.txt"}
        ],
        "stream": False,
        "tools": minimal_tools,
    }),
    ("no schemas, example in prompt", {
        "model": "qwen2.5-coder:1.5b",
        "messages": [
            {"role": "system", "content": "Call tools: write_file(path,content), read_file(path), list_directory(path). Respond ONLY with JSON tool_calls."},
            {"role": "user", "content": "write hello to a.txt"}
        ],
        "stream": False,
    }),
]

for label, payload in payloads:
    start = time.time()
    r = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120)
    data = r.json()
    elapsed = time.time() - start
    content = str(data.get("message", {}).get("content", ""))[:120]
    print(f"{label}: prompt={data.get('prompt_eval_count', 'N/A')}, output={data.get('eval_count', 'N/A')}, time={elapsed:.2f}s")
    print(f"  Response: {content}")
    print()
