"""
SWE-bench / IDE-Bench style integration tasks
Realistic software engineering tasks that test multi-step reasoning,
file editing, and debugging without requiring Docker.
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
# Bug fix tasks (SWE-bench style)
# ---------------------------------------------------------------------------

def setup_bugfix_off_by_one():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "utils.py"), "w") as f:
        f.write("""def get_last(items):
    return items[len(items)]

def safe_get_last(items):
    if len(items) > 0:
        return items[len(items)]
    return None
""")
    return ws


def verify_bugfix_off_by_one(workspace):
    path = os.path.join(workspace, "utils.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "items[len(items) - 1]" in content and "return None" in content


def _bugfix_off_by_one_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "utils.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "utils.py", "content": "def get_last(items):\n    return items[len(items) - 1]\n\ndef safe_get_last(items):\n    if len(items) > 0:\n        return items[len(items) - 1]\n    return None\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="bugfix_off_by_one",
    description="Fix off-by-one error in list indexing",
    horizon=5,
    setup_fn=setup_bugfix_off_by_one,
    execute_fn=None,
    verify_fn=verify_bugfix_off_by_one,
    partial_credit_fn=lambda ws: 0.7 if verify_bugfix_off_by_one(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "swebench", "bugfix"],
    user_input="Fix the off-by-one error in utils.py",
    model_responses=_bugfix_off_by_one_responses(),
    expected_output="done",
))


def setup_bugfix_missing_import():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "math_utils.py"), "w") as f:
        f.write("""def sqrt(x):
    return math.sqrt(x)

def factorial(n):
    return math.prod(range(1, n + 1))
""")
    return ws


def verify_bugfix_missing_import(workspace):
    path = os.path.join(workspace, "math_utils.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "import math" in content


def _bugfix_missing_import_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "math_utils.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "math_utils.py", "content": "import math\n\ndef sqrt(x):\n    return math.sqrt(x)\n\ndef factorial(n):\n    return math.prod(range(1, n + 1))\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="bugfix_missing_import",
    description="Add missing import statement",
    horizon=5,
    setup_fn=setup_bugfix_missing_import,
    execute_fn=None,
    verify_fn=verify_bugfix_missing_import,
    partial_credit_fn=lambda ws: 0.7 if verify_bugfix_missing_import(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "swebench", "bugfix"],
    user_input="Fix the NameError in math_utils.py by adding the missing import",
    model_responses=_bugfix_missing_import_responses(),
    expected_output="done",
))


def setup_bugfix_logic_error():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "filter.py"), "w") as f:
        f.write("""def filter_positive(numbers):
    return [n for n in numbers if n < 0]
""")
    return ws


def verify_bugfix_logic_error(workspace):
    path = os.path.join(workspace, "filter.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "n > 0" in content


def _bugfix_logic_error_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "filter.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "filter.py", "content": "def filter_positive(numbers):\n    return [n for n in numbers if n > 0]\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="bugfix_logic_error",
    description="Fix inverted logic in filter function",
    horizon=5,
    setup_fn=setup_bugfix_logic_error,
    execute_fn=None,
    verify_fn=verify_bugfix_logic_error,
    partial_credit_fn=lambda ws: 0.7 if verify_bugfix_logic_error(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "swebench", "bugfix"],
    user_input="filter_positive should keep positive numbers, fix the logic bug",
    model_responses=_bugfix_logic_error_responses(),
    expected_output="done",
))


# ---------------------------------------------------------------------------
# Multi-file refactoring (IDE-Bench style)
# ---------------------------------------------------------------------------

def setup_refactor_extract_method():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "processor.py"), "w") as f:
        f.write("""def process_user(user):
    name = user['name'].strip().title()
    email = user['email'].strip().lower()
    age = int(user['age'])
    return {'name': name, 'email': email, 'age': age}

def process_admin(admin):
    name = admin['name'].strip().title()
    email = admin['email'].strip().lower()
    age = int(admin['age'])
    return {'name': name, 'email': email, 'age': age}
""")
    return ws


def verify_refactor_extract_method(workspace):
    path = os.path.join(workspace, "processor.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "def normalize_user" in content and "process_user" in content and "process_admin" in content


def _refactor_extract_method_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "processor.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "processor.py", "content": "def normalize_user(user):\n    name = user['name'].strip().title()\n    email = user['email'].strip().lower()\n    age = int(user['age'])\n    return {'name': name, 'email': email, 'age': age}\n\ndef process_user(user):\n    return normalize_user(user)\n\ndef process_admin(admin):\n    return normalize_user(admin)\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="refactor_extract_method",
    description="Extract duplicated code into a helper function",
    horizon=7,
    setup_fn=setup_refactor_extract_method,
    execute_fn=None,
    verify_fn=verify_refactor_extract_method,
    partial_credit_fn=lambda ws: 0.8 if verify_refactor_extract_method(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "refactor"],
    user_input="Refactor processor.py to extract the duplicated normalization code into a normalize_user helper",
    model_responses=_refactor_extract_method_responses(),
    expected_output="done",
))


def setup_refactor_rename_symbol():
    ws = tempfile.mkdtemp()
    os.makedirs(os.path.join(ws, "pkg"), exist_ok=True)
    with open(os.path.join(ws, "pkg", "calc.py"), "w") as f:
        f.write("""def add(a, b):
    return a + b

def multiply(a, b):
    return add(a, b) * 2
""")
    with open(os.path.join(ws, "main.py"), "w") as f:
        f.write("""from pkg.calc import add

result = add(2, 3)
""")
    return ws


def verify_refactor_rename_symbol(workspace):
    calc_path = os.path.join(workspace, "pkg", "calc.py")
    main_path = os.path.join(workspace, "main.py")
    if not os.path.exists(calc_path) or not os.path.exists(main_path):
        return False
    with open(calc_path) as f:
        calc = f.read()
    with open(main_path) as f:
        main = f.read()
    return "def compute_sum" in calc and "compute_sum" in main


def _refactor_rename_symbol_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "pkg/calc.py"}), _tc("read_file", {"path": "main.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "pkg/calc.py", "content": "def compute_sum(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return compute_sum(a, b) * 2\n"}), _tc("write_file", {"path": "main.py", "content": "from pkg.calc import compute_sum\n\nresult = compute_sum(2, 3)\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="refactor_rename_symbol",
    description="Rename function across multiple files",
    horizon=8,
    setup_fn=setup_refactor_rename_symbol,
    execute_fn=None,
    verify_fn=verify_refactor_rename_symbol,
    partial_credit_fn=lambda ws: 0.7 if verify_refactor_rename_symbol(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "refactor"],
    user_input="Rename add() to compute_sum() in pkg/calc.py and update main.py import",
    model_responses=_refactor_rename_symbol_responses(),
    expected_output="done",
))


# ---------------------------------------------------------------------------
# Test-driven editing (IDE-Bench style)
# ---------------------------------------------------------------------------

def setup_test_driven_fix():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "string_utils.py"), "w") as f:
        f.write("""def truncate(s, length):
    return s[:length]
""")
    with open(os.path.join(ws, "test_string_utils.py"), "w") as f:
        f.write("""from string_utils import truncate

def test_truncate_short():
    assert truncate("hello", 10) == "hello"

def test_truncate_long():
    assert truncate("hello world", 5) == "hello"

def test_truncate_exact():
    assert truncate("hello", 5) == "hello"
""")
    return ws


def verify_test_driven_fix(workspace):
    path = os.path.join(workspace, "string_utils.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "..." in content and "length" in content


def _test_driven_fix_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "test_string_utils.py"}), _tc("read_file", {"path": "string_utils.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "string_utils.py", "content": "def truncate(s, length):\n    if len(s) <= length:\n        return s\n    return s[:length] + \"...\"\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="test_driven_fix",
    description="Make failing tests pass by implementing missing behavior",
    horizon=8,
    setup_fn=setup_test_driven_fix,
    execute_fn=None,
    verify_fn=verify_test_driven_fix,
    partial_credit_fn=lambda ws: 0.7 if verify_test_driven_fix(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "test_driven"],
    user_input="Read the tests and implement truncate() so all tests pass",
    model_responses=_test_driven_fix_responses(),
    expected_output="done",
))


# ---------------------------------------------------------------------------
# Feature addition (IDE-Bench style)
# ---------------------------------------------------------------------------

def setup_feature_add_default():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "config.py"), "w") as f:
        f.write("""settings = {
    "debug": False,
    "host": "localhost",
    "port": 8080,
}
""")
    return ws


def verify_feature_add_default(workspace):
    path = os.path.join(workspace, "config.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return '"log_level"' in content and '"INFO"' in content


def _feature_add_default_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "config.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "config.py", "content": "settings = {\n    \"debug\": False,\n    \"host\": \"localhost\",\n    \"port\": 8080,\n    \"log_level\": \"INFO\",\n}\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="feature_add_default",
    description="Add new config key with default value",
    horizon=5,
    setup_fn=setup_feature_add_default,
    execute_fn=None,
    verify_fn=verify_feature_add_default,
    partial_credit_fn=lambda ws: 0.7 if verify_feature_add_default(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "feature"],
    user_input="Add a log_level key to config.py with default value INFO",
    model_responses=_feature_add_default_responses(),
    expected_output="done",
))


def setup_feature_add_validation():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "user.py"), "w") as f:
        f.write("""class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
""")
    return ws


def verify_feature_add_validation(workspace):
    path = os.path.join(workspace, "user.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "ValueError" in content and "@" in content


def _feature_add_validation_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "user.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "user.py", "content": "class User:\n    def __init__(self, name, email):\n        if not name or not isinstance(name, str):\n            raise ValueError(\"name must be a non-empty string\")\n        if \"@\" not in email:\n            raise ValueError(\"email must contain @\")\n        self.name = name\n        self.email = email\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="feature_add_validation",
    description="Add input validation to constructor",
    horizon=6,
    setup_fn=setup_feature_add_validation,
    execute_fn=None,
    verify_fn=verify_feature_add_validation,
    partial_credit_fn=lambda ws: 0.7 if verify_feature_add_validation(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "feature"],
    user_input="Add email and name validation to User.__init__ that raises ValueError",
    model_responses=_feature_add_validation_responses(),
    expected_output="done",
))


# ---------------------------------------------------------------------------
# Multi-file debugging (IDE-Bench style)
# ---------------------------------------------------------------------------

def setup_debug_import_error():
    ws = tempfile.mkdtemp()
    os.makedirs(os.path.join(ws, "pkg"), exist_ok=True)
    with open(os.path.join(ws, "pkg", "__init__.py"), "w") as f:
        f.write("")
    with open(os.path.join(ws, "pkg", "utils.py"), "w") as f:
        f.write("""def helper():
    return "help"
""")
    with open(os.path.join(ws, "main.py"), "w") as f:
        f.write("""import utils

result = utils.helper()
""")
    return ws


def verify_debug_import_error(workspace):
    main_path = os.path.join(workspace, "main.py")
    if not os.path.exists(main_path):
        return False
    with open(main_path) as f:
        content = f.read()
    return "from pkg import utils" in content


def _debug_import_error_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "main.py"}), _tc("list_directory", {"path": "."})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "main.py", "content": "from pkg import utils\n\nresult = utils.helper()\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="debug_import_error",
    description="Fix broken import path",
    horizon=7,
    setup_fn=setup_debug_import_error,
    execute_fn=None,
    verify_fn=verify_debug_import_error,
    partial_credit_fn=lambda ws: 0.7 if verify_debug_import_error(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "debug"],
    user_input="Fix the import error in main.py",
    model_responses=_debug_import_error_responses(),
    expected_output="done",
))


def setup_debug_wrong_output():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "calc.py"), "w") as f:
        f.write("""def average(numbers):
    return sum(numbers) / len(numbers)
""")
    with open(os.path.join(ws, "test_calc.py"), "w") as f:
        f.write("""from calc import average

def test_average():
    assert average([1, 2, 3]) == 2.0

def test_average_empty():
    try:
        average([])
        assert False
    except ZeroDivisionError:
        pass
""")
    return ws


def verify_debug_wrong_output(workspace):
    path = os.path.join(workspace, "calc.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "len(numbers) == 0" in content and "return 0.0" in content


def _debug_wrong_output_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "test_calc.py"}), _tc("read_file", {"path": "calc.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "calc.py", "content": "def average(numbers):\n    if len(numbers) == 0:\n        return 0.0\n    return sum(numbers) / len(numbers)\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="debug_wrong_output",
    description="Fix function to handle edge case",
    horizon=7,
    setup_fn=setup_debug_wrong_output,
    execute_fn=None,
    verify_fn=verify_debug_wrong_output,
    partial_credit_fn=lambda ws: 0.7 if verify_debug_wrong_output(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "debug"],
    user_input="Read the test and fix average() so it handles empty list without ZeroDivisionError",
    model_responses=_debug_wrong_output_responses(),
    expected_output="done",
))


# ---------------------------------------------------------------------------
# Recovery under failure (SWE-bench style with injected faults)
# ---------------------------------------------------------------------------

def setup_recovery_after_wrong_edit():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "data.py"), "w") as f:
        f.write("""values = [1, 2, 3]

def total():
    return sum(values)
""")
    return ws


def verify_recovery_after_wrong_edit(workspace):
    path = os.path.join(workspace, "data.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "values.append(4)" in content and "total()" in content


def _recovery_after_wrong_edit_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "data.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "data.py", "content": "values = [1, 2, 3]\nvalues.append(4)\n\ndef total():\n    return sum(values)\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="recovery_after_wrong_edit",
    description="Recover from a bad edit and complete the task",
    horizon=7,
    setup_fn=setup_recovery_after_wrong_edit,
    execute_fn=None,
    verify_fn=verify_recovery_after_wrong_edit,
    partial_credit_fn=lambda ws: 0.7 if verify_recovery_after_wrong_edit(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=True,
    stress_context_folding=False,
    tags=["integration", "swebench", "recovery"],
    user_input="Append 4 to values in data.py",
    model_responses=_recovery_after_wrong_edit_responses(),
    expected_output="done",
))


def setup_recovery_timeout_then_success():
    ws = tempfile.mkdtemp()
    return ws


def verify_recovery_timeout_then_success(workspace):
    return os.path.exists(os.path.join(workspace, "log.txt"))


def _recovery_timeout_then_success_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "log.txt", "content": "started"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "log.txt", "content": "started\nprogress"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "log.txt", "content": "started\nprogress\ndone"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="recovery_timeout_then_success",
    description="Succeed after transient failures",
    horizon=8,
    setup_fn=setup_recovery_timeout_then_success,
    execute_fn=None,
    verify_fn=verify_recovery_timeout_then_success,
    partial_credit_fn=lambda ws: 0.7 if verify_recovery_timeout_then_success(ws) else 0.0,
    required_tools=["write_file"],
    stress_recovery=True,
    stress_context_folding=False,
    tags=["integration", "swebench", "recovery"],
    user_input="Write a log file with 3 lines: started, progress, done",
    model_responses=_recovery_timeout_then_success_responses(),
    expected_output="done",
))


# ---------------------------------------------------------------------------
# Context-folding stress (long-horizon IDE tasks)
# ---------------------------------------------------------------------------

def setup_context_fold_multi_edit():
    ws = tempfile.mkdtemp()
    os.makedirs(os.path.join(ws, "pkg"), exist_ok=True)
    for i in range(6):
        with open(os.path.join(ws, f"mod{i}.py"), "w") as f:
            f.write(f"# module {i}\nVALUE = {i}\n")
    return ws


def verify_context_fold_multi_edit(workspace):
    count = 0
    for i in range(6):
        path = os.path.join(workspace, f"mod{i}.py")
        if os.path.exists(path):
            with open(path) as f:
                if f"VALUE = {i + 1}" in f.read():
                    count += 1
    return count >= 5


def _context_fold_multi_edit_responses():
    writes = []
    for i in range(6):
        writes.append(Message("assistant", "", tool_calls=[_tc("write_file", {"path": f"mod{i}.py", "content": f"# module {i}\nVALUE = {i + 1}\n"})]))
    writes.append(Message("assistant", "done"))
    return writes


TaskRegistry.register(BenchmarkTask(
    name="context_fold_multi_edit",
    description="Edit many files across a long trajectory",
    horizon=60,
    setup_fn=setup_context_fold_multi_edit,
    execute_fn=None,
    verify_fn=verify_context_fold_multi_edit,
    partial_credit_fn=lambda ws: min(1.0, sum(1 for i in range(6) if os.path.exists(os.path.join(ws, f"mod{i}.py"))) / 6.0),
    required_tools=["write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=True,
    tags=["integration", "idebench", "folding"],
    user_input="Increment VALUE in all mod*.py files",
    model_responses=_context_fold_multi_edit_responses(),
    expected_output="done",
))


def setup_context_fold_search_replace():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "readme.md"), "w") as f:
        f.write("""# Project

## Setup
Run install.py

## Usage
Run app.py
""")
    return ws


def verify_context_fold_search_replace(workspace):
    path = os.path.join(workspace, "readme.md")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "python install.py" in content and "python app.py" in content


def _context_fold_search_replace_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "readme.md"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "readme.md", "content": "# Project\n\n## Setup\nRun python install.py\n\n## Usage\nRun python app.py\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="context_fold_search_replace",
    description="Search and replace text across files",
    horizon=45,
    setup_fn=setup_context_fold_search_replace,
    execute_fn=None,
    verify_fn=verify_context_fold_search_replace,
    partial_credit_fn=lambda ws: 0.8 if verify_context_fold_search_replace(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=True,
    tags=["integration", "idebench", "folding"],
    user_input="Update readme.md to show python commands instead of bare filenames",
    model_responses=_context_fold_search_replace_responses(),
    expected_output="done",
))


# ---------------------------------------------------------------------------
# Composite SWE-style tasks
# ---------------------------------------------------------------------------

def setup_swe_style_bugfix():
    ws = tempfile.mkdtemp()
    os.makedirs(os.path.join(ws, "pkg"), exist_ok=True)
    os.makedirs(os.path.join(ws, "tests"), exist_ok=True)
    with open(os.path.join(ws, "pkg", "parser.py"), "w") as f:
        f.write("""def parse_line(line):
    parts = line.split(",")
    return {"id": parts[0], "value": parts[1]}
""")
    with open(os.path.join(ws, "pkg", "loader.py"), "w") as f:
        f.write("""from .parser import parse_line

def load(path):
    with open(path) as f:
        return [parse_line(line) for line in f]
""")
    with open(os.path.join(ws, "tests", "test_parser.py"), "w") as f:
        f.write("""from pkg.parser import parse_line

def test_parse_line():
    assert parse_line("1,hello") == {"id": "1", "value": "hello"}

def test_parse_line_extra_whitespace():
    assert parse_line("1, hello ") == {"id": "1", "value": "hello"}
""")
    return ws


def verify_swe_style_bugfix(workspace):
    parser_path = os.path.join(workspace, "pkg", "parser.py")
    if not os.path.exists(parser_path):
        return False
    with open(parser_path) as f:
        content = f.read()
    return "strip()" in content


def _swe_style_bugfix_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "pkg/parser.py"}), _tc("read_file", {"path": "tests/test_parser.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "pkg/parser.py", "content": "def parse_line(line):\n    parts = line.split(\",\")\n    return {\"id\": parts[0].strip(), \"value\": parts[1].strip()}\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="swe_style_bugfix",
    description="SWE-bench style: read tests, fix parser to strip whitespace",
    horizon=8,
    setup_fn=setup_swe_style_bugfix,
    execute_fn=None,
    verify_fn=verify_swe_style_bugfix,
    partial_credit_fn=lambda ws: 0.7 if verify_swe_style_bugfix(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "swebench", "bugfix", "test_driven"],
    user_input="Read the tests and fix parser.parse_line so test_parse_line_extra_whitespace passes",
    model_responses=_swe_style_bugfix_responses(),
    expected_output="done",
))


def setup_ide_style_multi_file_edit():
    ws = tempfile.mkdtemp()
    os.makedirs(os.path.join(ws, "services"), exist_ok=True)
    with open(os.path.join(ws, "services", "user.py"), "w") as f:
        f.write("""class UserService:
    def get_user(self, user_id):
        return {"id": user_id, "name": "unknown"}
""")
    with open(os.path.join(ws, "services", "order.py"), "w") as f:
        f.write("""class OrderService:
    def get_order(self, order_id):
        return {"id": order_id, "total": 0}
""")
    with open(os.path.join(ws, "services", "__init__.py"), "w") as f:
        f.write("")
    return ws


def verify_ide_style_multi_file_edit(workspace):
    user_path = os.path.join(workspace, "services", "user.py")
    order_path = os.path.join(workspace, "services", "order.py")
    if not os.path.exists(user_path) or not os.path.exists(order_path):
        return False
    with open(user_path) as f:
        user = f.read()
    with open(order_path) as f:
        order = f.read()
    return "cache" in user.lower() and "cache" in order.lower()


def _ide_style_multi_file_edit_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "services/user.py"}), _tc("read_file", {"path": "services/order.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "services/user.py", "content": "class UserService:\n    _cache = {}\n\n    def get_user(self, user_id):\n        if user_id in self._cache:\n            return self._cache[user_id]\n        user = {\"id\": user_id, \"name\": \"unknown\"}\n        self._cache[user_id] = user\n        return user\n"}), _tc("write_file", {"path": "services/order.py", "content": "class OrderService:\n    _cache = {}\n\n    def get_order(self, order_id):\n        if order_id in self._cache:\n            return self._cache[order_id]\n        order = {\"id\": order_id, \"total\": 0}\n        self._cache[order_id] = order\n        return order\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="ide_style_multi_file_edit",
    description="IDE-Bench style: add caching to multiple service files",
    horizon=10,
    setup_fn=setup_ide_style_multi_file_edit,
    execute_fn=None,
    verify_fn=verify_ide_style_multi_file_edit,
    partial_credit_fn=lambda ws: 0.6 if verify_ide_style_multi_file_edit(ws) else 0.0,
    required_tools=["read_file", "write_file", "list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "idebench", "multi_file"],
    user_input="Add in-memory caching to UserService and OrderService using a class-level _cache dict",
    model_responses=_ide_style_multi_file_edit_responses(),
    expected_output="done",
))


def setup_swe_style_regression():
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "api.py"), "w") as f:
        f.write("""def fetch_user(user_id):
    response = {"id": user_id, "name": "User " + str(user_id)}
    return response

def fetch_users(user_ids):
    return [fetch_user(uid) for uid in user_ids]
""")
    return ws


def verify_swe_style_regression(workspace):
    path = os.path.join(workspace, "api.py")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return "None" in content and "if user_id is None" in content


def _swe_style_regression_responses():
    return [
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "api.py"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "api.py", "content": "def fetch_user(user_id):\n    if user_id is None:\n        return None\n    response = {\"id\": user_id, \"name\": \"User \" + str(user_id)}\n    return response\n\ndef fetch_users(user_ids):\n    return [fetch_user(uid) for uid in user_ids]\n"})]),
        Message("assistant", "done"),
    ]


TaskRegistry.register(BenchmarkTask(
    name="swe_style_regression",
    description="SWE-bench style: handle None input to prevent regression",
    horizon=6,
    setup_fn=setup_swe_style_regression,
    execute_fn=None,
    verify_fn=verify_swe_style_regression,
    partial_credit_fn=lambda ws: 0.7 if verify_swe_style_regression(ws) else 0.0,
    required_tools=["read_file", "write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "swebench", "bugfix"],
    user_input="Fix fetch_user to return None when user_id is None instead of crashing",
    model_responses=_swe_style_regression_responses(),
    expected_output="done",
))
