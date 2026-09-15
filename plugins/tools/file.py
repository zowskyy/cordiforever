from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.errors import ToolError, WorkspaceError
from core.plugin import Plugin
from core.diagnosis import evidence_line_span
from core.repo_index import index_for
from core.structured_edit import EditError, apply_json_patch, replace_exact, replace_python_symbol, serialize_like, set_json_pointer_value, validate_language

if TYPE_CHECKING:
    from core.context import Context


class FileTools(Plugin):
    name = "file_tools"

    # 3x deterministic templates — reuse via TEMPLATE: prefix, LLM sends short token, FileTools expands deterministically (pre-existing system)
    TEMPLATES: dict[str, str] = {
        "todo:index.html": '<!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head><body><div id="app"><h1>Todo</h1><input id="input" placeholder="todo"><button onclick="add()">Add</button><ul id="list"></ul></div><script src="app.js"></script></body></html>',
        "todo:app.js": 'let todos=[];function add(){let v=document.getElementById("input").value.trim();if(!v)return;todos.push(v);render();document.getElementById("input").value=""}function render(){let l=document.getElementById("list");l.innerHTML=todos.map((t,i)=>`<li>${t} <button onclick="todos.splice(${i},1);render()">x</button></li>`).join("")}',
        "todo:style.css": 'body{font-family:sans-serif;background:#f5f5f5}#app{max-width:500px;margin:40px auto;background:white;padding:20px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1)}#input{width:70%;padding:8px}button{padding:8px 12px;margin-left:4px}',
        "todo:crud.js": 'const store={items:[],add(t){this.items.push({id:Date.now(),text:t})},remove(id){this.items=this.items.filter(i=>i.id!==id)},list(){return this.items}};if(typeof module!=="undefined")module.exports=store;',
        "landing:index.html": '<!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head><body><header><h1>Landing</h1><p>Welcome</p><button>Get Started</button></header><script src="app.js"></script></body></html>',
        "landing:app.js": 'document.querySelector("button").addEventListener("click",()=>alert("started"))',
        "landing:style.css": 'header{text-align:center;padding:60px;background:#667eea;color:white}button{padding:12px 24px;border:none;border-radius:4px;background:white;color:#667eea}',
    }

    def __init__(self, workspace: str | Path, *, max_read_bytes: int = 2 * 1024 * 1024, max_write_bytes: int = 2 * 1024 * 1024) -> None:
        super().__init__()
        self.workspace = Path(workspace).expanduser().resolve()
        self.max_read_bytes = max_read_bytes
        self.max_write_bytes = max_write_bytes
        # Files protected from write/delete/rename at the tool boundary.
        # AGENTS.md is always protected (canonical instructions).
        # Additional files configurable via context config["protected_files"].
        self._protected_files: set[str] = {"AGENTS.md"}
        self._protected_paths: set[Path] = set()
        self._context: Context | None = None
        self.structured_edits = False
        self.repo_tools = False
        self.diagnose_before_mutation = False
        self.evidence_extraction = False
        self.localized_edits = False
        self.explicit_selector_kind = False

    def register(self, context: Any) -> None:
        super().register(context)
        self._context = context
        calibration = context.config.get("calibration") if context and context.config else None
        self.structured_edits = bool(isinstance(calibration, dict) and calibration.get("structured_edits"))
        self.repo_tools = bool(isinstance(calibration, dict) and calibration.get("repo_tools"))
        self.diagnose_before_mutation = bool(isinstance(calibration, dict) and calibration.get("diagnose_before_mutation"))
        self.evidence_extraction = bool(isinstance(calibration, dict) and calibration.get("evidence_extraction"))
        self.localized_edits = bool(isinstance(calibration, dict) and calibration.get("localized_edits"))
        self.explicit_selector_kind = bool(isinstance(calibration, dict) and calibration.get("explicit_selector_kind"))
        # Merge user-configured protected files
        extra = context.config.get("protected_files", []) if context and context.config else []
        if isinstance(extra, list):
            self._protected_files.update(extra)
        # Pre-resolve protected paths so _resolve can check efficiently
        for name in self._protected_files:
            try:
                resolved = (self.workspace / name).resolve()
                self._protected_paths.add(resolved)
            except (OSError, ValueError):
                pass

    def _emit_violation(self, path: str, operation: str) -> None:
        """Emit protected_file.violation event if EventBus is available."""
        if self._context is not None:
            self._context.events.emit("protected_file.violation", {
                "file": path,
                "operation": operation,
                "protected_files": sorted(self._protected_files),
            })

    def _check_protected(self, user_path: str, resolved: Path) -> None:
        """Raise ToolError if the resolved path matches a protected file."""
        # Check by resolved path match
        if resolved in self._protected_paths:
            self._emit_violation(user_path, "access")
            raise ToolError(f"Protected file cannot be modified: {user_path}")
        # Also check by name match (covers symlinks / parent escapes)
        name = Path(user_path.strip().replace("\\", "/")).name
        if name in self._protected_files:
            self._emit_violation(user_path, "access")
            raise ToolError(f"Protected file cannot be modified: {user_path}")

    def start(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)

    def health_check(self) -> dict[str, Any]:
        """Verify the tool layer integrity: workspace exists, protected files enforced."""
        return {
            "healthy": self.workspace.exists(),
            "protected_files_enforced": len(self._protected_files) > 0,
            "protected_count": len(self._protected_files),
        }

    def _resolve(self, user_path: str) -> Path:
        if not isinstance(user_path, str) or not user_path.strip():
            raise WorkspaceError("Path must be a non-empty string.")
        candidate = Path(user_path.strip().replace("\\", "/"))
        if candidate.is_absolute():
            raise WorkspaceError("Absolute paths are not allowed.")
        try:
            resolved = (self.workspace / candidate).resolve()
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise WorkspaceError(f"Path escapes workspace: {user_path!r}") from exc
        # Enforce protected files at the filesystem/tool boundary
        self._check_protected(user_path, resolved)
        return resolved

    def _missing(self, path: str) -> ToolError:
        if not any(c in path for c in "*?["):
            return ToolError(f"File does not exist: {path}")
        matches: list[str] = []
        try:
            for candidate in self.workspace.glob(path.strip().replace("\\", "/")):
                resolved = candidate.resolve()
                if resolved.is_file() and resolved.is_relative_to(self.workspace):
                    matches.append(resolved.relative_to(self.workspace).as_posix())
                if len(matches) >= 50:
                    break
        except (ValueError, OSError, NotImplementedError):
            matches = []
        matches.sort()
        found = f" Matching files: {', '.join(matches)}. Call the tool once per file." if matches else " No files match."
        return ToolError(f"File does not exist: {path}. Wildcards are not supported.{found}")

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise self._missing(path)
        size = target.stat().st_size
        if size > self.max_read_bytes:
            raise ToolError(f"File is too large ({size} bytes); limit is {self.max_read_bytes}.")
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"File is not valid UTF-8: {path}") from exc
        except OSError as exc:
            raise ToolError(f"Could not read {path}: {exc}") from exc

    def delete_file(self, path: str) -> str:
        """Delete a file from the workspace. Raises ToolError if not found."""
        target = self._resolve(path)
        if not target.exists():
            raise self._missing(path)
        try:
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                raise ToolError(f"Path is a directory, not a file: {path}")
        except OSError as exc:
            raise ToolError(f"Could not delete {path}: {exc}") from exc
        return f"Deleted {path}"

    def write_file(self, path: str, content: str) -> str:
        if not isinstance(content, str):
            raise ToolError("content must be a string.")
        # 3x: TEMPLATE: expansion — LLM sends short token (e.g., TEMPLATE:todo:index.html), FileTools expands deterministically
        if content.strip().startswith("TEMPLATE:"):
            key = content.strip()[9:].strip()  # after "TEMPLATE:"
            # support "todo:index.html" or "todo/app.js" -> normalize
            key = key.replace("/", ":").replace("\\", ":")
            expanded = self.TEMPLATES.get(key)
            if expanded is None:
                # fallback: try path-based lookup
                # e.g., write_file path=index.html with content TEMPLATE:todo -> map to todo:index.html
                alt = f"todo:{Path(path).name}"
                expanded = self.TEMPLATES.get(alt)
            if expanded is not None:
                content = expanded
            else:
                raise ToolError(f"Unknown template: {key!r}. Available: {', '.join(self.TEMPLATES)}")
        if len(content.encode("utf-8")) > self.max_write_bytes:
            raise ToolError("Content exceeds write size limit.")
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(content, encoding="utf-8", newline="")
        except OSError as exc:
            raise ToolError(f"Could not write {path}: {exc}") from exc
        return f"Wrote {len(content.encode('utf-8'))} bytes to {path}"

    def _commit_verified(self, path: str, target: Path, expected: str) -> None:
        """Atomically replace target with expected text, then prove the file now holds exactly that text."""
        if len(expected.encode("utf-8")) > self.max_write_bytes:
            raise ToolError("Content exceeds write size limit.")
        tmp = target.with_name(f".{target.name}.cordii-edit.tmp")
        try:
            tmp.write_text(expected, encoding="utf-8", newline="")
            os.replace(tmp, target)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise ToolError(f"Could not write {path}: {exc}") from exc
        if target.read_text(encoding="utf-8") != expected:
            raise ToolError(f"Postcondition failed: {path} does not contain the intended edit after writing.")

    def _read_existing_text(self, path: str) -> tuple[Path, str]:
        target = self._resolve(path)
        if not target.is_file():
            raise self._missing(path)
        return target, self.read_file(path)

    def replace_text(self, path: str, old: str, new: str) -> str:
        target, before = self._read_existing_text(path)
        after = replace_exact(before, old, new)
        validate_language(path, before, after)
        self._commit_verified(path, target, after)
        line = before[: before.index(old)].count("\n") + 1
        return f"Replaced 1 occurrence in {path} at line {line}: {old!r} -> {new!r}"

    SELECTOR_KINDS = {"python_symbol": ".py", "json_pointer": ".json"}

    def edit_symbol(self, path: str, target: str, replacement: str, selector_kind: str | None = None) -> str:
        """Gate qwen_localedit_v1: bounded edit of one Python symbol or one JSON pointer value in an existing file.
        Gate qwen_selectorkind_v1: with explicit_selector_kind, the declared kind must name the resolver for this file
        type; `target` is passed unchanged (no normalization, no inference)."""
        existing, before = self._read_existing_text(path)
        if self.explicit_selector_kind:
            if selector_kind not in self.SELECTOR_KINDS:
                raise EditError("selector_kind must be python_symbol or json_pointer.")
            if not path.lower().endswith(self.SELECTOR_KINDS[selector_kind]):
                raise EditError(f"selector_kind {selector_kind} does not apply to {path}.")
        if path.lower().endswith(".py"):
            after, span = replace_python_symbol(path, before, target, replacement)
            where = f"line {span[0]}" if span[0] == span[1] else f"lines {span[0]}-{span[1]}"
            summary = f"Replaced {target} ({where}) in {path}."
        elif path.lower().endswith(".json"):
            after, change = set_json_pointer_value(path, before, target, replacement)
            summary = f"Set {change} in {path}."
        else:
            raise EditError(f"{path}: edit supports only .py and .json files.")
        if after == before:
            raise EditError("replacement is identical to the current definition; nothing would change.")
        self._commit_verified(path, existing, after)
        return summary

    def patch_json(self, path: str, set_values: dict[str, Any] | None, remove: list[str] | None = None) -> str:
        target, before = self._read_existing_text(path)
        try:
            doc = json.loads(before)
        except json.JSONDecodeError as exc:
            raise EditError(f"{path} is not valid JSON ({exc.msg}); patch_json cannot edit it.") from exc
        new_doc, changes = apply_json_patch(doc, set_values, remove)
        after = serialize_like(before, new_doc)
        validate_language(path, before, after)
        self._commit_verified(path, target, after)
        if json.loads(target.read_text(encoding="utf-8")) != new_doc:
            raise ToolError(f"Postcondition failed: {path} does not parse to the patched document.")
        return f"Patched {path}: " + "; ".join(changes)

    def list_directory(self, path: str = ".") -> list[str]:
        target = self._resolve(path)
        if not target.is_dir():
            raise ToolError(f"Directory does not exist: {path}")
        try:
            return sorted(item.name for item in target.iterdir())
        except OSError as exc:
            raise ToolError(f"Could not list {path}: {exc}") from exc

    def read_json(self, path: str) -> Any:
        try:
            return json.loads(self.read_file(path))
        except json.JSONDecodeError as exc:
            raise ToolError(f"Invalid JSON in {path}: {exc}") from exc

    def search_files(self, pattern: str, path: str = ".") -> list[str]:
        """Find files in the workspace matching a glob pattern.

        Args:
            pattern: Glob pattern, e.g. ``*.py`` or ``**/*.json``.
            path: Workspace-relative directory to search from; defaults to ``.``.

        Returns:
            Sorted list of matching file paths relative to ``path`` using forward slashes.
        """
        target = self._resolve(path)
        if not target.is_dir():
            raise ToolError(f"Directory does not exist: {path}")
        try:
            return sorted(str(p.relative_to(target)).replace("\\", "/") for p in target.rglob(pattern) if p.is_file())
        except OSError as exc:
            raise ToolError(f"Could not search {path}: {exc}") from exc

    def schemas(self) -> list[dict[str, Any]]:
        structured = [
            {"type": "function", "function": {"name": "replace_text", "description": "Replace text that occurs exactly once in an existing file.", "parameters": {"type": "object", "required": ["path", "old", "new"], "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}, "old": {"type": "string", "description": "Exact existing text; must occur exactly once."}, "new": {"type": "string", "description": "Replacement text."}}}}},
            {"type": "function", "function": {"name": "patch_json", "description": "Change values inside an existing JSON file without rewriting it.", "parameters": {"type": "object", "required": ["path", "set"], "properties": {"path": {"type": "string", "description": "Workspace-relative JSON file path."}, "set": {"type": "object", "description": "Map of JSON Pointer (e.g. /port) to new value."}, "remove": {"type": "array", "items": {"type": "string"}, "description": "JSON Pointers to remove."}}}}},
        ] if self.structured_edits else []
        repository = [
            {"type": "function", "function": {"name": "repo_outline", "description": "Map of files with their functions, classes, exports and internal imports.", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "find_symbol", "description": "Where a function, class or constant is defined, exported, imported and referenced.", "parameters": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "description": "Symbol name, e.g. subtract or Item.value."}}}}},
            {"type": "function", "function": {"name": "find_references", "description": "Every line that uses a name, with its enclosing function.", "parameters": {"type": "object", "required": ["symbol"], "properties": {"symbol": {"type": "string", "description": "Symbol name."}}}}},
            {"type": "function", "function": {"name": "find_tests", "description": "Tests that exercise a symbol or a file.", "parameters": {"type": "object", "required": ["target"], "properties": {"target": {"type": "string", "description": "Symbol name or workspace-relative file path."}}}}},
            {"type": "function", "function": {"name": "dependency_cone", "description": "What a file imports and what imports it, or what a function calls and what calls it.", "parameters": {"type": "object", "required": ["target"], "properties": {"target": {"type": "string", "description": "Symbol name or workspace-relative file path."}, "depth": {"type": "integer", "description": "1 to 3; default 1."}}}}},
        ] if self.repo_tools else []
        diagnosis = [
            {"type": "function", "function": {"name": "diagnose", "description": "Before changing an existing file: quote the exact text that shows the problem, the cause, and the intended change.", "parameters": {"type": "object", "required": ["path", "evidence", "cause", "change"], "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}, "evidence": {"type": "string", "description": "Exact text copied from the file."}, "cause": {"type": "string", "description": "Why it is wrong."}, "change": {"type": "string", "description": "What will be changed."}}}}},
        ] if self.diagnose_before_mutation else []
        if diagnosis and self.evidence_extraction:
            # Gate qwen_extract_v1: the loop resolves `target` against its read snapshot (FileTools.diagnose is not used).
            diagnosis = [{"type": "function", "function": {"name": "diagnose", "description": "Before changing an existing file you read: name where the problem is, the cause, and the intended change.", "parameters": {"type": "object", "required": ["path", "target", "cause", "change"], "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}, "target": {"type": "string", "description": "Function/class/method name (.py) or JSON pointer (.json)."}, "cause": {"type": "string", "description": "Why it is wrong."}, "change": {"type": "string", "description": "What will be changed."}}}}}]
        localized = [
            {"type": "function", "function": {"name": "edit_symbol", "description": "Change one Python function/class/method/assignment, or one JSON value, in an existing file.", "parameters": {"type": "object", "required": ["path", "target", "replacement"], "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}, "target": {"type": "string", "description": "Function/class/method name (.py) or JSON pointer (.json)."}, "replacement": {"type": "string", "description": "New source of that definition (.py) or new JSON value (.json)."}}}}},
        ] if self.localized_edits else []
        if localized and self.explicit_selector_kind:
            localized[0]["function"]["parameters"]["required"] = ["path", "selector_kind", "target", "replacement"]
            localized[0]["function"]["parameters"]["properties"]["selector_kind"] = {"type": "string", "enum": ["python_symbol", "json_pointer"], "description": "python_symbol for .py files, json_pointer for .json files."}
        return structured + repository + diagnosis + localized + [
            {"type": "function", "function": {"name": "read_file", "description": "Read a UTF-8 text file inside the workspace.", "parameters": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}}}}},
            {"type": "function", "function": {"name": "write_file", "description": "Write UTF-8 text to a workspace-relative file.", "parameters": {"type": "object", "required": ["path", "content"], "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}, "content": {"type": "string", "description": "Complete UTF-8 file contents."}}}}},
            {"type": "function", "function": {"name": "delete_file", "description": "Delete a file from the workspace.", "parameters": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}}}}},
            {"type": "function", "function": {"name": "list_directory", "description": "List entries in a workspace-relative directory.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Workspace-relative directory path; defaults to '.'."}}}}},
            {"type": "function", "function": {"name": "read_json", "description": "Read and parse a JSON file inside the workspace.", "parameters": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string", "description": "Workspace-relative JSON file path."}}}}},
            {"type": "function", "function": {"name": "search_files", "description": "Find files in the workspace matching a glob pattern.", "parameters": {"type": "object", "required": ["pattern"], "properties": {"pattern": {"type": "string", "description": "Glob pattern, e.g. *.py or **/*.json."}, "path": {"type": "string", "description": "Workspace-relative directory to search from; defaults to '.'."}}}}},
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if not isinstance(arguments, dict):
            raise ToolError("Tool arguments must be a JSON object.")
        if name == "read_file":
            return self.read_file(str(arguments["path"]))
        if name == "write_file":
            return self.write_file(str(arguments["path"]), str(arguments["content"]))
        if name == "delete_file":
            return self.delete_file(str(arguments["path"]))
        if name == "list_directory":
            return json.dumps(self.list_directory(str(arguments.get("path", "."))))
        if name == "read_json":
            return json.dumps(self.read_json(str(arguments["path"])), ensure_ascii=False, indent=2)
        if name == "search_files":
            return json.dumps(self.search_files(str(arguments["pattern"]), str(arguments.get("path", "."))))
        if name == "replace_text" and self.structured_edits:
            return self.replace_text(str(arguments["path"]), arguments.get("old"), arguments.get("new"))
        if name == "patch_json" and self.structured_edits:
            return self.patch_json(str(arguments["path"]), arguments.get("set"), arguments.get("remove"))
        if self.repo_tools and name in ("repo_outline", "find_symbol", "find_references", "find_tests", "dependency_cone"):
            index = index_for(self.workspace)
            if name == "repo_outline":
                return index.repo_outline()
            if name == "find_symbol":
                return index.find_symbol(str(arguments["name"]))
            if name == "find_references":
                return index.find_references(str(arguments["symbol"]))
            if name == "find_tests":
                return index.find_tests(str(arguments["target"]))
            try:
                depth = int(arguments.get("depth", 1))
            except (TypeError, ValueError) as exc:
                raise ToolError("depth must be an integer from 1 to 3.") from exc
            return index.dependency_cone(str(arguments["target"]), depth)
        if name == "edit_symbol" and self.localized_edits:
            kind = arguments.get("selector_kind")
            return self.edit_symbol(str(arguments.get("path", "")), str(arguments.get("target", "")), str(arguments.get("replacement", "")),
                                    selector_kind=str(kind) if kind is not None else None)
        if name == "diagnose" and self.diagnose_before_mutation:
            return self.diagnose(str(arguments.get("path", "")), str(arguments.get("evidence", "")),
                                 str(arguments.get("cause", "")), str(arguments.get("change", "")))
        raise ToolError(f"Unknown file tool: {name}")

    def diagnose(self, path: str, evidence: str, cause: str, change: str) -> str:
        """Record a diagnosis. Valid only if the evidence is quoted from the file's current contents."""
        target = self._resolve(path)
        if not target.is_file():
            raise self._missing(path)
        if not cause.strip() or not change.strip():
            raise ToolError("diagnose needs a cause and a change.")
        span = evidence_line_span(self.read_file(path), evidence)
        if span is None:
            raise ToolError(f"The evidence is not text from {path}. Copy the exact lines from {path} that show the problem.")
        lines = f"line {span[0]}" if span[0] == span[1] else f"lines {span[0]}-{span[1]}"
        return f"Diagnosis recorded for {path} ({lines}). Cause: {cause.strip()} Change: {change.strip()}"
