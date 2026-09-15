"""
Exact/token-sensitive and cross-file invariant benchmark tasks
"""

import os
import tempfile
from dataclasses import dataclass, field
from typing import List, Callable, Optional

from core.messages import Message

from .long_horizon import BenchmarkTask, TaskRegistry


def _tc(name, args):
    return {"function": {"name": name, "arguments": args}}


# ---------------------------------------------------------------------------
# Token-sensitive exact tasks
# ---------------------------------------------------------------------------

def setup_count_chars():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "text.txt"), "w") as f:
        f.write("hello world hello")
    return ws


def verify_count_chars(workspace):
    path = os.path.join(workspace, "counts.json")
    if not os.path.exists(path):
        return False
    import json
    with open(path) as f:
        data = json.load(f)
    return data.get("l") == 3 and data.get("o") == 2


def _count_chars_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "text.txt"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "counts.json", "content": "{\"l\": 3, \"o\": 2}"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="count_chars",
    description="Count exact character occurrences",
    horizon=6,
    setup_fn=setup_count_chars,
    execute_fn=None,
    verify_fn=verify_count_chars,
    partial_credit_fn=lambda ws: 0.8 if verify_count_chars(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "exact", "token_sensitive"],
    user_input="Count occurrences of 'l' and 'o' in text.txt and write counts.json",
    model_responses=_count_chars_responses(),
    expected_output="done",
))


def setup_validate_emails():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "users.json"), "w") as f:
        f.write('{"users": [{"email": "a@b.com"}, {"email": "bad"}]}')
    return ws


def verify_validate_emails(workspace):
    path = os.path.join(workspace, "validation.json")
    if not os.path.exists(path):
        return False
    import json
    with open(path) as f:
        data = json.load(f)
    return data.get("valid") == 1 and data.get("invalid") == 1


def _validate_emails_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "users.json"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "validation.json", "content": "{\"valid\": 1, \"invalid\": 1}"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="validate_emails",
    description="Validate email formats in JSON data",
    horizon=6,
    setup_fn=setup_validate_emails,
    execute_fn=None,
    verify_fn=verify_validate_emails,
    partial_credit_fn=lambda ws: 0.8 if verify_validate_emails(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "exact", "token_sensitive"],
    user_input="Count valid and invalid emails in users.json and write validation.json",
    model_responses=_validate_emails_responses(),
    expected_output="done",
))


def setup_normalize_paths():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "paths.txt"), "w") as f:
        f.write("C:\\Users\\test\\file.py\n../relative/path\n./current/dir/")
    return ws


def verify_normalize_paths(workspace):
    path = os.path.join(workspace, "normalized.txt")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "C:/Users/test/file.py" in content and "relative/path" in content


def _normalize_paths_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "paths.txt"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "normalized.txt", "content": "C:/Users/test/file.py\nrelative/path\ncurrent/dir\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="normalize_paths",
    description="Normalize file paths to POSIX format",
    horizon=6,
    setup_fn=setup_normalize_paths,
    execute_fn=None,
    verify_fn=verify_normalize_paths,
    partial_credit_fn=lambda ws: 0.8 if verify_normalize_paths(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "exact", "token_sensitive"],
    user_input="Normalize all paths in paths.txt to POSIX format and save to normalized.txt",
    model_responses=_normalize_paths_responses(),
    expected_output="done",
))


# ---------------------------------------------------------------------------
# Cross-file invariant tasks
# ---------------------------------------------------------------------------

def setup_cross_file_signature():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "service.py"), "w") as f:
        f.write("""def get_user(user_id):
    return {"id": user_id, "name": "unknown"}
""")
    with open(os.path.join(ws, "client.py"), "w") as f:
        f.write("""from service import get_user

def fetch():
    return get_user(1)
""")
    return ws


def verify_cross_file_signature(workspace):
    service_path = os.path.join(workspace, "service.py")
    client_path = os.path.join(workspace, "client.py")
    if not os.path.exists(service_path) or not os.path.exists(client_path):
        return False
    with open(service_path) as f:
        service = f.read()
    with open(client_path) as f:
        client = f.read()
    return "def get_user(user_id=None)" in service and "get_user()" in client


def _cross_file_signature_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "service.py"}), _tc("read_file", {"path": "client.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "service.py", "content": "def get_user(user_id=None):\n    return {\"id\": user_id, \"name\": \"unknown\"}\n"}), _tc("write_file", {"path": "client.py", "content": "from service import get_user\n\ndef fetch():\n    return get_user()\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="cross_file_signature",
    description="Update function signature and all call sites",
    horizon=10,
    setup_fn=setup_cross_file_signature,
    execute_fn=None,
    verify_fn=verify_cross_file_signature,
    partial_credit_fn=lambda ws: 0.7 if verify_cross_file_signature(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "cross_file"],
    user_input="Make user_id optional in get_user() and update client.py call site",
    model_responses=_cross_file_signature_responses(),
    expected_output="done",
))


def setup_cross_file_config():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "config.py"), "w") as f:
        f.write("DEBUG = False\nHOST = 'localhost'\n")
    with open(os.path.join(ws, "app.py"), "w") as f:
        f.write("import config\n\ndef run():\n    if config.DEBUG:\n        print('debug')\n")
    with open(os.path.join(ws, "tests.py"), "w") as f:
        f.write("import config\n\ndef test_config():\n    assert config.DEBUG == False\n")
    return ws


def verify_cross_file_config(workspace):
    config_path = os.path.join(workspace, "config.py")
    app_path = os.path.join(workspace, "app.py")
    tests_path = os.path.join(workspace, "tests.py")
    if not all(os.path.exists(p) for p in [config_path, app_path, tests_path]):
        return False
    with open(config_path) as f:
        config = f.read()
    with open(app_path) as f:
        app = f.read()
    with open(tests_path) as f:
        tests = f.read()
    return "LOG_LEVEL" in config and "config.LOG_LEVEL" in app and "LOG_LEVEL" in tests


def _cross_file_config_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "config.py"}), _tc("read_file", {"path": "app.py"}), _tc("read_file", {"path": "tests.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "config.py", "content": "DEBUG = False\nHOST = 'localhost'\nLOG_LEVEL = 'INFO'\n"}), _tc("write_file", {"path": "app.py", "content": "import config\n\ndef run():\n    if config.DEBUG:\n        print('debug')\n    print(f'Log level: {config.LOG_LEVEL}')\n"}), _tc("write_file", {"path": "tests.py", "content": "import config\n\ndef test_config():\n    assert config.DEBUG == False\n    assert config.LOG_LEVEL == 'INFO'\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="cross_file_config",
    description="Propagate new config field across all files",
    horizon=12,
    setup_fn=setup_cross_file_config,
    execute_fn=None,
    verify_fn=verify_cross_file_config,
    partial_credit_fn=lambda ws: 0.6 if verify_cross_file_config(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "cross_file"],
    user_input="Add LOG_LEVEL='INFO' to config.py and update app.py and tests.py to use it",
    model_responses=_cross_file_config_responses(),
    expected_output="done",
))


def setup_cross_file_rename():
    ws = tempfile.mkdtemp()
    os.makedirs(os.path.join(ws, "pkg"), exist_ok=True)
    with open(os.path.join(ws, "pkg", "utils.py"), "w") as f:
        f.write("""def helper(x):
    return x * 2
""")
    with open(os.path.join(ws, "pkg", "calc.py"), "w") as f:
        f.write("""from .utils import helper

def compute(x):
    return helper(x) + 1
""")
    with open(os.path.join(ws, "main.py"), "w") as f:
        f.write("""from pkg.calc import compute

print(compute(5))
""")
    return ws


def verify_cross_file_rename(workspace):
    utils_path = os.path.join(workspace, "pkg", "utils.py")
    calc_path = os.path.join(workspace, "pkg", "calc.py")
    main_path = os.path.join(workspace, "main.py")
    if not all(os.path.exists(p) for p in [utils_path, calc_path, main_path]):
        return False
    with open(utils_path) as f:
        utils = f.read()
    with open(calc_path) as f:
        calc = f.read()
    with open(main_path) as f:
        main = f.read()
    return "def double" in utils and "double" in calc and "double" in main


def _cross_file_rename_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "pkg/utils.py"}), _tc("read_file", {"path": "pkg/calc.py"}), _tc("read_file", {"path": "main.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "pkg/utils.py", "content": "def double(x):\n    return x * 2\n"}), _tc("write_file", {"path": "pkg/calc.py", "content": "from .utils import double\n\ndef compute(x):\n    return double(x) + 1\n"}), _tc("write_file", {"path": "main.py", "content": "from pkg.calc import compute\n\nprint(compute(5))\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="cross_file_rename",
    description="Rename function across multiple files",
    horizon=12,
    setup_fn=setup_cross_file_rename,
    execute_fn=None,
    verify_fn=verify_cross_file_rename,
    partial_credit_fn=lambda ws: 0.7 if verify_cross_file_rename(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "cross_file"],
    user_input="Rename helper() to double() in pkg/utils.py, pkg/calc.py, and main.py",
    model_responses=_cross_file_rename_responses(),
    expected_output="done",
))


# ---------------------------------------------------------------------------
# Lifecycle tasks (bare repo → fix/feature → validation)
# ---------------------------------------------------------------------------

def setup_lifecycle_bugfix():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "app.py"), "w") as f:
        f.write("""def add(a, b):
    return a - b
""")
    with open(os.path.join(ws, "test_app.py"), "w") as f:
        f.write("""from app import add

def test_add():
    assert add(2, 3) == 5
""")
    return ws


def verify_lifecycle_bugfix(workspace):
    app_path = os.path.join(workspace, "app.py")
    test_path = os.path.join(workspace, "test_app.py")
    if not os.path.exists(app_path) or not os.path.exists(test_path):
        return False
    with open(app_path) as f:
        app = f.read()
    return "a + b" in app


def _lifecycle_bugfix_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "test_app.py"}), _tc("read_file", {"path": "app.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "app.py", "content": "def add(a, b):\n    return a + b\n"})]),
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "test_app.py"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="lifecycle_bugfix",
    description="Read tests, fix bug, verify with tests",
    horizon=10,
    setup_fn=setup_lifecycle_bugfix,
    execute_fn=None,
    verify_fn=verify_lifecycle_bugfix,
    partial_credit_fn=lambda ws: 0.8 if verify_lifecycle_bugfix(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "lifecycle"],
    user_input="Read test_app.py, fix the bug in app.py, and ensure tests pass",
    model_responses=_lifecycle_bugfix_responses(),
    expected_output="done",
))


def setup_lifecycle_feature():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "store.py"), "w") as f:
        f.write("""class Store:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)

    def all(self):
        return list(self.items)
""")
    with open(os.path.join(ws, "test_store.py"), "w") as f:
        f.write("""from store import Store

def test_add_and_all():
    s = Store()
    s.add(1)
    assert s.all() == [1]

def test_clear():
    s = Store()
    s.add(1)
    s.clear()
    assert s.all() == []
""")
    return ws


def verify_lifecycle_feature(workspace):
    store_path = os.path.join(workspace, "store.py")
    if not os.path.exists(store_path):
        return False
    with open(store_path) as f:
        content = f.read()
    return "def clear" in content


def _lifecycle_feature_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "test_store.py"}), _tc("read_file", {"path": "store.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "store.py", "content": "class Store:\n    def __init__(self):\n        self.items = []\n\n    def add(self, item):\n        self.items.append(item)\n\n    def all(self):\n        return list(self.items)\n\n    def clear(self):\n        self.items.clear()\n"})]),
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "test_store.py"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="lifecycle_feature",
    description="Add missing method to make tests pass",
    horizon=12,
    setup_fn=setup_lifecycle_feature,
    execute_fn=None,
    verify_fn=verify_lifecycle_feature,
    partial_credit_fn=lambda ws: 0.8 if verify_lifecycle_feature(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "lifecycle"],
    user_input="Read tests and implement Store.clear() so all tests pass",
    model_responses=_lifecycle_feature_responses(),
    expected_output="done",
))
