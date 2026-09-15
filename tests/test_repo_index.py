from __future__ import annotations

import os
import time
from pathlib import Path

from core.repo_index import MAX_OUTPUT_CHARS, RepositoryIndex, index_for, is_test_file

MATHLIB = Path(__file__).resolve().parents[1] / "benchmark" / "repos" / "mathlib"
INVENTORY = Path(__file__).resolve().parents[1] / "benchmark" / "repos" / "inventory"


def test_outline_lists_files_symbols_exports_and_internal_imports():
    outline = RepositoryIndex(MATHLIB).repo_outline()
    assert "  operations.py — functions: add, subtract, multiply, divide" in outline
    assert "  __init__.py — exports: add, subtract, multiply, divide, mean, median; imports: mathlib/operations.py, mathlib/stats.py" in outline
    assert "  calculator.py — functions: evaluate; constants: OPERATIONS; imports: mathlib/__init__.py" in outline
    assert "legacy/" in outline and "tests/" in outline


def test_find_symbol_reports_definitions_exports_imports_and_references():
    text = RepositoryIndex(MATHLIB).find_symbol("subtract")
    assert text.splitlines() == [
        "subtract", "DEFINED:", "  legacy/operations.py:8 (function subtract)", "  mathlib/operations.py:5 (function subtract)",
        "EXPORTED:", "  mathlib/__init__.py", "IMPORTED:", "  calculator.py:1", "  mathlib/__init__.py:1",
        "REFERENCED:", "  calculator.py:5",
    ]


def test_find_symbol_redirects_invented_file_names():
    index = RepositoryIndex(MATHLIB)
    assert index.find_symbol("median.py") == "median.py: no such file. median is defined in mathlib/stats.py:5."
    assert index.find_symbol("sqrt") == "sqrt: not defined in this repository."


def test_find_references_includes_enclosing_function_and_line_text():
    text = RepositoryIndex(MATHLIB).find_references("median")
    assert text == "median: 1 reference(s)\n  tests/test_core.py:18 in test_median_odd_length  assert median([3, 1, 2]) == 2"


def test_find_tests_by_file_and_symbol():
    index = RepositoryIndex(MATHLIB)
    assert index.find_tests("mathlib/stats.py") == "mathlib/stats.py: tests\n  tests/test_core.py: test_mean, test_median_odd_length"
    assert index.find_tests("evaluate") == "evaluate: tests\n  tests/test_core.py: test_calculator_add"
    assert index.find_tests("subtract") == "subtract: no tests found."
    assert RepositoryIndex(INVENTORY).find_tests("inventory/service.py") == "inventory/service.py: no tests found."


def test_dependency_cone_for_file_and_symbol():
    index = RepositoryIndex(MATHLIB)
    assert index.dependency_cone("mathlib/operations.py", depth=2) == (
        "mathlib/operations.py (file)\nIMPORTS:\n  (none)\nIMPORTED BY:\n  mathlib/__init__.py\n    calculator.py\n    tests/test_core.py"
    )
    shallow = index.dependency_cone("mathlib.operations", depth=1)
    assert "calculator.py" not in shallow and "mathlib/__init__.py" in shallow
    symbol = index.dependency_cone("evaluate")
    assert "DEFINED: calculator.py:11" in symbol and "CALLED BY:\n  test_calculator_add (tests/test_core.py)" in symbol
    assert index.dependency_cone("nothing.py").endswith("Call repo_outline to see what exists.")


def test_methods_calls_and_relative_imports(tmp_path):
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "base.py").write_text("LIMIT = 3\n\ndef helper(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "pkg" / "sub" / "worker.py").write_text(
        "from ..base import helper, LIMIT\n\nclass Worker:\n    def run(self, x):\n        return helper(x) + LIMIT\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    index = RepositoryIndex(tmp_path)
    assert "worker.py — classes: Worker; imports: pkg/base.py" in index.repo_outline()
    assert "broken.py — unparseable" in index.repo_outline()
    cone = index.dependency_cone("Worker.run")
    assert "CALLS:\n  helper (pkg/base.py:3)" in cone
    assert "CALLED BY:\n  Worker.run (pkg/sub/worker.py)" in index.dependency_cone("helper")
    assert "(constant LIMIT)" in index.find_symbol("LIMIT")


def test_output_is_bounded(tmp_path):
    for i in range(400):
        (tmp_path / f"module_{i:03d}.py").write_text(f"def function_number_{i}():\n    return {i}\n", encoding="utf-8")
    outline = RepositoryIndex(tmp_path).repo_outline()
    assert len(outline) <= MAX_OUTPUT_CHARS and outline.endswith("(truncated)")


def test_index_cache_rebuilds_on_change(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("def one():\n    pass\n", encoding="utf-8")
    first = index_for(tmp_path)
    assert index_for(tmp_path) is first
    target.write_text("def one():\n    pass\n\ndef two():\n    pass\n", encoding="utf-8")
    later = time.time() + 5
    os.utime(target, (later, later))
    second = index_for(tmp_path)
    assert second is not first and "functions: one, two" in second.repo_outline()


def test_is_test_file():
    assert is_test_file("tests/test_core.py") and is_test_file("pkg/foo_test.py") and is_test_file("tests/helpers.py")
    assert not is_test_file("pkg/testing_utils.py") and not is_test_file("tests/data.json")
