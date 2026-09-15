"""Evidence matching for diagnose-before-mutation.

A diagnosis quotes evidence from a file. The quote must occur in the file; whitespace runs are treated as equal
(small models reflow indentation and line breaks when copying) and the quote must carry at least
MIN_EVIDENCE_CHARS non-space characters so a trivial token cannot stand in for evidence.
"""

from __future__ import annotations

import re

MIN_EVIDENCE_CHARS = 5


def evidence_line_span(text: str, evidence: str) -> tuple[int, int] | None:
    """1-based inclusive line span of the first occurrence of `evidence` in `text`, or None if absent/too short."""
    tokens = evidence.split()
    if sum(len(t) for t in tokens) < MIN_EVIDENCE_CHARS:
        return None
    match = re.search(r"\s+".join(re.escape(t) for t in tokens), text)
    if match is None:
        return None
    return text.count("\n", 0, match.start()) + 1, text.count("\n", 0, match.end()) + 1


def python_symbol_span(text: str, target: str) -> tuple[int, int] | None:
    """Gate qwen_extract_v1 selector for .py: exact name of a module-level function/class, a method as `Class.method`,
    or a module-level assigned name. Returns the definition's 1-based inclusive line span."""
    import ast

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == target:
                return node.lineno, node.end_lineno or node.lineno
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and f"{node.name}.{child.name}" == target:
                        return child.lineno, child.end_lineno or child.lineno
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == target for t in node.targets):
                return node.lineno, node.end_lineno or node.lineno
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == target:
            return node.lineno, node.end_lineno or node.lineno
    return None


def json_pointer_span(text: str, pointer: str) -> tuple[int, int] | None:
    """Gate qwen_extract_v1 selector for .json: an RFC 6901 pointer that resolves in the parsed text. Span = the line of
    the final object member's key, found by scanning for each segment's `"key":` in order. An array-index segment ends
    the scan at the enclosing key's line (None when the array is the document root)."""
    import json

    if not pointer.startswith("/"):
        return None
    try:
        node = json.loads(text)
    except ValueError:
        return None
    segments = [s.replace("~1", "/").replace("~0", "~") for s in pointer[1:].split("/")]
    resolved = node
    for segment in segments:  # the whole pointer must resolve before any line is reported
        if isinstance(resolved, dict) and segment in resolved:
            resolved = resolved[segment]
        elif isinstance(resolved, list) and segment.isdigit() and int(segment) < len(resolved):
            resolved = resolved[int(segment)]
        else:
            return None
    position, line = 0, None
    for segment in segments:
        if isinstance(node, dict):
            if segment not in node:
                return None
            match = re.compile(re.escape(json.dumps(segment)) + r"\s*:").search(text, position)
            if match is None:
                return None
            position = match.end()
            line = text.count("\n", 0, match.start()) + 1
            node = node[segment]
        elif isinstance(node, list):
            if not segment.isdigit() or int(segment) >= len(node):
                return None
            return (line, line) if line is not None else None
        else:
            return None
    return (line, line) if line is not None else None


def target_line_span(path: str, text: str, target: str) -> tuple[int, int] | None:
    """Resolve a qwen_extract_v1 selector against a read snapshot. Exact matching only; unsupported types yield None."""
    if path.endswith(".py"):
        return python_symbol_span(text, target)
    if path.endswith(".json"):
        return json_pointer_span(text, target)
    return None
