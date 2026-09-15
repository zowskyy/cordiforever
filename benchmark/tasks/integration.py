"""
Integration benchmark tasks for real AgentLoop execution
"""

import os
import tempfile
from dataclasses import dataclass, field
from typing import List, Callable, Optional

from core.messages import Message

from .long_horizon import BenchmarkTask, TaskRegistry
from .verification import (
    TaskVerification,
    VerificationCheck,
    VerificationProcedure,
    VerifiedBenchmarkTask,
)


def _tc(name, args):
    return {"function": {"name": name, "arguments": args}}


def setup_simple_write():
    import tempfile
    return tempfile.mkdtemp()


def verify_simple_write(workspace):
    import os
    return os.path.exists(os.path.join(workspace, "a.txt"))


TaskRegistry.register(VerifiedBenchmarkTask(
    name="simple_write",
    description="Write a simple file",
    horizon=3,
    setup_fn=setup_simple_write,
    execute_fn=None,
    verify_fn=verify_simple_write,
    verification=TaskVerification(
        type="artifact",
        checks=[
            VerificationCheck(
                kind="file_content",
                path="a.txt",
                expected="hello",
                mode="exact",
            )
        ],
        procedure=VerificationProcedure(
            allowed_tools=["write_file"],
            required_steps=["tool_call"],
            max_tool_calls=2,
        ),
    ),
    partial_credit_fn=lambda ws: 1.0 if verify_simple_write(ws) else 0.0,
    required_tools=["write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "basic"],
    user_input="write hello to a.txt",
    model_responses=[
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ],
    expected_output="done",
))


def setup_simple_read():
    import tempfile
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "a.txt"), "w") as f:
        f.write("hello")
    return ws


def verify_simple_read(workspace):
    import os
    path = os.path.join(workspace, "a.txt")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        return f.read() == "hello"


TaskRegistry.register(VerifiedBenchmarkTask(
    name="simple_read",
    description="Read a simple file",
    horizon=3,
    setup_fn=setup_simple_read,
    execute_fn=None,
    verify_fn=verify_simple_read,
    verification=TaskVerification(
        type="artifact",
        checks=[
            VerificationCheck(
                kind="file_content",
                path="a.txt",
                expected="hello",
                mode="exact",
            )
        ],
        procedure=VerificationProcedure(
            allowed_tools=["read_file", "list_directory"],
            required_steps=["tool_call"],
            max_tool_calls=2,
        ),
    ),
    partial_credit_fn=lambda ws: 1.0 if verify_simple_read(ws) else 0.0,
    required_tools=["read_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "basic"],
    user_input="read a.txt",
    model_responses=[
        Message("assistant", "", tool_calls=[_tc("read_file", {"path": "a.txt"})]),
        Message("assistant", "done"),
    ],
    expected_output="done",
))


def setup_multi_tool():
    import tempfile
    return tempfile.mkdtemp()


def verify_multi_tool(workspace):
    import os
    return os.path.exists(os.path.join(workspace, "a.txt")) and os.path.exists(os.path.join(workspace, "b.txt"))


TaskRegistry.register(VerifiedBenchmarkTask(
    name="multi_tool_integration",
    description="Create two files in one round",
    horizon=3,
    setup_fn=setup_multi_tool,
    execute_fn=None,
    verify_fn=verify_multi_tool,
    verification=TaskVerification(
        type="artifact",
        checks=[
            VerificationCheck(kind="file_exists", path="a.txt"),
            VerificationCheck(kind="file_exists", path="b.txt"),
        ],
        procedure=VerificationProcedure(
            allowed_tools=["write_file"],
            required_steps=["tool_call"],
            max_tool_calls=2,
        ),
    ),
    partial_credit_fn=lambda ws: sum(1 for f in ["a.txt", "b.txt"] if os.path.exists(os.path.join(ws, f))) / 2.0,
    required_tools=["write_file"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "basic"],
    user_input="create a.txt and b.txt",
    model_responses=[
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "a.txt", "content": "a"}), _tc("write_file", {"path": "b.txt", "content": "b"})]),
        Message("assistant", "done"),
    ],
    expected_output="done",
))


def setup_timeout_recovery():
    import tempfile
    return tempfile.mkdtemp()


def verify_timeout_recovery(workspace):
    import os
    return os.path.exists(os.path.join(workspace, "a.txt"))


TaskRegistry.register(VerifiedBenchmarkTask(
    name="timeout_recovery_integration",
    description="Recover from timeout and complete task",
    horizon=5,
    setup_fn=setup_timeout_recovery,
    execute_fn=None,
    verify_fn=verify_timeout_recovery,
    verification=TaskVerification(
        type="artifact",
        checks=[
            VerificationCheck(kind="file_content", path="a.txt", expected="hello", mode="exact"),
        ],
        procedure=VerificationProcedure(
            allowed_tools=["write_file"],
            required_steps=["tool_call"],
            max_tool_calls=3,
            max_recovery_attempts=2,
        ),
    ),
    partial_credit_fn=lambda ws: 1.0 if verify_timeout_recovery(ws) else 0.0,
    required_tools=["write_file"],
    stress_recovery=True,
    stress_context_folding=False,
    tags=["integration", "recovery"],
    user_input="write hello to a.txt",
    model_responses=[
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ],
    expected_output="done",
))


def setup_context_fold():
    import tempfile
    return tempfile.mkdtemp()


def verify_context_fold(workspace):
    import os
    count = sum(1 for f in os.listdir(workspace) if f.startswith("f") and f.endswith(".txt"))
    return count >= 5


TaskRegistry.register(VerifiedBenchmarkTask(
    name="context_fold_integration",
    description="Write many files to trigger context folding",
    horizon=70,
    setup_fn=setup_context_fold,
    execute_fn=None,
    verify_fn=verify_context_fold,
    verification=TaskVerification(
        type="artifact",
        checks=[
            VerificationCheck(
                kind="file_exists",
                path="f0.txt",
            ),
        ],
        procedure=VerificationProcedure(
            allowed_tools=["write_file"],
            required_steps=["tool_call"],
            max_tool_calls=12,
        ),
    ),
    partial_credit_fn=lambda ws: min(1.0, sum(1 for f in os.listdir(ws) if f.startswith("f") and f.endswith(".txt")) / 10.0),
    required_tools=["write_file"],
    stress_recovery=False,
    stress_context_folding=True,
    tags=["integration", "folding"],
    user_input="write 10 data files",
    model_responses=[
        Message("assistant", "", tool_calls=[_tc("write_file", {"path": f"f{i}.txt", "content": f"data{i}"}) for i in range(10)]),
        Message("assistant", "done"),
    ],
    expected_output="done",
))


def setup_list_directory():
    import tempfile
    ws = tempfile.mkdtemp()
    with open(os.path.join(ws, "a.txt"), "w") as f:
        f.write("hello")
    return ws


def verify_list_directory(workspace):
    import os
    return os.path.exists(os.path.join(workspace, "a.txt"))


TaskRegistry.register(VerifiedBenchmarkTask(
    name="list_directory_integration",
    description="List directory contents",
    horizon=3,
    setup_fn=setup_list_directory,
    execute_fn=None,
    verify_fn=verify_list_directory,
    verification=TaskVerification(
        type="artifact",
        checks=[
            VerificationCheck(kind="file_exists", path="a.txt"),
        ],
        procedure=VerificationProcedure(
            allowed_tools=["list_directory", "read_file"],
            required_steps=["tool_call"],
            max_tool_calls=2,
        ),
    ),
    partial_credit_fn=lambda ws: 1.0 if verify_list_directory(ws) else 0.0,
    required_tools=["list_directory"],
    stress_recovery=False,
    stress_context_folding=False,
    tags=["integration", "basic"],
    user_input="list files",
    model_responses=[
        Message("assistant", "", tool_calls=[_tc("list_directory", {"path": "."})]),
        Message("assistant", "done"),
    ],
    expected_output="done",
))
