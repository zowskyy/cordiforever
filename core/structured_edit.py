"""Structured, verifiable file edits: exact text replacement and JSON patching on parsed data.

Pure functions (no filesystem). Every operation either returns the complete new file text or raises
EditError; callers commit only returned text and then verify the postcondition by re-reading.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from .errors import ToolError


class EditError(ToolError):
    """A structured edit was refused; the file must be left unchanged."""


_MISSING = object()


def replace_exact(text: str, old: str, new: str) -> str:
    if not isinstance(old, str) or not isinstance(new, str):
        raise EditError("old and new must be strings.")
    if old == "":
        raise EditError("old must not be empty.")
    if old == new:
        raise EditError("old and new are identical; nothing would change.")
    count = text.count(old)
    if count == 0:
        raise EditError("old text not found. It must match the file exactly, including spaces and indentation.")
    if count > 1:
        raise EditError(f"old text matches {count} places. Include more surrounding text so it matches exactly once.")
    return text.replace(old, new, 1)


def parse_pointer(pointer: str) -> list[str]:
    """RFC 6901 JSON Pointer. A bare key without a leading '/' is accepted as a single top-level segment."""
    if not isinstance(pointer, str):
        raise EditError("JSON path must be a string.")
    if pointer == "" or pointer == "/":
        raise EditError("Replacing the whole document is not allowed; set individual keys instead.")
    if not pointer.startswith("/"):
        return [pointer]
    segments = pointer[1:].split("/")
    if any(s == "" for s in segments):
        raise EditError(f"Invalid JSON path {pointer!r}: empty segment.")
    return [s.replace("~1", "/").replace("~0", "~") for s in segments]


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise EditError(f"Unsupported value type: {type(value).__name__}")


def _parent_and_key(doc: Any, segments: list[str], pointer: str) -> tuple[Any, str | int]:
    node = doc
    for seg in segments[:-1]:
        if isinstance(node, dict) and seg in node:
            node = node[seg]
        elif isinstance(node, list) and re.fullmatch(r"\d+", seg) and int(seg) < len(node):
            node = node[int(seg)]
        else:
            raise EditError(f"JSON path {pointer!r} does not exist (missing {seg!r}).")
    last = segments[-1]
    if isinstance(node, dict):
        return node, last
    if isinstance(node, list):
        if last == "-":
            return node, len(node)
        if re.fullmatch(r"\d+", last):
            return node, int(last)
        raise EditError(f"JSON path {pointer!r}: {last!r} is not an array index.")
    raise EditError(f"JSON path {pointer!r}: parent is a {_json_type(node)}, not an object or array.")


def apply_json_patch(doc: Any, set_values: dict[str, Any] | None = None, remove: list[str] | None = None) -> tuple[Any, list[str]]:
    """Return (new document, human-readable change list). Existing values keep their JSON type."""
    if not isinstance(doc, (dict, list)):
        raise EditError("patch_json only edits JSON objects or arrays.")
    set_values = set_values or {}
    remove = remove or []
    if not isinstance(set_values, dict) or not isinstance(remove, list):
        raise EditError("set must be an object and remove must be a list of JSON paths.")
    if not set_values and not remove:
        raise EditError("Nothing to change: provide set and/or remove.")
    result = copy.deepcopy(doc)
    changes: list[str] = []
    for pointer, value in set_values.items():
        segments = parse_pointer(pointer)
        new_type = _json_type(value)
        parent, key = _parent_and_key(result, segments, pointer)
        if isinstance(parent, dict):
            old = parent.get(key, _MISSING)
        else:
            if key > len(parent):
                raise EditError(f"JSON path {pointer!r}: index {key} is past the end of the array.")
            old = parent[key] if key < len(parent) else _MISSING
        if old is not _MISSING and _json_type(old) != new_type:
            raise EditError(f"JSON path {pointer!r} holds a {_json_type(old)}; refusing to replace it with a {new_type}.")
        if isinstance(parent, list) and old is _MISSING:
            parent.append(value)
        else:
            parent[key] = value
        before = "(new)" if old is _MISSING else json.dumps(old, ensure_ascii=False)
        changes.append(f"{'/' + '/'.join(segments)}: {before} -> {json.dumps(value, ensure_ascii=False)}")
    for pointer in remove:
        segments = parse_pointer(pointer)
        parent, key = _parent_and_key(result, segments, pointer)
        exists = key in parent if isinstance(parent, dict) else isinstance(key, int) and key < len(parent)
        if not exists:
            raise EditError(f"JSON path {pointer!r} does not exist; nothing to remove.")
        del parent[key]
        changes.append(f"{'/' + '/'.join(segments)}: removed")
    return result, changes


def serialize_like(original_text: str, doc: Any) -> str:
    """Serialize JSON keeping the original's indentation style and trailing newline."""
    indent_match = re.search(r"\n([ \t]+)\S", original_text)
    if indent_match:
        indent = indent_match.group(1)
        text = json.dumps(doc, ensure_ascii=False, indent="\t" if indent.startswith("\t") else len(indent))
    else:
        text = json.dumps(doc, ensure_ascii=False)
    return text + ("\n" if original_text.endswith("\n") else "")


def _top_level_names(tree: Any) -> set[str]:
    import ast

    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


STRUCTURAL_NOOP_MESSAGE = "Replacement is structurally equivalent to the current definition and does not constitute a substantive edit."


def target_definition_node(tree: Any, target: str) -> Any:
    """The AST node selected by the python_symbol selector (same semantics as core.diagnosis.python_symbol_span)."""
    import ast

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == target:
                return node
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and f"{node.name}.{child.name}" == target:
                        return child
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == target for t in node.targets):
            return node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == target:
            return node
    return None


def is_structural_noop(original_node: Any, replacement_tree: Any) -> bool:
    """Gate qwen_astnoop_v1: the replacement is exactly one statement whose AST, without line/column attributes, equals
    the selected definition's. A structural no-op detector only; it does not claim behavioral equivalence."""
    import ast

    if original_node is None or len(replacement_tree.body) != 1:
        return False
    return ast.dump(replacement_tree.body[0], annotate_fields=True, include_attributes=False) == ast.dump(original_node, annotate_fields=True, include_attributes=False)


def replace_python_symbol(path: str, text: str, target: str, replacement: str, refuse_structural_noop: bool = False) -> tuple[str, tuple[int, int]]:
    """Gate qwen_localedit_v1: replace exactly the definition selected by `target` (qwen_extract_v1 selector semantics)
    with `replacement`, re-indented to the target's indentation. Returns (new text, replaced line span).
    With `refuse_structural_noop` (gate qwen_astnoop_v1), a normalized-AST-identical replacement is refused."""
    import ast
    import textwrap

    from .diagnosis import python_symbol_span

    if not isinstance(replacement, str) or not replacement.strip():
        raise EditError("replacement must be non-empty Python source.")
    span = python_symbol_span(text, target)
    if span is None:
        raise EditError(f"{target} is not a function, class, method or assignment defined in {path}.")
    source = textwrap.dedent(replacement).strip("\n")
    try:
        rep_tree = ast.parse(source)
    except SyntaxError as exc:
        raise EditError(f"replacement is not valid Python ({exc.msg}, line {exc.lineno}).") from exc
    name = target.split(".")[-1]
    defined = _top_level_names(rep_tree)
    if name not in defined:
        raise EditError(f"replacement must define {name}.")
    original_tree = ast.parse(text)
    if refuse_structural_noop and is_structural_noop(target_definition_node(original_tree, target), rep_tree):
        raise EditError(STRUCTURAL_NOOP_MESSAGE)
    if "." in target:
        class_name = target.split(".")[0]
        owner = next(n for n in original_tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
        existing = {n.name for n in owner.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    else:
        existing = _top_level_names(original_tree)
    clobbered = sorted((defined - {name}) & existing)
    if clobbered:
        raise EditError(f"replacement also redefines {', '.join(clobbered)}, which already exist in {path}.")
    lines = text.splitlines()
    first = lines[span[0] - 1]
    indent = first[: len(first) - len(first.lstrip())]
    new_block = [(indent + line) if line.strip() else "" for line in source.splitlines()]
    new_text = "\n".join(lines[: span[0] - 1] + new_block + lines[span[1]:]) + ("\n" if text.endswith("\n") else "")
    try:
        new_tree = ast.parse(new_text)
        compile(new_text, path, "exec")
    except (SyntaxError, ValueError) as exc:
        raise EditError(f"Edit rejected: {path} would no longer be valid Python.") from exc
    lost = sorted(_top_level_names(original_tree) - _top_level_names(new_tree))
    if lost:
        raise EditError(f"Edit rejected: {path} would no longer define {', '.join(lost)}.")
    return new_text, span


def set_json_pointer_value(path: str, text: str, pointer: str, replacement: str) -> tuple[str, str]:
    """Gate qwen_localedit_v1: set the value at an RFC 6901 pointer that already resolves. Returns (new text, change)."""
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        raise EditError(f"{pointer} is not a JSON pointer that resolves in {path}.")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EditError(f"{path} is not valid JSON ({exc.msg}).") from exc
    node = doc
    for segment in (s.replace("~1", "/").replace("~0", "~") for s in pointer[1:].split("/")):
        if isinstance(node, dict) and segment in node:
            node = node[segment]
        elif isinstance(node, list) and segment.isdigit() and int(segment) < len(node):
            node = node[int(segment)]
        else:
            raise EditError(f"{pointer} is not a JSON pointer that resolves in {path}.")
    try:
        value = json.loads(replacement)
    except (json.JSONDecodeError, TypeError) as exc:
        raise EditError("replacement must be a JSON value (for example 8080, \"text\", [\"a\"], {\"k\": 1}).") from exc
    new_doc, changes = apply_json_patch(doc, {pointer: value})
    new_text = serialize_like(text, new_doc)
    validate_language(path, text, new_text)
    return new_text, changes[0]


def validate_language(path: str, before: str, after: str) -> None:
    """Refuse an edit that breaks a file which was syntactically valid before it."""
    lower = path.lower()
    if lower.endswith(".py"):
        try:
            compile(before, path, "exec")
        except (SyntaxError, ValueError):
            return
        try:
            compile(after, path, "exec")
        except (SyntaxError, ValueError) as exc:
            raise EditError(f"Edit rejected: {path} would no longer be valid Python ({exc.msg}, line {exc.lineno}).") from exc
    elif lower.endswith(".json"):
        try:
            json.loads(before)
        except json.JSONDecodeError:
            return
        try:
            json.loads(after)
        except json.JSONDecodeError as exc:
            raise EditError(f"Edit rejected: {path} would no longer be valid JSON ({exc.msg}).") from exc
