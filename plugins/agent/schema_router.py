from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.plugin import Plugin


@dataclass
class LogicalTool:
    """A compact logical tool visible to the model."""
    name: str
    description: str
    args_schema: Dict[str, Any] = field(default_factory=dict)


class SchemaRouter(Plugin):
    """
    Compact-schema router for small models (qwen2.5-coder:1.5b).

    When enabled and compact_schema is True:
    - The model sees a single ``call_tool(tool, args)`` function instead of
      verbose per-tool JSON schemas, saving hundreds of prompt tokens per round.
    - Logical calls (``read``, ``write``, ``list``, ``done``) are expanded
      into real tool calls before execution.
    - Tool results are compressed (truncated) before being added to context.

    When disabled:
    - ``get_model_tools()`` returns ``[]`` (the loop falls through to the
      normal registry schemas).
    - ``expand_call()`` returns ``None`` (no expansion).
    - ``compress_result()`` returns the input unchanged.

    Deterministic and zero-token by design: no model calls, no network.
    """

    name = "schema_router"
    dependencies: tuple[str, ...] = ()
    __contract__: dict[str, Any] = {
        "requires": ("schema_router_enabled", "compact_schema"),
        "provides": ("compact_schema", "expand_call", "compress_result", "get_model_tools"),
        "deterministic": True,
        "zero_token": True,
    }

    # ---- Logical tools the model can see in compact mode ----

    LOGICAL_TOOLS: List[LogicalTool] = [
        LogicalTool(
            name="read",
            description="Read a file from the workspace.",
            args_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        LogicalTool(
            name="write",
            description="Write content to a file.",
            args_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        ),
        LogicalTool(
            name="list",
            description="List files in a directory.",
            args_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative directory path; default '.'"},
                },
                "required": [],
                "additionalProperties": False,
            },
        ),
        LogicalTool(
            name="delete",
            description="Delete a file from the workspace.",
            args_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        LogicalTool(
            name="done",
            description="Signal that the task is complete; respond with text only.",
            args_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
    ]

    # ---- Expansion rules: logical_name -> (real_tool, arg_map, default_args) ----
    # arg_map: logical_arg_name -> real_arg_name
    # default_args: real arg_name -> default value (used when logical args omit it)

    # Exposed only when calibration enables structured_edits (existing files are edited, never rewritten).
    STRUCTURED_TOOLS: List[LogicalTool] = [
        LogicalTool(
            name="replace",
            description="Replace text that occurs exactly once in an existing file.",
            args_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
                "additionalProperties": False,
            },
        ),
        LogicalTool(
            name="patch_json",
            description="Change values inside an existing JSON file.",
            args_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "set": {"type": "object"},
                    "remove": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path", "set"],
                "additionalProperties": False,
            },
        ),
    ]

    # Exposed only when calibration enables repo_tools: deterministic repository navigation (read-only).
    REPO_TOOLS: List[LogicalTool] = [
        LogicalTool(name="repo_outline", description="Map of files, functions, classes and imports.",
                    args_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False}),
        LogicalTool(name="find_symbol", description="Where a symbol is defined, exported and used.",
                    args_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}),
        LogicalTool(name="find_references", description="Every line that uses a name.",
                    args_schema={"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"], "additionalProperties": False}),
        LogicalTool(name="find_tests", description="Tests for a symbol or file.",
                    args_schema={"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"], "additionalProperties": False}),
        LogicalTool(name="dependency_cone", description="Imports/importers of a file or callers/callees of a function.",
                    args_schema={"type": "object", "properties": {"target": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["target"], "additionalProperties": False}),
    ]
    REPO_TOOL_NAMES = frozenset(t.name for t in REPO_TOOLS)

    # Exposed only when calibration enables diagnose_before_mutation.
    DIAGNOSE_TOOL = LogicalTool(
        name="diagnose",
        description="State the evidence, cause and intended change before changing an existing file.",
        args_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "evidence": {"type": "string"}, "cause": {"type": "string"}, "change": {"type": "string"}},
            "required": ["path", "evidence", "cause", "change"],
            "additionalProperties": False,
        },
    )
    # Gate qwen_extract_v1: the model names a target; deterministic code extracts the evidence from its read snapshot.
    DIAGNOSE_TARGET_TOOL = LogicalTool(
        name="diagnose",
        description="Name the defect's location (Python symbol or JSON pointer) in a file you read, the cause and the intended change.",
        args_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "target": {"type": "string"}, "cause": {"type": "string"}, "change": {"type": "string"}},
            "required": ["path", "target", "cause", "change"],
            "additionalProperties": False,
        },
    )

    # Gate qwen_localedit_v1: bounded edit of one Python definition or one JSON pointer value.
    EDIT_TOOL = LogicalTool(
        name="edit",
        description="Change one function/class/method/assignment (.py) or one JSON value (.json) in an existing file.",
        args_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "target": {"type": "string"}, "replacement": {"type": "string"}},
            "required": ["path", "target", "replacement"],
            "additionalProperties": False,
        },
    )

    # Gate qwen_selectorkind_v1: the same edit, with the selector's type stated explicitly.
    EDIT_KIND_TOOL = LogicalTool(
        name="edit",
        description="Change one function/class/method/assignment (.py, python_symbol) or one JSON value (.json, json_pointer) in an existing file.",
        args_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "selector_kind": {"type": "string", "enum": ["python_symbol", "json_pointer"]},
                           "target": {"type": "string"}, "replacement": {"type": "string"}},
            "required": ["path", "selector_kind", "target", "replacement"],
            "additionalProperties": False,
        },
    )

    EXPANSIONS: Dict[str, Dict[str, Any]] = {
        "edit":   {"real_tool": "edit_symbol", "arg_map": {"path": "path", "selector_kind": "selector_kind", "target": "target", "replacement": "replacement"}, "defaults": {}},
        "repo_outline":    {"real_tool": "repo_outline",    "arg_map": {}, "defaults": {}},
        "find_symbol":     {"real_tool": "find_symbol",     "arg_map": {"name": "name"}, "defaults": {}},
        "find_references": {"real_tool": "find_references", "arg_map": {"symbol": "symbol"}, "defaults": {}},
        "find_tests":      {"real_tool": "find_tests",      "arg_map": {"target": "target"}, "defaults": {}},
        "dependency_cone": {"real_tool": "dependency_cone", "arg_map": {"target": "target", "depth": "depth"}, "defaults": {"depth": 1}},
        "replace":    {"real_tool": "replace_text", "arg_map": {"path": "path", "old": "old", "new": "new"}, "defaults": {}},
        "patch_json": {"real_tool": "patch_json",   "arg_map": {"path": "path", "set": "set", "remove": "remove"}, "defaults": {}},
        "read":   {"real_tool": "read_file",      "arg_map": {"path": "path"}, "defaults": {}},
        "write":  {"real_tool": "write_file",     "arg_map": {"path": "path", "content": "content"}, "defaults": {}},
        "list":   {"real_tool": "list_directory", "arg_map": {"path": "path"}, "defaults": {"path": "."}},
        "delete": {"real_tool": "delete_file",    "arg_map": {"path": "path"}, "defaults": {}},
        "done":   {"real_tool": None,             "arg_map": {}, "defaults": {}},
        "diagnose": {"real_tool": "diagnose", "arg_map": {"path": "path", "evidence": "evidence", "target": "target", "cause": "cause", "change": "change"}, "defaults": {}},
    }

    # Size threshold for result compression
    _PREVIEW_LIMIT = 200

    def __init__(self, context: Optional[Any] = None) -> None:
        super().__init__()
        self.context = context
        self.enabled = False
        self.compact_mode = False
        self.structured_edits = False
        self.repo_tools = False
        self.navigation_only = False
        self.full_read_views = False
        self.diagnose_before_mutation = False
        self.evidence_extraction = False
        self.localized_edits = False
        self.explicit_selector_kind = False

    def register(self, context: Any) -> None:
        super().register(context)
        cfg = context.config if context is not None else {}
        self.enabled = bool(cfg.get("schema_router_enabled", False))
        self.compact_mode = bool(cfg.get("compact_schema", False))
        calibration = cfg.get("calibration")
        self.structured_edits = bool(isinstance(calibration, dict) and calibration.get("structured_edits"))
        self.repo_tools = bool(isinstance(calibration, dict) and calibration.get("repo_tools"))
        self.navigation_only = bool(isinstance(calibration, dict) and calibration.get("navigation_only"))
        self.full_read_views = bool(isinstance(calibration, dict) and calibration.get("full_read_views"))
        self.diagnose_before_mutation = bool(isinstance(calibration, dict) and calibration.get("diagnose_before_mutation"))
        self.evidence_extraction = bool(isinstance(calibration, dict) and calibration.get("evidence_extraction"))
        self.localized_edits = bool(isinstance(calibration, dict) and calibration.get("localized_edits"))
        self.explicit_selector_kind = bool(isinstance(calibration, dict) and calibration.get("explicit_selector_kind"))

    NAVIGATION_LOGICAL = frozenset({"read", "list", "done"})

    def active_logical_tools(self) -> List[LogicalTool]:
        base = [t for t in self.LOGICAL_TOOLS if t.name != "done"]
        done = [t for t in self.LOGICAL_TOOLS if t.name == "done"]
        tools = (base + (list(self.STRUCTURED_TOOLS) if self.structured_edits else [])
                 + (list(self.REPO_TOOLS) if self.repo_tools else [])
                 + ([self.DIAGNOSE_TARGET_TOOL if self.evidence_extraction else self.DIAGNOSE_TOOL] if self.diagnose_before_mutation else [])
                 + ([self.EDIT_KIND_TOOL if self.explicit_selector_kind else self.EDIT_TOOL] if self.localized_edits else []) + done)
        if self.navigation_only:
            # The constrained decoder cannot even emit a mutating action.
            tools = [t for t in tools if t.name in self.NAVIGATION_LOGICAL or t.name in self.REPO_TOOL_NAMES]
        return tools

    def start(self) -> None:
        # Config is read in register() so context.config is already available.
        # No-op start; the router is a pure transformation layer.
        pass

    def health_check(self) -> dict[str, Any]:
        """Verify the router has all required capability methods."""
        return {
            "healthy": self.enabled,
            "enabled": self.enabled,
            "compact_mode": self.compact_mode,
            "has_get_model_tools": hasattr(self, "get_model_tools"),
            "has_expand_call": hasattr(self, "expand_call"),
            "has_compress_result": hasattr(self, "compress_result"),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_model_tools(self) -> List[Dict[str, Any]]:
        """
        Return the tool schemas the model should see.

        If compact mode is enabled, returns a single ``call_tool`` function
        schema. Otherwise returns ``[]`` (loop falls through to registry schemas).
        """
        if not (self.enabled and self.compact_mode):
            return []

        logical_names = [t.name for t in self.active_logical_tools()]
        description = (
            "call_tool(tool, args). tool ∈ {"
            + ", ".join(logical_names)
            + "}. Format: {\"tool\": \"<name>\", \"args\": {...}}"
        )

        return [
            {
                "type": "function",
                "function": {
                    "name": "call_tool",
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tool": {
                                "type": "string",
                                "enum": logical_names,
                                "description": "Logical tool name",
                            },
                            "args": {
                                "type": "object",
                                "description": "Tool arguments as a JSON object",
                            },
                        },
                        "required": ["tool", "args"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

    def get_response_format(self) -> Optional[Dict[str, Any]]:
        """JSON schema for constrained decoding of a bare {"tool", "args"} action (compact mode only)."""
        if not (self.enabled and self.compact_mode):
            return None
        # One branch per tool so the decoder cannot emit a call with missing or foreign arguments.
        branches: List[Dict[str, Any]] = []
        for tool in self.active_logical_tools():
            properties = {k: {kk: vv for kk, vv in v.items() if kk != "description"} for k, v in tool.args_schema.get("properties", {}).items()}
            required = list(tool.args_schema.get("required", []))
            if tool.name == "done":
                properties = {"summary": {"type": "string"}}
                required = ["summary"]
            branches.append({
                "type": "object",
                "properties": {
                    "tool": {"const": tool.name},
                    "args": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
                },
                "required": ["tool", "args"],
                "additionalProperties": False,
            })
        return {"anyOf": branches}

    def done_summary(self, calls: List[Dict[str, Any]]) -> Optional[str]:
        """Return the summary text of a compact ``done`` call, or None if no call is ``done``."""
        if not self.enabled:
            return None
        for call in calls:
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            if not isinstance(fn, dict) or fn.get("name") != "call_tool":
                continue
            raw_args = fn.get("arguments")
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(raw_args, dict) and raw_args.get("tool") == "done":
                logical_args = raw_args.get("args")
                summary = logical_args.get("summary") if isinstance(logical_args, dict) else None
                return summary if isinstance(summary, str) else ""
        return None

    def expand_call(
        self, call: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Expand a compact-schema tool call (call_tool) into a real tool call.

        Accepts a full OpenAI-format tool call dict as the model emits it:

            {"id": "call_xxx", "type": "function",
             "function": {"name": "call_tool",
                          "arguments": {"tool": "read", "args": {"path": "a.txt"}}}}

        Arguments may come as a dict or a JSON string (both accepted by the
        model depending on the client).

        Returns the expanded call in the same outer format, with the real tool
        name and arguments::

            {"id": "call_xxx", "type": "function",
             "function": {"name": "read_file",
                          "arguments": {"path": "a.txt"}}}

        Returns ``None`` for ``done`` calls (sentinel, no real tool to execute,
        caller should drop the call) and for any non-``call_tool`` call when the
        router is disabled.

        Non-``call_tool`` calls (real tool names) pass through unchanged so
        this method is safe to call on mixed lists of compact and verbose
        calls.
        """
        if not self.enabled:
            return None

        fn = call.get("function", {})
        if not isinstance(fn, dict):
            return None

        name = fn.get("name", "")

        # Passthrough: only expand compact-schema calls
        if name != "call_tool":
            return call

        # Parse arguments (may be a dict or JSON string)
        raw_args = fn.get("arguments")
        if raw_args is None:
            return None
        if isinstance(raw_args, str):
            try:
                raw_args = json.loads(raw_args)
            except (json.JSONDecodeError, TypeError):
                return None
        if not isinstance(raw_args, dict):
            return None

        logical_name = raw_args.get("tool")
        logical_args = raw_args.get("args", {})

        rule = self.EXPANSIONS.get(logical_name)
        if rule is None:
            return None

        real_tool = rule["real_tool"]
        if real_tool is None:
            # "done" — signals completion, no tool execution
            return None

        arg_map = rule["arg_map"]
        defaults = rule["defaults"]

        real_args: Dict[str, Any] = {}
        for logical_arg, real_arg in arg_map.items():
            if logical_arg in logical_args:
                real_args[real_arg] = logical_args[logical_arg]

        # Apply defaults for missing args
        for real_arg, default_val in defaults.items():
            if real_arg not in real_args:
                real_args[real_arg] = default_val

        return {
            "id": call.get("id") or f"call_{logical_name}",
            "type": "function",
            "function": {
                "name": real_tool,
                "arguments": real_args,
            },
        }

    def compress_tool_output(self, tool_name: str, result: Any) -> Any:
        """Compact a tool result for the model. File contents are data: they are only length-truncated, never
        parsed and rewritten (dict compression would rename keys or add a fabricated "status" to a JSON file)."""
        if not self.compact_mode:
            return result
        if tool_name in self.REPO_TOOL_NAMES:
            return result  # already structured and size-bounded by the repository index
        if tool_name == "read_file" and isinstance(result, str):
            if self.full_read_views:
                return result  # experimental control: reads are delivered whole (still bounded by max_tool_result_bytes)
            return result[: self._PREVIEW_LIMIT] + "..." if len(result) > self._PREVIEW_LIMIT else result
        if tool_name == "diagnose" and isinstance(result, str):
            return result
        return self.compress_result(result)

    def compress_result(self, result: Any) -> Any:
        """
        Compress a tool result for the model's context window.

        Tool results arrive as strings (raw content from read_file, or JSON
        from list_directory / error dicts). This method:

        - Parses JSON strings and compresses dict fields (truncate ``content``,
          shorten ``error`` to first line).
        - For non-JSON long strings (e.g., large file reads), truncates to a
          preview.
        - Returns the input unchanged when compact_mode is off.
        """
        if not self.compact_mode:
            return result

        # Non-dict results (plain strings) — try JSON, then plain truncation.
        if not isinstance(result, dict):
            if isinstance(result, str):
                # Try parsing as JSON first
                try:
                    parsed = json.loads(result)
                except (json.JSONDecodeError, TypeError):
                    parsed = None

                if isinstance(parsed, dict):
                    compressed = self._compress_dict(parsed)
                    return json.dumps(compressed, ensure_ascii=False)
                elif isinstance(parsed, list):
                    # list_directory results are already compact (just filenames)
                    return result

                # Not JSON — treat as raw text (e.g., read_file output)
                if len(result) > self._PREVIEW_LIMIT:
                    return result[: self._PREVIEW_LIMIT] + "..."
                return result
            return result

        # Already a dict — compress fields directly
        return self._compress_dict(result)

    def _compress_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compress a dict result: truncate content, shorten errors."""
        compressed: Dict[str, Any] = {}
        for key, value in data.items():
            if key == "content" and isinstance(value, str) and len(value) > self._PREVIEW_LIMIT:
                compressed["content_preview"] = value[: self._PREVIEW_LIMIT] + "..."
            elif key == "error" and isinstance(value, str):
                compressed["error"] = value.splitlines()[0] if value else value
            else:
                compressed[key] = value
        if "status" not in compressed:
            compressed["status"] = data.get("status", "unknown")
        return compressed

    def get_logical_tools_description(self) -> str:
        """Short textual description of logical tools (for system prompt if needed)."""
        lines = ["Available tools:"]
        for t in self.LOGICAL_TOOLS:
            args = sorted(t.args_schema.get("properties", {}).keys())
            lines.append(f"- {t.name}({', '.join(args)})")
        return "\n".join(lines)
