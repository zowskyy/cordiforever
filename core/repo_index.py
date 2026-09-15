"""Deterministic Python repository index built from the standard-library AST.

Answers structural questions (where is X defined / exported / referenced, which tests exercise it, what does it
depend on) so a small model does not have to infer repository structure from blind reads. No embeddings, no
external parsers; the index is rebuilt when any file's size or mtime changes.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache"}
_MAX_FILES = 2000
MAX_OUTPUT_CHARS = 4000


@dataclass(frozen=True)
class Symbol:
    name: str
    qualname: str
    kind: str  # function | class | method | constant
    file: str
    line: int
    end_line: int


@dataclass
class ModuleInfo:
    file: str
    module: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[tuple[int, str | None, str, tuple[str, ...]]] = field(default_factory=list)  # (line, internal file|None, raw module, names)
    exports: list[str] = field(default_factory=list)
    parse_error: str | None = None


def _module_name(rel: str) -> str:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return rel.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py") or "tests" in rel.split("/")[:-1])


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[: MAX_OUTPUT_CHARS - 20] + "\n... (truncated)"


class RepositoryIndex:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.files: list[str] = []
        self.modules: dict[str, ModuleInfo] = {}
        self.module_to_file: dict[str, str] = {}
        self.references: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.calls: dict[tuple[str, str], set[str]] = defaultdict(set)  # (file, qualname) -> called simple names
        self._lines: dict[str, list[str]] = {}
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        for path in sorted(self.root.rglob("*")):
            rel_parts = path.relative_to(self.root).parts
            if any(part in _SKIP_DIRS for part in rel_parts) or not path.is_file() or path.is_symlink():
                continue
            rel = "/".join(rel_parts)
            self.files.append(rel)
            if rel.endswith(".py"):
                self.module_to_file[_module_name(rel)] = rel
            if len(self.files) >= _MAX_FILES:
                break
        for rel in self.files:
            if rel.endswith(".py"):
                self._index_module(rel)

    def _resolve(self, current: str, module: str | None, level: int) -> str | None:
        if level:
            base = _module_name(current).split(".")
            if not current.endswith("__init__.py"):
                base = base[:-1]
            base = base[: len(base) - (level - 1)] if level > 1 else base
            target = ".".join([*base, module] if module else base)
        else:
            target = module or ""
        return self.module_to_file.get(target)

    def _index_module(self, rel: str) -> None:
        info = ModuleInfo(rel, _module_name(rel))
        self.modules[rel] = info
        try:
            source = (self.root / rel).read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as exc:
            info.parse_error = f"{type(exc).__name__}: {exc}"
            return
        self._lines[rel] = source.splitlines()

        def define(node: ast.AST, qualname: str, kind: str) -> Symbol:
            symbol = Symbol(qualname.rsplit(".", 1)[-1], qualname, kind, rel, node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno)
            info.symbols.append(symbol)
            return symbol

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                define(node, node.name, "function")
                self._collect_calls(rel, node.name, node)
            elif isinstance(node, ast.ClassDef):
                define(node, node.name, "class")
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        define(child, f"{node.name}.{child.name}", "method")
                        self._collect_calls(rel, f"{node.name}.{child.name}", child)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        if target.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                            info.exports.extend(e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
                        elif target.id.isupper():
                            define(node, target.id, "constant")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    info.imports.append((node.lineno, self._resolve(rel, alias.name, 0), alias.name, ()))
            elif isinstance(node, ast.ImportFrom):
                names = tuple(alias.name for alias in node.names)
                raw = ("." * node.level) + (node.module or "")
                info.imports.append((node.lineno, self._resolve(rel, node.module, node.level), raw, names))
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                self.references[node.id].append((rel, node.lineno))
            elif isinstance(node, ast.Attribute):
                self.references[node.attr].append((rel, node.lineno))
        if rel.endswith("__init__.py") and not info.exports:
            info.exports = [n for _, internal, _, names in info.imports if internal for n in names if n != "*"]

    def _collect_calls(self, rel: str, qualname: str, node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name):
                    self.calls[(rel, qualname)].add(func.id)
                elif isinstance(func, ast.Attribute):
                    self.calls[(rel, qualname)].add(func.attr)

    # ------------------------------------------------------------------ helpers
    def definitions(self, name: str) -> list[Symbol]:
        simple = name.rsplit(".", 1)[-1]
        return [s for info in self.modules.values() for s in info.symbols if s.qualname == name or (s.name == simple and "." not in name)]

    def _enclosing(self, rel: str, line: int) -> str | None:
        best = None
        for symbol in self.modules.get(rel, ModuleInfo(rel, "")).symbols:
            if symbol.kind in ("function", "method") and symbol.line <= line <= symbol.end_line:
                if best is None or symbol.line >= best.line:
                    best = symbol
        return best.qualname if best else None

    def _usage_lines(self, name: str) -> list[tuple[str, int]]:
        simple = name.rsplit(".", 1)[-1]
        definition_lines = {(s.file, s.line) for s in self.definitions(name)}
        return sorted({ref for ref in self.references.get(simple, []) if ref not in definition_lines})

    def _line_text(self, rel: str, line: int) -> str:
        lines = self._lines.get(rel, [])
        return lines[line - 1].strip()[:100] if 0 < line <= len(lines) else ""

    def _target_file(self, target: str) -> str | None:
        target = target.strip().replace("\\", "/").removeprefix("./")
        if target in self.files:
            return target
        return self.module_to_file.get(target)

    # ------------------------------------------------------------------ tools
    def repo_outline(self) -> str:
        lines: list[str] = []
        current_dir = None
        for rel in self.files:
            directory, _, name = rel.rpartition("/")
            if directory != current_dir:
                lines.append(f"{directory}/" if directory else "./")
                current_dir = directory
            info = self.modules.get(rel)
            if info is None:
                lines.append(f"  {name}")
                continue
            parts = []
            if info.parse_error:
                parts.append("unparseable")
            functions = [s.name for s in info.symbols if s.kind == "function"]
            classes = [s.name for s in info.symbols if s.kind == "class"]
            constants = [s.name for s in info.symbols if s.kind == "constant"]
            internal_imports = sorted({internal for _, internal, _, _ in info.imports if internal})
            if functions:
                parts.append("functions: " + ", ".join(functions))
            if classes:
                parts.append("classes: " + ", ".join(classes))
            if constants:
                parts.append("constants: " + ", ".join(constants))
            if info.exports:
                parts.append("exports: " + ", ".join(info.exports))
            if internal_imports:
                parts.append("imports: " + ", ".join(internal_imports))
            lines.append(f"  {name}" + (f" — {'; '.join(parts)}" if parts else ""))
        return _truncate("\n".join(lines))

    def find_symbol(self, name: str) -> str:
        defs = self.definitions(name)
        if not defs:
            stem = name.rsplit("/", 1)[-1].removesuffix(".py")
            if stem != name and self.definitions(stem):
                places = ", ".join(f"{d.file}:{d.line}" for d in self.definitions(stem))
                return f"{name}: no such file. {stem} is defined in {places}."
            known = sorted({s.qualname for info in self.modules.values() for s in info.symbols})
            close = [k for k in known if name.lower() in k.lower() or k.lower() in name.lower()][:10]
            return f"{name}: not defined in this repository." + (f" Similar: {', '.join(close)}" if close else "")
        simple = name.rsplit(".", 1)[-1]
        exported = [info.file for info in self.modules.values() if simple in info.exports and all(d.file != info.file for d in defs)]
        import_lines = {(info.file, line) for info in self.modules.values() for line, _, _, names in info.imports if simple in names}
        usages = [ref for ref in self._usage_lines(name) if ref not in import_lines]
        out = [name, "DEFINED:"] + [f"  {d.file}:{d.line} ({d.kind} {d.qualname})" for d in defs]
        if exported:
            out += ["EXPORTED:"] + [f"  {f}" for f in exported]
        if import_lines:
            out += ["IMPORTED:"] + [f"  {f}:{l}" for f, l in sorted(import_lines)]
        out += ["REFERENCED:"] + ([f"  {f}:{l}" for f, l in usages] or ["  (no references)"])
        return _truncate("\n".join(out))

    def find_references(self, symbol: str) -> str:
        usages = self._usage_lines(symbol)
        if not usages:
            return f"{symbol}: no references found."
        out = [f"{symbol}: {len(usages)} reference(s)"]
        for rel, line in usages:
            where = self._enclosing(rel, line)
            out.append(f"  {rel}:{line}" + (f" in {where}" if where else "") + f"  {self._line_text(rel, line)}")
        return _truncate("\n".join(out))

    def find_tests(self, target: str) -> str:
        test_files = [rel for rel in self.modules if is_test_file(rel)]
        target_file = self._target_file(target)
        hits: dict[str, set[str]] = defaultdict(set)
        if target_file is not None:
            info = self.modules.get(target_file)
            names = {s.name for s in info.symbols} if info else set()
            package_exports = {f for f, i in self.modules.items() if f.endswith("__init__.py") and any(internal == target_file for _, internal, _, _ in i.imports)}
            for rel in test_files:
                for line, internal, _, imported in self.modules[rel].imports:
                    if internal == target_file or (internal in package_exports and names & set(imported)):
                        for ref_line in [line] + [l for n in names for f, l in self.references.get(n, []) if f == rel]:
                            hits[rel].add(self._enclosing(rel, ref_line) or "(module level)")
        else:
            simple = target.rsplit(".", 1)[-1]
            for rel, line in self.references.get(simple, []):
                if rel in test_files:
                    hits[rel].add(self._enclosing(rel, line) or "(module level)")
            for rel in test_files:
                for line, _, _, imported in self.modules[rel].imports:
                    if simple in imported:
                        hits[rel].add(self._enclosing(rel, line) or "(module level)")
        if not hits:
            return f"{target}: no tests found."
        out = [f"{target}: tests"]
        for rel in sorted(hits):
            tests = sorted(t for t in hits[rel] if t != "(module level)")
            out.append(f"  {rel}" + (f": {', '.join(tests)}" if tests else ""))
        return _truncate("\n".join(out))

    def dependency_cone(self, target: str, depth: int = 1) -> str:
        depth = max(1, min(int(depth), 3))
        target_file = self._target_file(target)
        if target_file is not None:
            imports_out = {f: sorted({internal for _, internal, _, _ in info.imports if internal}) for f, info in self.modules.items()}
            importers: dict[str, set[str]] = defaultdict(set)
            for f, deps in imports_out.items():
                for dep in deps:
                    importers[dep].add(f)
            out = [f"{target_file} (file)"]
            for label, graph in (("IMPORTS", imports_out), ("IMPORTED BY", importers)):
                seen, frontier, lines = {target_file}, [target_file], []
                for level in range(1, depth + 1):
                    nxt = []
                    for node in frontier:
                        for neighbor in sorted(graph.get(node, [])):
                            if neighbor not in seen:
                                seen.add(neighbor)
                                nxt.append(neighbor)
                                lines.append(f"  {'  ' * (level - 1)}{neighbor}")
                    frontier = nxt
                out += [f"{label}:"] + (lines or ["  (none)"])
            return _truncate("\n".join(out))
        defs = self.definitions(target)
        if not defs:
            return f"{target}: not a file or symbol in this repository. Call repo_outline to see what exists."
        internal_names = {s.name: s for info in self.modules.values() for s in info.symbols if s.kind in ("function", "method", "class")}
        out = [f"{target} (symbol)"]
        for d in defs:
            out.append(f"DEFINED: {d.file}:{d.line}")
            callees = sorted(n for n in self.calls.get((d.file, d.qualname), set()) if n in internal_names)
            out += ["CALLS:"] + ([f"  {n} ({internal_names[n].file}:{internal_names[n].line})" for n in callees] or ["  (none)"])
            callers = sorted({(f, q) for (f, q), names in self.calls.items() if d.name in names})
            out += ["CALLED BY:"] + ([f"  {q} ({f})" for f, q in callers] or ["  (none)"])
            used_in = sorted({f for f, _ in self._usage_lines(d.qualname) if f != d.file})
            if used_in:
                out += ["USED IN FILES:"] + [f"  {f}" for f in used_in]
        return _truncate("\n".join(out))


_CACHE: dict[str, tuple[tuple, RepositoryIndex]] = {}


def index_for(root: Path) -> RepositoryIndex:
    """Cached index, rebuilt when any file's size or mtime changes."""
    root = root.resolve()
    stamp = tuple(sorted(
        (str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file() and not any(part in _SKIP_DIRS for part in p.relative_to(root).parts)
    ))
    cached = _CACHE.get(str(root))
    if cached is None or cached[0] != stamp:
        cached = (stamp, RepositoryIndex(root))
        _CACHE[str(root)] = cached
    return cached[1]
