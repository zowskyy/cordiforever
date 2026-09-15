import requests
import time

# Compact but valid schemas - just name + required params, no descriptions
compact_tools = [
    {"type": "function", "function": {"name": "write_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "list_directory", "parameters": {"type": "object", "properties": {}, "required": []}}},
]

payloads = [
    ("current lite", {
        "model": "qwen2.5-coder:1.5b",
        "messages": [
            {"role": "system", "content": '33k Tools: write_file(path,content) read_file(path) list_directory\nJSON: {"tool_calls":[{"function":{"name":"write_file","arguments":{"path":"a.txt","content":"hi"}}}]} ONE per turn. Check exists first. /math for math. TEMPLATE:todo:index.html expands to full file (use for todo app).'},
            {"role": "user", "content": "write hello to a.txt"}
        ],
        "stream": False,
        "tools": compact_tools,
    }),
    ("ultra compact schemas", {
        "model": "qwen2.5-coder:1.5b",
        "messages": [
            {"role": "system", "content": "Tools: write_file, read_file, list_directory. Call one tool: {\"tool_calls\":[{\"function\":{\"name\":\"write_file\",\"arguments\":{\"path\":\"a.txt\",\"content\":\"hi\"}}}]}"},
            {"role": "user", "content": "write hello to a.txt"}
        ],
        "stream": False,
        "tools": compact_tools,
    }),
]

for label, payload in payloads:
    start = time.time()
    r = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120)
    data = r.json()
    elapsed = time.time() - start
    content = str(data.get("message", {}).get("content", ""))[:150]
    print(f"{label}: prompt={data.get('prompt_eval_count', 'N/A')}, output={data.get('eval_count', 'N/A')}, time={elapsed:.2f}s")
    print(f"  Response: {content}")
    print()
