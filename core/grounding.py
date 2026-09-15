"""Targeted deterministic grounding: repository coordinates for names the request actually mentions.

Deliberately narrow: no repository outline. For each path-like token and each identifier that names a real
symbol, emit one compact fact. The returned evidence set lists existing paths the grounding established, which the
evidence-gated completion check accepts as support for a declaration.
"""

from __future__ import annotations

import re
from pathlib import Path

from .path_candidates import ground_request, normalize, request_path_refs
from .repo_index import RepositoryIndex, index_for

MAX_SYMBOL_FACTS = 6
_IDENTIFIER = re.compile(r"(?<![\w./-])([A-Za-z_][A-Za-z0-9_]{2,})(?![\w/-]|\.\w)")


def _symbol_fact(index: RepositoryIndex, name: str) -> tuple[str, set[str]]:
    definitions = index.definitions(name)
    places = ", ".join(f"{d.file} line {d.line}" for d in definitions)
    exported = sorted({info.file for info in index.modules.values() if name in info.exports and all(d.file != info.file for d in definitions)})
    fact = f"- {name}: defined in {places}" + (f"; exported by {', '.join(exported)}" if exported else "")
    return fact, {d.file for d in definitions} | set(exported)


def targeted_grounding(workspace: Path, request: str) -> tuple[list[str], set[str]]:
    index = index_for(workspace)
    files = set(index.files)
    lines: list[str] = []
    evidence: set[str] = set()
    mentioned_paths = request_path_refs(request)

    for line in ground_request(workspace, request):
        lines.append(f"- {line}")
    for ref in mentioned_paths:
        path = normalize(ref)
        if path in files:
            evidence.add(path)
            continue
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if path.endswith(".py") and index.definitions(stem):
            fact, found = _symbol_fact(index, stem)
            lines.append(f"- {path}: no such file; {fact[2:]}")
            evidence |= found
    for line in lines:
        evidence |= {p for p in (normalize(r) for r in request_path_refs(line)) if p in files}

    known = {s.name for info in index.modules.values() for s in info.symbols}
    path_words = {normalize(r).rsplit("/", 1)[-1].rsplit(".", 1)[0] for r in mentioned_paths}
    seen: list[str] = []
    for match in _IDENTIFIER.finditer(request):
        name = match.group(1)
        if name in known and name not in seen and name not in path_words:
            seen.append(name)
    for name in seen[:MAX_SYMBOL_FACTS]:
        fact, found = _symbol_fact(index, name)
        lines.append(fact)
        evidence |= found
    return lines, evidence
