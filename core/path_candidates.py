"""Deterministic, deliberately narrow near-path lookup shared by the wrong-path guard and its evaluation.

A candidate is an existing workspace file that either has exactly the requested file name
(``exact_basename``) or looks like a typo of it (``near_name``: same extension, stem similarity
>= 0.85, stem length within 2). This is not fuzzy search: names like ``app.test.json`` or
``adder.py`` are not conflicts for ``app.json`` / ``add.py``.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache"}
_MAX_FILES = 5000
_NEAR_STEM_RATIO = 0.85
_NEAR_STEM_LENGTH_DELTA = 2

ConflictKind = Literal["exact_basename", "near_name"]


@dataclass(frozen=True)
class Candidate:
    path: str
    kind: ConflictKind


@dataclass(frozen=True)
class PathVerdict:
    wrong_path: bool
    conflict: ConflictKind | None
    candidates: list[str]


def normalize(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").removeprefix("./").strip("/")


def _split_name(name: str) -> tuple[str, str]:
    stem, dot, ext = name.rpartition(".")
    return (stem, ext) if dot and stem else (name, "")


def workspace_files(workspace: Path) -> list[str]:
    files: list[str] = []
    root = workspace.resolve()
    for candidate in sorted(root.rglob("*")):
        if any(part in _SKIP_DIRS for part in candidate.relative_to(root).parts):
            continue
        if candidate.is_file() and not candidate.is_symlink():
            files.append(candidate.relative_to(root).as_posix())
            if len(files) >= _MAX_FILES:
                break
    return files


def near_paths(workspace: Path, requested: str, limit: int = 5) -> list[Candidate]:
    """Existing files conflicting with the requested path: exact file-name matches first, then typo-like names."""
    wanted = normalize(requested)
    wanted_name = wanted.rsplit("/", 1)[-1].lower()
    wanted_stem, wanted_ext = _split_name(wanted_name)
    exact: list[Candidate] = []
    near: list[tuple[float, Candidate]] = []
    for rel in workspace_files(workspace):
        if rel == wanted:
            continue
        name = rel.rsplit("/", 1)[-1].lower()
        if name == wanted_name:
            exact.append(Candidate(rel, "exact_basename"))
            continue
        stem, ext = _split_name(name)
        if ext != wanted_ext or abs(len(stem) - len(wanted_stem)) > _NEAR_STEM_LENGTH_DELTA:
            continue
        ratio = difflib.SequenceMatcher(None, stem, wanted_stem).ratio()
        if ratio >= _NEAR_STEM_RATIO:
            near.append((ratio, Candidate(rel, "near_name")))
    near.sort(key=lambda item: (-item[0], item[1].path))
    return (exact + [c for _, c in near])[:limit]


def _token_in(text: str, needle: str) -> bool:
    return len(needle) >= 3 and re.search(rf"(?<![\w./-]){re.escape(needle)}(?![\w/-]|\.\w)", text) is not None


def mentioned_in(request: str, path: str, exact_only: bool = False) -> bool:
    """True if the request names this path (or, unless exact_only, its file name) as a standalone token."""
    wanted = normalize(path).lower()
    if not wanted:
        return False
    text = request.lower().replace("\\", "/")
    if _token_in(text, wanted):
        return True
    return not exact_only and _token_in(text, wanted.rsplit("/", 1)[-1])


_PATH_TOKEN = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w-][\w.-]*\.[A-Za-z0-9]{1,8})(?![\w/-]|\.\w)")


def request_path_refs(request: str) -> list[str]:
    """Path- or file-name-like tokens in the request (must contain an extension), in order, de-duplicated."""
    seen: list[str] = []
    for match in _PATH_TOKEN.finditer(request.replace("\\", "/")):
        ref = normalize(match.group(1))
        if ref and ref not in seen and not re.fullmatch(r"[\d.]+", ref):
            seen.append(ref)
    return seen


DECLARABLE_EXTENSIONS = frozenset({"py", "json", "txt", "md", "yml", "yaml", "toml", "cfg", "ini", "js", "ts", "html", "css", "csv", "log", "sh", "ps1"})


def declared_paths(text: str) -> list[str]:
    """File paths mentioned in free text. A dotted symbol such as calculator.evaluate is not a file."""
    return [ref for ref in request_path_refs(text or "") if ref.rsplit(".", 1)[-1].lower() in DECLARABLE_EXTENSIONS]


def ground_request(workspace: Path, request: str) -> list[str]:
    """Compact path grounding for references already in the request. Never lists the workspace tree.

    - reference exists as written                      -> nothing
    - missing, has a folder (explicitly requested path) -> kept as-is; a line only if the same file name exists
                                                           elsewhere, and that line never names the other file
    - missing, bare file name                          -> 0 candidates: nothing; 1: "ref → path"; >1: ambiguous, all listed
    """
    root = workspace.resolve()
    lines: list[str] = []
    for ref in request_path_refs(request):
        try:
            target = (root / ref).resolve()
            target.relative_to(root)
        except (ValueError, OSError):
            continue
        if target.exists():
            continue
        candidates = near_paths(root, ref)
        if "/" in ref:
            name = ref.rsplit("/", 1)[-1].lower()
            if any(c.kind == "exact_basename" and c.path.rsplit("/", 1)[-1].lower() == name for c in candidates):
                lines.append(f"{ref} → new file at exactly {ref}")
            continue
        if len(candidates) == 1:
            lines.append(f"{ref} → {candidates[0].path}")
        elif len(candidates) > 1:
            lines.append(f"{ref} → ambiguous: {', '.join(c.path for c in candidates)}")
    return lines


def named_existing_files(workspace: Path, request: str) -> list[list[str]]:
    """Existing files the request names, as alternatives: each inner list must have at least one member read.

    - reference exists as written                -> [ref]
    - bare file name, exact-name match(es) exist -> [all exact matches] (any one satisfies an ambiguous name)
    - otherwise (new file, near-name only, escape) -> no requirement
    """
    root = workspace.resolve()
    requirements: list[list[str]] = []
    for ref in request_path_refs(request):
        try:
            target = (root / ref).resolve()
            target.relative_to(root)
        except (ValueError, OSError):
            continue
        if target.is_file():
            requirements.append([ref])
        elif "/" not in ref and not target.exists():
            exact = [c.path for c in near_paths(root, ref, limit=10) if c.kind == "exact_basename"]
            if exact:
                requirements.append(exact)
    return requirements


def classify_path(workspace: Path, tool: str, path: str, request: str) -> PathVerdict:
    """Decide whether a read/write proposal targets the wrong path.

    - target exists: not this guard's concern (overwrite rules apply)
    - target missing, no candidate: allowed (reads fail normally in the tool; writes create)
    - target missing, candidate exists: reads are wrong_path; writes are wrong_path unless authorized:
        exact_basename conflict -> only a full path containing a folder, named in the request, authorizes
        near_name conflict      -> naming the path or its file name authorizes
    """
    none = PathVerdict(False, None, [])
    if tool not in ("read_file", "write_file", "replace_text", "patch_json", "edit_symbol") or not isinstance(path, str) or any(c in path for c in "*?["):
        return none
    wanted = normalize(path)
    try:
        target = (workspace / wanted).resolve()
        target.relative_to(workspace.resolve())
    except (ValueError, OSError):
        return none
    if not wanted or target.exists():
        return none
    candidates = near_paths(workspace, path)
    if not candidates:
        return none
    conflict: ConflictKind = candidates[0].kind
    if tool == "write_file":
        if conflict == "exact_basename":
            authorized = "/" in wanted and mentioned_in(request, path, exact_only=True)
        else:
            authorized = mentioned_in(request, path)
        if authorized:
            return none
    return PathVerdict(True, conflict, [c.path for c in candidates])
