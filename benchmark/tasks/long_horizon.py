"""
Expanded long-horizon benchmark tasks (50-100 steps)
Stressing recovery + context folding
"""

from dataclasses import dataclass, field
from typing import List, Dict, Callable, Optional
import random
import tempfile
import os
import shutil
import time

from core.messages import Message


@dataclass
class BenchmarkTask:
    """Definition of a benchmark task"""
    name: str
    description: str
    horizon: int
    setup_fn: Callable
    execute_fn: Callable
    verify_fn: Callable
    partial_credit_fn: Optional[Callable] = None
    required_tools: List[str] = field(default_factory=list)
    stress_recovery: bool = False
    stress_context_folding: bool = False
    tags: List[str] = field(default_factory=list)
    user_input: str = ""
    model_responses: List[Message] = field(default_factory=list)
    expected_output: str = ""


class TaskRegistry:
    """Registry of all benchmark tasks"""
    _tasks: Dict[str, BenchmarkTask] = {}

    @classmethod
    def register(cls, task: BenchmarkTask):
        cls._tasks[task.name] = task

    @classmethod
    def get_all(cls) -> List[BenchmarkTask]:
        return list(cls._tasks.values())

    @classmethod
    def get_by_tag(cls, tag: str) -> List[BenchmarkTask]:
        return [t for t in cls._tasks.values() if tag in t.tags]

    @classmethod
    def get_by_name(cls, name: str) -> BenchmarkTask:
        return cls._tasks.get(name)


def _setup_workspace():
    workspace = tempfile.mkdtemp(prefix="benchmark_")
    return workspace


def _cleanup_workspace(workspace: str):
    shutil.rmtree(workspace, ignore_errors=True)


def setup_refactoring():
    ws = _setup_workspace()
    files = {
        "main.py": """from utils import helper, config
from data import load_dataset

def main():
    data = load_dataset()
    result = helper.process(data)
    config.save(result)
    return result

if __name__ == "__main__":
    main()
""",
        "utils.py": """def helper(data):
    return [x * 2 for x in data]

def config(data):
    return {"path": "/tmp/output.json"}
""",
        "data.py": """def load_dataset():
    import csv
    with open("input.csv") as f:
        return list(csv.reader(f))
""",
        "tests/test_utils.py": """def test_helper():
    assert helper([1, 2, 3]) == [2, 4, 6]
""",
        "requirements.txt": "pandas==2.0.0\nnumpy==1.24.0"
    }

    for path, content in files.items():
        full_path = os.path.join(ws, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)

    return ws


def verify_refactoring(ws):
    with open(os.path.join(ws, "main.py")) as f:
        main = f.read()
        if "def config(data):" not in main:
            return False
    return True


def partial_credit_refactoring(ws):
    score = 0.0
    files_modified = 0
    for fname in ["main.py", "utils.py", "data.py"]:
        path = os.path.join(ws, fname)
        if os.path.exists(path):
            with open(path) as f:
                if len(f.read()) > 100:
                    files_modified += 1
    return files_modified / 3.0


TaskRegistry.register(BenchmarkTask(
    name="refactoring",
    description="Refactor a multi-file Python project with dependencies",
    horizon=70,
    setup_fn=setup_refactoring,
    execute_fn=None,
    verify_fn=verify_refactoring,
    partial_credit_fn=partial_credit_refactoring,
    required_tools=["read_file", "write_file", "grep", "find"],
    stress_recovery=False,
    stress_context_folding=True,
    tags=["code", "refactoring", "long-horizon"]
))


def setup_data_pipeline():
    ws = _setup_workspace()
    os.makedirs(os.path.join(ws, "data"), exist_ok=True)
    os.makedirs(os.path.join(ws, "scripts"), exist_ok=True)
    os.makedirs(os.path.join(ws, "output"), exist_ok=True)

    with open(os.path.join(ws, "data", "input.csv"), "w") as f:
        f.write("id,name,value\n1,alice,100\n2,bob,200\n3,charlie,300\n")

    with open(os.path.join(ws, "data", "input2.csv"), "w") as f:
        f.write("id,score\n1,10\n2,20\n3,30\n")

    with open(os.path.join(ws, "scripts", "process.py"), "w") as f:
        f.write("""import csv
import json
import sys

def load_data(path):
    with open(path) as f:
        return list(csv.DictReader(f))

def join_data(data1, data2):
    result = []
    for r1 in data1:
        for r2 in data2:
            if r1['id'] == r2['id']:
                result.append({**r1, 'score': r2['score']})
    return result

def compute_stats(data):
    return sum(int(x['value']) for x in data)

if __name__ == "__main__":
    data1 = load_data(sys.argv[1])
    data2 = load_data(sys.argv[2])
    joined = join_data(data1, data2)
    stats = compute_stats(joined)
    with open("output/stats.json", "w") as f:
        json.dump({"sum": stats}, f)
""")

    return ws


def verify_data_pipeline(ws):
    output_path = os.path.join(ws, "output", "stats.json")
    if not os.path.exists(output_path):
        return False
    import json
    with open(output_path) as f:
        data = json.load(f)
        return data.get("sum") == 600


def partial_credit_data_pipeline(ws):
    score = 0.0
    if os.path.exists(os.path.join(ws, "output", "stats.json")):
        score += 0.5
    if os.path.exists(os.path.join(ws, "scripts", "process.py")):
        with open(os.path.join(ws, "scripts", "process.py")) as f:
            if "join_data" in f.read():
                score += 0.5
    return score


TaskRegistry.register(BenchmarkTask(
    name="data_pipeline",
    description="Build a multi-stage data processing pipeline",
    horizon=55,
    setup_fn=setup_data_pipeline,
    execute_fn=None,
    verify_fn=verify_data_pipeline,
    partial_credit_fn=partial_credit_data_pipeline,
    required_tools=["read_file", "write_file", "grep", "find"],
    stress_recovery=True,
    stress_context_folding=True,
    tags=["data", "pipeline", "long-horizon"]
))


def setup_web_scraper():
    ws = _setup_workspace()
    os.makedirs(os.path.join(ws, "scraper"), exist_ok=True)

    pages = {
        "index.html": """<html><body>
            <a href="/page1.html">Page 1</a>
            <a href="/page2.html">Page 2</a>
            <a href="/page3.html">Page 3</a>
            <a href="/broken.html">Broken</a>
        </body></html>""",
        "page1.html": """<html><body>
            <h1>Page 1</h1>
            <p>Content for page 1</p>
            <a href="/subpage1.html">Subpage 1</a>
        </body></html>""",
        "page2.html": """<html><body>
            <h1>Page 2</h1>
            <p>Content for page 2</p>
        </body></html>""",
        "page3.html": """<html><body>
            <h1>Page 3</h1>
            <p>Content for page 3</p>
            <a href="/subpage2.html">Subpage 2</a>
        </body></html>""",
        "broken.html": """<html><body>
            <h1>Broken Page</h1>
            <p>Missing content</p>
        </body></html>""",
        "subpage1.html": """<html><body>
            <h1>Subpage 1</h1>
            <p>Deep content</p>
        </body></html>""",
        "subpage2.html": """<html><body>
            <h1>Subpage 2</h1>
            <p>More deep content</p>
        </body></html>"""
    }

    for path, content in pages.items():
        full_path = os.path.join(ws, "scraper", path)
        with open(full_path, "w") as f:
            f.write(content)

    with open(os.path.join(ws, "scraper", "scraper.py"), "w") as f:
        f.write("""import requests
from bs4 import BeautifulSoup
import time

def fetch_page(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.text

def parse_links(html):
    soup = BeautifulSoup(html, 'html.parser')
    return [a.get('href') for a in soup.find_all('a') if a.get('href')]

def scrape_site(base_url):
    visited = set()
    to_visit = [base_url]
    results = []

    while to_visit:
        url = to_visit.pop()
        if url in visited:
            continue
        visited.add(url)
        try:
            html = fetch_page(url)
            links = parse_links(html)
            results.append({'url': url, 'links': links})
            to_visit.extend(links)
        except Exception as e:
            print(f"Error: {e}")

    return results
""")

    return ws


def verify_web_scraper(ws):
    scraper_path = os.path.join(ws, "scraper", "scraper.py")
    if not os.path.exists(scraper_path):
        return False
    with open(scraper_path) as f:
        content = f.read()
        return "retry" in content.lower() and "except" in content


def partial_credit_web_scraper(ws):
    score = 0.0
    with open(os.path.join(ws, "scraper", "scraper.py")) as f:
        content = f.read()
        if "try" in content and "except" in content:
            score += 0.5
        if "parse_links" in content and "find_all" in content:
            score += 0.5
    return score


TaskRegistry.register(BenchmarkTask(
    name="web_scraper",
    description="Build a web scraper with error recovery",
    horizon=90,
    setup_fn=setup_web_scraper,
    execute_fn=None,
    verify_fn=verify_web_scraper,
    partial_credit_fn=partial_credit_web_scraper,
    required_tools=["read_file", "write_file", "grep", "find"],
    stress_recovery=True,
    stress_context_folding=True,
    tags=["scraper", "recovery", "long-horizon"]
))


def setup_api_client():
    ws = _setup_workspace()
    os.makedirs(os.path.join(ws, "api"), exist_ok=True)

    with open(os.path.join(ws, "api", "client.py"), "w") as f:
        f.write("""import requests
import time
import json

class APIClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def get_data(self, endpoint):
        response = requests.get(f"{self.base_url}/{endpoint}")
        return response.json()

    def post_data(self, endpoint, data):
        response = requests.post(f"{self.base_url}/{endpoint}", json=data)
        return response.status_code

def process_all_endpoints(client, endpoints):
    results = {}
    for endpoint in endpoints:
        try:
            data = client.get_data(endpoint)
            results[endpoint] = data
        except Exception as e:
            print(f"Failed: {endpoint}")
    return results
""")

    return ws


def verify_api_client(ws):
    path = os.path.join(ws, "api", "client.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
        return "time.sleep" in content and "retry" in content.lower()


def partial_credit_api_client(ws):
    score = 0.0
    with open(os.path.join(ws, "api", "client.py")) as f:
        content = f.read()
        if "time.sleep" in content or "rate" in content.lower():
            score += 0.5
        if "except" in content and "retry" in content.lower():
            score += 0.5
    return score


TaskRegistry.register(BenchmarkTask(
    name="api_client",
    description="Build an API client with rate limiting and retry logic",
    horizon=70,
    setup_fn=setup_api_client,
    execute_fn=None,
    verify_fn=verify_api_client,
    partial_credit_fn=partial_credit_api_client,
    required_tools=["read_file", "write_file", "grep"],
    stress_recovery=True,
    stress_context_folding=False,
    tags=["api", "recovery", "long-horizon"]
))


def setup_db_migration():
    ws = _setup_workspace()
    os.makedirs(os.path.join(ws, "migrations"), exist_ok=True)

    with open(os.path.join(ws, "migrations", "001_initial.sql"), "w") as f:
        f.write("""CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT
);

CREATE TABLE posts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    title TEXT,
    content TEXT
);
""")

    with open(os.path.join(ws, "migrations", "002_add_created_at.sql"), "w") as f:
        f.write("""ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE posts ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP;
""")

    with open(os.path.join(ws, "migrations", "migrate.py"), "w") as f:
        f.write("""import sqlite3
import glob
import re

def get_current_version(conn):
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)")
    cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
    row = cursor.fetchone()
    return row[0] if row else 0

def run_migrations(conn, target_version):
    current = get_current_version(conn)
    migrations = sorted(glob.glob("migrations/*.sql"))
    for path in migrations:
        version = int(re.search(r'(\\d+)', path).group(1))
        if version > current and version <= target_version:
            with open(path) as f:
                conn.executescript(f.read())
            cursor = conn.cursor()
            cursor.execute("INSERT INTO schema_version VALUES (?)", (version,))
            conn.commit()
""")

    return ws


def verify_db_migration(ws):
    path = os.path.join(ws, "migrations", "migrate.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
        return "version" in content and "INSERT INTO schema_version" in content


def partial_credit_db_migration(ws):
    score = 0.0
    with open(os.path.join(ws, "migrations", "migrate.py")) as f:
        content = f.read()
        if "schema_version" in content:
            score += 0.5
        if "executescript" in content:
            score += 0.5
    return score


TaskRegistry.register(BenchmarkTask(
    name="db_migration",
    description="Build a database migration script with version tracking",
    horizon=60,
    setup_fn=setup_db_migration,
    execute_fn=None,
    verify_fn=verify_db_migration,
    partial_credit_fn=partial_credit_db_migration,
    required_tools=["read_file", "write_file", "grep"],
    stress_recovery=False,
    stress_context_folding=True,
    tags=["database", "migration", "long-horizon"]
))


def setup_cicd_pipeline():
    ws = _setup_workspace()
    os.makedirs(os.path.join(ws, ".github", "workflows"), exist_ok=True)

    with open(os.path.join(ws, ".github", "workflows", "old.yml"), "w") as f:
        f.write("""name: Old CI

on: [push]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run tests
        run: pytest
      - name: Deploy
        run: deploy.sh
""")

    with open(os.path.join(ws, "deploy.sh"), "w") as f:
        f.write("""#!/bin/bash
echo "Deploying to staging..."
""")

    with open(os.path.join(ws, "build.py"), "w") as f:
        f.write("""#!/usr/bin/env python
import subprocess
import sys

def build():
    subprocess.run(["python", "setup.py", "build"])
    subprocess.run(["python", "-m", "pytest", "tests/"])
    return True

if __name__ == "__main__":
    build()
""")

    return ws


def verify_cicd_pipeline(ws):
    path = os.path.join(ws, ".github", "workflows", "old.yml")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
        return "test" in content and "build" in content


def partial_credit_cicd_pipeline(ws):
    score = 0.0
    with open(os.path.join(ws, ".github", "workflows", "old.yml")) as f:
        content = f.read()
        if "test" in content:
            score += 0.4
        if "build" in content:
            score += 0.3
        if "deploy" in content:
            score += 0.3
    return score


TaskRegistry.register(BenchmarkTask(
    name="cicd_pipeline",
    description="Generate a CI/CD pipeline with multiple stages",
    horizon=80,
    setup_fn=setup_cicd_pipeline,
    execute_fn=None,
    verify_fn=verify_cicd_pipeline,
    partial_credit_fn=partial_credit_cicd_pipeline,
    required_tools=["read_file", "write_file", "grep"],
    stress_recovery=False,
    stress_context_folding=True,
    tags=["cicd", "pipeline", "long-horizon"]
))


def setup_multi_tool():
    ws = _setup_workspace()
    os.makedirs(os.path.join(ws, "tools"), exist_ok=True)

    with open(os.path.join(ws, "tools", "extract.py"), "w") as f:
        f.write("""def extract_data():
    return {"names": ["alice", "bob", "charlie"], "values": [10, 20, 30]}
""")

    with open(os.path.join(ws, "tools", "transform.py"), "w") as f:
        f.write("""def transform_data(data):
    return [x * 2 for x in data]
""")

    with open(os.path.join(ws, "tools", "load.py"), "w") as f:
        f.write("""def load_data(data):
    for item in data:
        print(item)
""")

    with open(os.path.join(ws, "workflow.py"), "w") as f:
        f.write("""from tools import extract, transform, load

def run_workflow():
    data = extract.extract_data()
    transformed = transform.transform_data(data['values'])
    load.load_data(transformed)
    return transformed

if __name__ == "__main__":
    result = run_workflow()
    print(f"Result: {result}")
""")

    return ws


def verify_multi_tool(ws):
    path = os.path.join(ws, "workflow.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
        return "extract" in content and "transform" in content and "load" in content


def partial_credit_multi_tool(ws):
    score = 0.0
    with open(os.path.join(ws, "workflow.py")) as f:
        content = f.read()
        if "extract" in content:
            score += 0.33
        if "transform" in content:
            score += 0.33
        if "load" in content:
            score += 0.34
    return score


TaskRegistry.register(BenchmarkTask(
    name="multi_tool",
    description="Orchestrate multiple tools in a workflow",
    horizon=60,
    setup_fn=setup_multi_tool,
    execute_fn=None,
    verify_fn=verify_multi_tool,
    partial_credit_fn=partial_credit_multi_tool,
    required_tools=["read_file", "write_file", "grep"],
    stress_recovery=True,
    stress_context_folding=True,
    tags=["orchestration", "workflow", "long-horizon"]
))


def setup_config_manager():
    ws = _setup_workspace()

    configs = {
        "config/dev.json": '{"env": "dev", "debug": true, "host": "localhost", "port": 8080}',
        "config/staging.json": '{"env": "staging", "debug": false, "host": "staging.example.com", "port": 8080}',
        "config/prod.json": '{"env": "prod", "debug": false, "host": "example.com", "port": 80}',
        "config/base.json": '{"timeout": 30, "retries": 3, "cache": true}'
    }

    for path, content in configs.items():
        full_path = os.path.join(ws, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)

    with open(os.path.join(ws, "config_manager.py"), "w") as f:
        f.write("""import json
import os

def load_config(env):
    base_path = f"config/{env}.json"
    if not os.path.exists(base_path):
        raise ValueError(f"Config not found: {env}")
    with open(base_path) as f:
        config = json.load(f)
    return config

def merge_configs(base, override):
    result = {**base, **override}
    return result
""")

    return ws


def verify_config_manager(ws):
    path = os.path.join(ws, "config_manager.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
        return "load_config" in content and "env" in content


def partial_credit_config_manager(ws):
    score = 0.0
    with open(os.path.join(ws, "config_manager.py")) as f:
        content = f.read()
        if "load_config" in content:
            score += 0.5
        if "merge_configs" in content:
            score += 0.5
    return score


TaskRegistry.register(BenchmarkTask(
    name="config_manager",
    description="Build a configuration manager for multiple environments",
    horizon=55,
    setup_fn=setup_config_manager,
    execute_fn=None,
    verify_fn=verify_config_manager,
    partial_credit_fn=partial_credit_config_manager,
    required_tools=["read_file", "write_file", "grep"],
    stress_recovery=False,
    stress_context_folding=True,
    tags=["config", "management", "long-horizon"]
))


def setup_log_parser():
    ws = _setup_workspace()
    os.makedirs(os.path.join(ws, "logs"), exist_ok=True)

    log_files = {
        "logs/app.log": """2024-01-01 10:00:00 INFO Application started
2024-01-01 10:01:00 INFO User login: alice
2024-01-01 10:02:00 ERROR Database connection failed
2024-01-01 10:03:00 WARN Retry attempt 1
2024-01-01 10:04:00 INFO User login: bob
2024-01-01 10:05:00 ERROR Timeout in api call
2024-01-01 10:06:00 INFO User logout: alice
""",
        "logs/web.log": """2024-01-01 10:00:10 GET / 200
2024-01-01 10:01:10 GET /login 200
2024-01-01 10:02:10 POST /login 500
2024-01-01 10:03:10 GET /dashboard 200
2024-01-01 10:04:10 POST /logout 200
""",
        "logs/error.log": """2024-01-01 10:02:00 DB_ERROR: connection refused
2024-01-01 10:05:00 TIMEOUT: api call took >5s
2024-01-01 10:07:00 DB_ERROR: connection pool exhausted
"""
    }

    for path, content in log_files.items():
        full_path = os.path.join(ws, path)
        with open(full_path, "w") as f:
            f.write(content)

    with open(os.path.join(ws, "log_parser.py"), "w") as f:
        f.write("""import re
from collections import defaultdict

def parse_logs(log_paths):
    stats = defaultdict(int)
    for path in log_paths:
        with open(path) as f:
            for line in f:
                if 'ERROR' in line:
                    stats['errors'] += 1
                elif 'WARN' in line:
                    stats['warnings'] += 1
                elif 'INFO' in line:
                    stats['info'] += 1
    return stats
""")

    return ws


def verify_log_parser(ws):
    path = os.path.join(ws, "log_parser.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
        return "ERROR" in content and "WARN" in content and "INFO" in content


def partial_credit_log_parser(ws):
    score = 0.0
    with open(os.path.join(ws, "log_parser.py")) as f:
        content = f.read()
        if "ERROR" in content and "WARN" in content and "INFO" in content:
            score += 0.5
        if "aggregate" in content or "stats" in content:
            score += 0.5
    return score


TaskRegistry.register(BenchmarkTask(
    name="log_parser",
    description="Build a log parser with aggregation",
    horizon=60,
    setup_fn=setup_log_parser,
    execute_fn=None,
    verify_fn=verify_log_parser,
    partial_credit_fn=partial_credit_log_parser,
    required_tools=["read_file", "write_file", "grep"],
    stress_recovery=False,
    stress_context_folding=True,
    tags=["logging", "parsing", "long-horizon"]
))


def setup_fs_operations():
    ws = _setup_workspace()

    dirs = [
        "src/module1",
        "src/module2",
        "src/module3",
        "src/tests",
        "docs",
        "scripts",
        "config"
    ]

    for d in dirs:
        os.makedirs(os.path.join(ws, d), exist_ok=True)

    files = {
        "src/module1/core.py": "def core(): return 'core'",
        "src/module1/utils.py": "def util(): return 'util'",
        "src/module2/processor.py": "def process(): return 'processed'",
        "src/module2/helpers.py": "def help(): return 'help'",
        "src/module3/api.py": "def api(): return 'api'",
        "src/tests/test_core.py": "def test_core(): assert core() == 'core'",
        "docs/README.md": "# Project\n\nDocumentation",
        "scripts/build.sh": "#!/bin/bash\necho 'Building'",
        "config/settings.json": '{"debug": true}'
    }

    for path, content in files.items():
        full_path = os.path.join(ws, path)
        with open(full_path, "w") as f:
            f.write(content)

    with open(os.path.join(ws, "fs_ops.py"), "w") as f:
        f.write("""import os
import shutil

def organize_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        for filename in filenames:
            if filename.endswith('.py'):
                print(f"Found Python file: {filename}")
""")

    return ws


def verify_fs_operations(ws):
    path = os.path.join(ws, "fs_ops.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
        return "os.walk" in content and ".py" in content


def partial_credit_fs_operations(ws):
    score = 0.0
    with open(os.path.join(ws, "fs_ops.py")) as f:
        content = f.read()
        if "os.walk" in content:
            score += 0.5
        if "shutil" in content or "move" in content:
            score += 0.5
    return score


TaskRegistry.register(BenchmarkTask(
    name="fs_operations",
    description="Build file system operations with organization",
    horizon=80,
    setup_fn=setup_fs_operations,
    execute_fn=None,
    verify_fn=verify_fs_operations,
    partial_credit_fn=partial_credit_fs_operations,
    required_tools=["read_file", "write_file", "grep", "find"],
    stress_recovery=True,
    stress_context_folding=True,
    tags=["filesystem", "organization", "long-horizon"]
))


def get_all_tasks() -> List[BenchmarkTask]:
    return TaskRegistry.get_all()


def get_tasks_by_tag(tag: str) -> List[BenchmarkTask]:
    return TaskRegistry.get_by_tag(tag)


def get_stress_tasks() -> List[BenchmarkTask]:
    return [t for t in get_all_tasks() if t.stress_recovery or t.stress_context_folding]
