import requests
import json
import time

system = "33k Tools: write_file(path,content) read_file(path) list_directory\nJSON: {\"tool_calls\":[{\"function\":{\"name\":\"write_file\",\"arguments\":{\"path\":\"a.txt\",\"content\":\"hi\"}}}]} ONE per turn. Check exists first. /math for math. TEMPLATE:todo:index.html expands to full file (use for todo app)."
user = "write hello to a.txt"
tool = {
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

configs = [
    ("full system+user+tool", system, user, [tool]),
    ("system only", system, "", []),
    ("user only", "", user, []),
    ("tool only", "", "", [tool]),
    ("no tools", system, user, []),
]

for label, sys_msg, user_msg, tools in configs:
    messages = []
    if sys_msg:
        messages.append({"role": "system", "content": sys_msg})
    if user_msg:
        messages.append({"role": "user", "content": user_msg})
    
    payload = {
        "model": "qwen2.5-coder:1.5b",
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    
    start = time.time()
    r = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120)
    data = r.json()
    elapsed = time.time() - start
    
    print(f"{label}: prompt={data.get('prompt_eval_count', 'N/A')}, output={data.get('eval_count', 'N/A')}, time={elapsed:.2f}s")
