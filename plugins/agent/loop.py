from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from core.context import Context
from core.calibration import MODEL_PRESETS, DEFAULT_PRESET_KEY, calibration_from_context
from core.context_pruner import ContextPruner, PrunedContext
from core.diagnosis import target_line_span
from core.errors import PolicyRejection, ToolError
from core.outcomes import EscalationOutcome, EscalationRequired
from core.grounding import targeted_grounding
from core.path_candidates import classify_path, declared_paths, ground_request, named_existing_files, normalize
from core.repo_index import index_for
from core.events import Manifest, SYSTEM_MESSAGE, USER_MESSAGE, TOOL_CALL_START, TOOL_CALL_END
from core.failure_taxonomy import FailureClassifier, FailureType, PreFlightGuard
from core.messages import Message
from core.plugin import Plugin
from core.retry import RetryPolicy, retry_with_backoff
from core.reality import RealityProjector, RequestEnvelope
from core.self_healing import BudgetedSelfHealing
from core.summarizer import Summarizer
from plugins.agent.routers import try_datetime_router, try_math_router, try_units_router
from plugins.agent.semantic_router import SemanticRouter
from plugins.agent.specialized_routers import RepairMessageBuilder, SpecializedRouters, ToolResultVerifier
from plugins.agent.aggregate_response import AggregateResponse
from plugins.agent.multi_domain_router import MultiDomainRouter
from plugins.agent.schema_router import SchemaRouter
from plugins.core.decision_logger import DecisionLogger

# Back-compat alias (tests import it). The VALUE comes from the shared model
# calibration table (core.context.MODEL_PRESETS), not a literal here: the
# invariant layer carries no model-specific numbers. 1.5b default = 30000
# budget leaving ~2768 headroom for the 32768 window (Modelfile num_ctx 32768).
TOKEN_BUDGET = MODEL_PRESETS[DEFAULT_PRESET_KEY]["pruner_budget"]

_FILE_STATE_TOOLS = ("read_file", "write_file", "delete_file", "replace_text", "patch_json", "edit_symbol")
_MUTATING_TOOLS = ("write_file", "delete_file", "replace_text", "patch_json", "edit_symbol")
_EVIDENCE_OUTPUT_TOOLS = frozenset({"search_files", "repo_outline", "find_symbol", "find_references", "find_tests", "dependency_cone"})
_NAVIGATION_TOOLS = frozenset({"read_file", "list_directory", "read_json", "search_files",
                               "repo_outline", "find_symbol", "find_references", "find_tests", "dependency_cone"})

# Scored with benchmark/tool_call_eval.py; re-run it before changing this text.
LITE_COMPACT_GUIDANCE = (
    "You are a coding agent working inside a real project folder. You CAN read and change files, but only by calling tools. "
    "Never say you cannot access files. Never invent file contents.\n\n"
    "To act, reply with exactly one JSON object and nothing else:\n"
    "{\"tool\": \"<name>\", \"args\": {...}}\n\n"
    "Tools:\n"
    "- read: {\"path\": \"file\"} - show a file's contents\n"
    "- write: {\"path\": \"file\", \"content\": \"full file text\"} - create or overwrite a file\n"
    "- list: {\"path\": \"dir\"} - list a folder (\".\" is the project root)\n"
    "- delete: {\"path\": \"file\"} - delete a file\n"
    "Rules: to change an existing file, read it first. Use list for folders, read for files.\n"
    "When the task is finished, reply {\"tool\": \"done\", \"args\": {\"summary\": \"what you did\"}}.\n"
    "Only if the user asks for a todo app: write content \"TEMPLATE:todo\" to index.html.\n\n"
    "Examples:\n"
    "User: Open notes.md\n"
    "{\"tool\": \"read\", \"args\": {\"path\": \"notes.md\"}}\n"
    "User: Make a file a.txt that says hi\n"
    "{\"tool\": \"write\", \"args\": {\"path\": \"a.txt\", \"content\": \"hi\"}}\n"
    "User: Fix the typo in index.html\n"
    "{\"tool\": \"read\", \"args\": {\"path\": \"index.html\"}}"
)

# Appended when calibration enables repo_tools. Observed failure it targets: models inventing file names
# (median.py, data.csv, subtract.js) instead of locating the real code.
REPO_TOOLS_GUIDANCE = (
    "\n\nRepository tools (they only look; use them to find where things are). "
    "Replace <...> with the real name or path from the user's request:\n"
    "- repo_outline: {} - map of all files with their functions, classes and imports\n"
    "- find_symbol: {\"name\": \"<function or class name>\"} - where it is defined, exported and used\n"
    "- find_references: {\"symbol\": \"<function or class name>\"} - every line that uses it\n"
    "- find_tests: {\"target\": \"<function name or file path>\"} - tests for it\n"
    "- dependency_cone: {\"target\": \"<file path or function name>\", \"depth\": 1} - what it imports or calls, and what uses it\n"
    "Never guess a file name. If you do not know the exact path, call repo_outline or find_symbol first."
)

# Appended when calibration enables diagnose_before_mutation (gate benchmark/gates/diagnose_v1.md; frozen for that run).
DIAGNOSE_GUIDANCE = (
    "\n\nBefore changing an existing file, first send diagnose. Replace <...> with real text:\n"
    "- diagnose: {\"path\": \"<file>\", \"evidence\": \"<exact lines copied from the file that show the problem>\", "
    "\"cause\": \"<why it is wrong>\", \"change\": \"<what you will change>\"}\n"
    "Then make the change."
)

# Gate qwen_localedit_v1 treatment: the write line says it only creates files, and one edit line is appended.
LITE_WRITE_LINE = "- write: {\"path\": \"file\", \"content\": \"full file text\"} - create or overwrite a file\n"
LOCALIZED_WRITE_LINE = "- write: {\"path\": \"file\", \"content\": \"full file text\"} - create a NEW file\n"
LOCALIZED_EDIT_GUIDANCE = (
    "\n- edit: {\"path\": \"<file>\", \"target\": \"<function or class name in a .py file, or JSON pointer such as /key in a .json file>\", "
    "\"replacement\": \"<the new code of that function or class, or the new JSON value>\"} - change one part of an existing file"
)
# Gate qwen_selectorkind_v1 treatment: the single edit line becomes one line per selector kind (placeholders only).
SELECTOR_KIND_EDIT_GUIDANCE = (
    "\n- edit: {\"path\": \"<file.py>\", \"selector_kind\": \"python_symbol\", \"target\": \"<function or class name>\", "
    "\"replacement\": \"<new code of that function or class>\"} - change one function or class in a .py file"
    "\n- edit: {\"path\": \"<file.json>\", \"selector_kind\": \"json_pointer\", \"target\": \"</key/subkey>\", "
    "\"replacement\": \"<new JSON value>\"} - change one value in a .json file"
)
# Gate qwen_formatcontract_v1 treatment: the two replacement placeholders above become exact type-specific format
# contracts (text only; no examples, no validation, no repair).
REPLACEMENT_PLACEHOLDER_PY = "\"replacement\": \"<new code of that function or class>\""
REPLACEMENT_PLACEHOLDER_JSON = "\"replacement\": \"<new JSON value>\""
REPLACEMENT_CONTRACT_PY = (
    "\"replacement\": \"<the complete new definition of only that function, method, class or assignment, starting with def, "
    "async def, class, or the assignment name; no other definitions, no whole file, no Markdown code fences, no explanation>\""
)
REPLACEMENT_CONTRACT_JSON = (
    "\"replacement\": \"<one valid JSON value of the same kind as the current value at target: a quoted \\\"string\\\", "
    "a number, true, false, null, a [list] or an {object}>\""
)
assert SELECTOR_KIND_EDIT_GUIDANCE.count(REPLACEMENT_PLACEHOLDER_PY) == 1 and SELECTOR_KIND_EDIT_GUIDANCE.count(REPLACEMENT_PLACEHOLDER_JSON) == 1

# Gate qwen_extract_v1 treatment: identical to DIAGNOSE_GUIDANCE except the evidence argument is a target selector.
DIAGNOSE_TARGET_GUIDANCE = (
    "\n\nBefore changing an existing file, first send diagnose. Replace <...> with real text:\n"
    "- diagnose: {\"path\": \"<file>\", \"target\": \"<the function or class name in a .py file, or the JSON pointer such as /key/subkey in a .json file, where the problem is>\", "
    "\"cause\": \"<why it is wrong>\", \"change\": \"<what you will change>\"}\n"
    "Then make the change."
)

# Used when calibration enables structured_edits: existing files are edited in place, never rewritten.
LITE_COMPACT_GUIDANCE_STRUCTURED = (
    "You are a coding agent working inside a real project folder. You CAN read and change files, but only by calling tools. "
    "Never say you cannot access files. Never invent file contents.\n\n"
    "To act, reply with exactly one JSON object and nothing else:\n"
    "{\"tool\": \"<name>\", \"args\": {...}}\n\n"
    "Tools:\n"
    "- read: {\"path\": \"file\"} - show a file's contents\n"
    "- write: {\"path\": \"file\", \"content\": \"full file text\"} - create a NEW file (cannot overwrite an existing file)\n"
    "- replace: {\"path\": \"file\", \"old\": \"exact existing text\", \"new\": \"replacement text\"} - change part of an existing file; old must appear exactly once\n"
    "- patch_json: {\"path\": \"file.json\", \"set\": {\"/key\": value}} - change values inside an existing JSON file\n"
    "- list: {\"path\": \"dir\"} - list a folder (\".\" is the project root)\n"
    "- delete: {\"path\": \"file\"} - delete a file\n"
    "Rules: change existing files only with replace or patch_json; read a file first if you do not know its exact text. "
    "Use list for folders, read for files.\n"
    "When the task is finished, reply {\"tool\": \"done\", \"args\": {\"summary\": \"what you did\"}}.\n"
    "Only if the user asks for a todo app: write content \"TEMPLATE:todo\" to index.html.\n\n"
    "Examples:\n"
    "User: Open notes.md\n"
    "{\"tool\": \"read\", \"args\": {\"path\": \"notes.md\"}}\n"
    "User: Make a file a.txt that says hi\n"
    "{\"tool\": \"write\", \"args\": {\"path\": \"a.txt\", \"content\": \"hi\"}}\n"
    "User: main.py contains print(\"hi\"). Change it to print(\"bye\")\n"
    "{\"tool\": \"replace\", \"args\": {\"path\": \"main.py\", \"old\": \"print(\\\"hi\\\")\", \"new\": \"print(\\\"bye\\\")\"}}\n"
    "User: Set debug to true in settings.json\n"
    "{\"tool\": \"patch_json\", \"args\": {\"path\": \"settings.json\", \"set\": {\"/debug\": true}}}"
)


class AgentLoop(Plugin):
    name = "agent_loop"
    dependencies = ("ollama_model", "file_tools")

    def __init__(self, max_rounds: int = 12, stream: bool = False) -> None:
        super().__init__()
        self.max_rounds = max_rounds
        self.stream = stream
        self._tool_handlers: dict[str, Callable[[dict[str, Any]], str]] = {}
        self._tool_schemas: list[dict[str, Any]] = []
        self._failed_calls: dict[str, int] = {}
        self._successful_calls: set[str] = set()
        self._success_versions: dict[str, int] = {}
        self._duplicate_notices: set[str] = set()
        self._missing_path_notices: set[str] = set()
        self._progress_recovery = False
        self._read_before_evidence = False
        self._evidence_extraction = False
        self._localized_edits = False
        self._explicit_selector_kind = False
        self._replacement_format_contract = False
        self._read_snapshots: dict[str, str] = {}
        self._replan_count = 0
        self._round = 0
        self._healing = BudgetedSelfHealing()
        self._context_builder = None
        self._retry_policy = RetryPolicy()
        # Built in start() from the active model calibration (core.context).
        self._context_pruner: ContextPruner | None = None
        self._token_budget = TOKEN_BUDGET
        self._max_result_bytes = MODEL_PRESETS[DEFAULT_PRESET_KEY]["max_tool_result_bytes"]
        self._require_read_before_write = False
        self._read_fingerprints: dict[Path, str] = {}
        self._blind_write_sigs: dict[str, int] = {}
        self._mutation_version = 0
        self._failed_repeat_keys: set[str] = set()
        self._repeat_retry_temperature: float | None = None
        self._require_known_paths = False
        self._ground_request_paths = False
        self._structured_edits = False
        self._repo_tools = False
        self._navigation_only = False
        self._targeted_grounding = False
        self._evidence_gated_completion = False
        self._evidence_paths: set[str] = set()
        self._evidence_gate_rejections = 0
        self._diagnose_before_mutation = False
        self._diagnosed_paths: set[str] = set()
        self._require_read_named_files = False
        self._array_guidance = True
        self._named_file_requirements: list[list[str]] = []
        self._successful_reads: set[str] = set()
        self._deleted_paths: set[str] = set()
        self._done_gate_rejections = 0
        # Gate qwen_donelatch_v1: completion is unavailable after an unapplied mutation until a later one is applied.
        self._completion_latch_enabled = False
        self._latched = False
        self._latch_version = 0
        self._latch_rejections = 0
        self._current_request = ""
        self._parse_retry_count = 0
        self._routers: SpecializedRouters | None = None
        self._semantic_router: SemanticRouter | None = None
        self._multi_domain_router: MultiDomainRouter | None = None
        self._aggregator: AggregateResponse | None = None
        self._multi_domain_results: list[Any] = []
        self._projector: RealityProjector | None = None
        self._manifest: Manifest | None = None
        self._system_prompt: str | None = None
        self._schema_router: SchemaRouter | None = None
        self._array_helper: Any = None
        self._app_verifier: Any = None
        self._decision_logger: DecisionLogger | None = None

    def start(self) -> None:
        assert self.context is not None
        cal = calibration_from_context(self.context)
        self._token_budget = cal["pruner_budget"]
        self._max_result_bytes = cal["max_tool_result_bytes"]
        self._require_read_before_write = bool(cal.get("require_read_before_write", False))
        self._require_known_paths = bool(cal.get("require_known_paths", False))
        self._ground_request_paths = bool(cal.get("ground_request_paths", False))
        self._structured_edits = bool(cal.get("structured_edits", False))
        self._repo_tools = bool(cal.get("repo_tools", False))
        self._navigation_only = bool(cal.get("navigation_only", False))
        self._targeted_grounding = bool(cal.get("targeted_grounding", False))
        self._evidence_gated_completion = bool(cal.get("evidence_gated_completion", False))
        self._diagnose_before_mutation = bool(cal.get("diagnose_before_mutation", False))
        self._progress_recovery = bool(cal.get("progress_recovery", False))
        self._read_before_evidence = bool(cal.get("read_before_evidence", False))
        self._require_read_named_files = bool(cal.get("require_read_named_files", False))
        # Array hints are keyword-triggered and were observed misfiring and being parroted by 1B models.
        self._array_guidance = bool(cal.get("array_guidance", True))
        self._repeat_retry_temperature = cal.get("repeat_retry_temperature")
        self._context_pruner = ContextPruner(max_messages=cal["max_messages"], token_budget=cal["pruner_budget"])
        files = self.context.plugins["file_tools"]
        self._tool_schemas = files.schemas()
        self._tool_handlers = {s["function"]["name"]: files.execute for s in self._tool_schemas}
        self._evidence_extraction = bool(cal.get("evidence_extraction", False))
        self._localized_edits = bool(cal.get("localized_edits", False))
        self._explicit_selector_kind = bool(cal.get("explicit_selector_kind", False))
        self._replacement_format_contract = bool(cal.get("replacement_format_contract", False))
        self._completion_latch_enabled = bool(cal.get("completion_requires_mutation_success", False))
        if self._evidence_extraction and "diagnose" in self._tool_handlers:
            self._tool_handlers["diagnose"] = self._diagnose_from_snapshot
        self._schema_router = self.context.plugins.get("schema_router")
        self._array_helper = self.context.plugins.get("array_helper")
        self._routers = SpecializedRouters(
            tool_handlers=self._tool_handlers,
            context=self.context,
            record_tool_result=self._record_tool_result,
            resolve_path=self._resolve_path,
        )
        self._semantic_router = self.context.plugins.get("semantic_router")
        self._multi_domain_router = self.context.plugins.get("multi_domain_router")
        self._aggregator = self.context.plugins.get("aggregate_response")
        self._app_verifier = self.context.plugins.get("app_verifier")
        self._decision_logger = self.context.plugins.get("decision_logger")
        if self._decision_logger is not None:
            self._decision_logger.set_session_id(self._get_session_id())
        self._tool_result_pruner = self.context.plugins.get("tool_result_pruner")

    def tool_schemas(self) -> list[dict[str, Any]]:
        return list(self._tool_schemas)

    def _get_active_tool_schemas(self) -> list[dict[str, Any]]:
        """Return the tool schemas the model should see this turn.

        If schema_router is enabled and compact_schema is True, use the
        compact schema from the router instead of the verbose registry schemas.
        """
        if self._schema_router is not None and getattr(self._schema_router, "enabled", False):
            compact = self._schema_router.get_model_tools()
            if compact:
                return compact
        return list(self._tool_schemas)

    def _expand_compact_calls(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Expand compact-schema logical calls (call_tool) into real tool calls.

        When the model uses call_tool(tool, args), this method rewrites each
        call into the real tool name/arguments expected by the rest of the loop.
        Calls that are not compact-schema calls pass through unchanged.
        'done' logical calls are dropped (no real tool to execute).
        """
        if self._schema_router is None or not getattr(self._schema_router, "enabled", False):
            return tool_calls

        expanded: list[dict[str, Any]] = []
        for call in tool_calls:
            real = self._schema_router.expand_call(call)
            if real is None:
                # 'done' or unknown — skip (no real tool)
                continue
            expanded.append(real)
        return expanded

    def _sig(self, call: dict[str, Any]) -> str:
        fn = call.get("function", {})
        try:
            return f"{fn.get('name', '')}:{json.dumps(fn.get('arguments') or {}, sort_keys=True, default=str)}"
        except Exception:
            return f"{fn.get('name', '')}:{fn.get('arguments')}"

    def _repeat_key(self, name: str, arguments: Any) -> str:
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                pass
        if isinstance(arguments, dict):
            arguments = {
                k: (v.strip().replace("\\", "/").removeprefix("./") if k == "path" and isinstance(v, str) else v)
                for k, v in arguments.items()
            }
        try:
            normalized = json.dumps(arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            normalized = str(arguments)
        return f"{name}:{normalized}@v{self._mutation_version}"

    def _is_duplicate_success(self, call: dict[str, Any]) -> bool:
        """A mutation that already succeeded is a duplicate (unchanged behavior). A non-mutating call is a duplicate only
        if it succeeded with no mutation since, i.e. its result still describes the workspace."""
        sig = self._sig(call)
        if sig not in self._successful_calls:
            return False
        if str(call.get("function", {}).get("name", "")) in _MUTATING_TOOLS:
            return True
        return self._success_versions.get(sig) == self._mutation_version

    def _duplicate_read_notice(self, tool_calls: list[dict[str, Any]]) -> str:
        """Accurate guidance for repeated read-only calls. The second notice for the same call marks it as a failed
        repeat, so a third identical proposal goes through the existing repeat policy (resample, then escalate)."""
        described = []
        for call in tool_calls:
            fn = call.get("function", {})
            args = self._parse_arguments(fn.get("arguments"))
            target = args.get("path") or args.get("pattern") or args.get("name") or args.get("symbol") or args.get("target")
            described.append(f"{fn.get('name', '')} {target}" if target else str(fn.get("name", "")))
            key = self._call_repeat_key(call)
            if key in self._duplicate_notices:
                self._failed_repeat_keys.add(key)
            self._duplicate_notices.add(key)
        return (
            f"You already ran {'; '.join(described)} and the result is shown above; nothing has changed since. "
            "The task is not finished. Do not repeat that call: use the result you already have for the next step."
        )

    def _call_path(self, call: dict[str, Any]) -> str:
        return str(self._parse_arguments(call.get("function", {}).get("arguments")).get("path", ""))

    def _repeated_read_recovery(self, call: dict[str, Any]) -> str:
        path = self._call_path(call)
        target = self._resolve_path(path)
        try:
            lines = len(target.read_text(encoding="utf-8").splitlines()) if target is not None else None
        except OSError:
            lines = None
        size = f" ({lines} lines)" if lines is not None else ""
        return (f"Not executed: {path} was already read by your earlier action and its complete contents{size} are in the tool result above. "
                f"The file has not changed since, so reading it again shows nothing new. Your next action must be something other than reading {path}.")

    def _missing_path_recovery(self, call: dict[str, Any]) -> Optional[str]:
        """First repeat of a read on a path this run already found missing, at the same mutation version."""
        if str(call.get("function", {}).get("name", "")) != "read_file":
            return None
        path = self._call_path(call)
        target = self._resolve_path(path)
        key = self._call_repeat_key(call)
        if target is None or target.exists() or key not in self._failed_repeat_keys or key in self._missing_path_notices:
            return None
        self._missing_path_notices.add(key)
        return (f"Not executed: your earlier action already established that {path} does not exist, and the workspace has not changed since. "
                f"This identical path will not be tried again. Your next action must be something other than reading {path}.")

    def _deliver_recovery(self, session_id: str, content: str, tool_calls: list[dict[str, Any]], texts: list[str], state: str) -> None:
        """Record the model's call and answer it as that call's (unexecuted) tool result, so it reaches the lite envelope."""
        self.context.append_message("assistant", content, tool_calls=tool_calls)
        self.context.events.emit("assistant.message", {"content": content, "tool_calls": tool_calls})
        for call, text in zip(tool_calls, texts):
            name = str(call.get("function", {}).get("name", ""))
            arguments = self._parse_arguments(call.get("function", {}).get("arguments"))
            self.context.append_message("tool", text, tool_name=name)
            self.context.events.emit("tool.result", {"tool": name, "arguments": arguments, "result": text, "success": False, "recovery": state})
            self.context.events.emit("progress.recovery", {"session_id": session_id, "round": self._round, "state": state, "path": arguments.get("path")})

    def _call_repeat_key(self, call: dict[str, Any]) -> str:
        fn = call.get("function", {}) if isinstance(call, dict) else {}
        return self._repeat_key(str(fn.get("name", "")), fn.get("arguments") or {})

    def _repeated_failures(self, tool_calls: list[dict[str, Any]]) -> list[str]:
        keys = [self._call_repeat_key(c) for c in tool_calls]
        return [k for k in keys if k in self._failed_repeat_keys]

    def _emit_latch(self, action: str, reason: str) -> None:
        self.context.events.emit("completion.latch", {"round": self._round, "reason": reason, "latch_version": self._latch_version,
                                                      "mutation_version": self._mutation_version, "action": action})

    def _observe_mutation_attempt(self, name: str, version_before: int) -> None:
        """Gate qwen_donelatch_v1. A mutating attempt that did not raise the mutation version sets the latch (only when
        unlatched); one that raised it releases the current episode."""
        if not self._completion_latch_enabled or name not in _MUTATING_TOOLS:
            return
        if self._mutation_version > version_before:
            if self._latched and self._mutation_version > self._latch_version:
                self._latched = False
                self._latch_rejections = 0
                self._emit_latch("released", "mutation_applied")
        elif not self._latched:
            self._latched = True
            self._latch_version = self._mutation_version
            self._latch_rejections = 0
            self._emit_latch("set", "mutation_not_applied")

    def _escalate(self, model: Any, session_id: str, reason: str, repeated: list[str], task_state: dict[str, Any], user_text: str) -> None:
        outcome = EscalationOutcome(
            reason=reason,  # type: ignore[arg-type]
            model=str(getattr(model, "model", type(model).__name__)),
            round=self._round,
            mutation_version=self._mutation_version,
            repeated_calls=repeated,
            retry_temperature=self._repeat_retry_temperature,
            evidence=[f"failed:{k}" for k in sorted(self._failed_repeat_keys)],
        )
        self.context.events.emit("turn.escalated", {"session_id": session_id, **outcome.to_dict()})
        self.context.events.emit("turn.end", {"final_result": "", "error": "escalated", "session_id": session_id})
        self._mark_session_outcome_failure(user_text, session_id, task_state)
        raise EscalationRequired(outcome)

    def _interpret_response(self, response: Message, active_schemas: list[dict[str, Any]]) -> tuple[Message, list[dict[str, Any]]]:
        tool_calls = response.tool_calls or []
        # main.py registers OllamaToolCallParser under its own name
        # ("ollama_tool_call_parser"); accept the generic role name too.
        parser = self.context.plugins.get("ollama_tool_call_parser") or self.context.plugins.get("tool_call_parser")
        if not tool_calls and parser is not None and response.content:
            tool_calls = parser.parse(response, active_schemas) or []
        # Expand compact-schema logical calls (call_tool) into real tool calls
        if tool_calls:
            done_summary = self._schema_router.done_summary(tool_calls) if self._schema_router is not None else None
            tool_calls = self._expand_compact_calls(tool_calls)
            if not tool_calls and done_summary:
                response = Message(role=response.role, content=done_summary)
        return response, tool_calls

    def _blocked(self, sig: str) -> bool:
        return self._failed_calls.get(sig, 0) >= 2

    def _record_fail(self, sig: str) -> None:
        self._failed_calls[sig] = self._failed_calls.get(sig, 0) + 1

    def _log_routing_decision(self, decision_type: str, input_data: Any, output_data: Any) -> None:
        if self._decision_logger is not None:
            self._decision_logger.increment_turn()
            self._decision_logger.log_decision(
                decision_type=decision_type,
                input_data=input_data,
                output_data=output_data,
                confidence=1.0,
                duration_ms=0.0,
                alternatives_considered=[],
            )

    def _log_tool_decision(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        duration_ms: float = 0.0,
        error: str | None = None,
    ) -> None:
        if self._decision_logger is not None:
            self._decision_logger.log_decision(
                decision_type="tool_selection",
                input_data={"tool_name": tool_name, "arguments": arguments},
                output_data={"result": result, "success": success, "error": error},
                confidence=1.0 if success else 0.0,
                duration_ms=duration_ms,
                alternatives_considered=[],
            )

    @staticmethod
    def _parse_arguments(raw: Any) -> dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ToolError(f"Malformed tool arguments: {raw!r}") from exc
            if not isinstance(parsed, dict):
                raise ToolError("Tool arguments must decode to a JSON object.")
            return parsed
        raise ToolError("Unsupported tool argument format.")

    def _classify_failure(self, exc: Exception, context: dict[str, Any]) -> FailureType:
        return FailureClassifier.classify(exc, context)

    def _quarantine(self, context: Any, sig: str, exc: Exception) -> None:
        note = json.dumps({
            "role": "system",
            "content": f"Previous attempt to call {sig} failed with {type(exc).__name__}: {exc}. Do not repeat identical call.",
        }, ensure_ascii=False)
        context.append_message("system", note)
        context.events.emit(SYSTEM_MESSAGE, {"content": note})

    @staticmethod
    def _fingerprint(path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        except OSError:
            return None

    def _enforce_known_path(self, name: str, arguments: dict[str, Any]) -> None:
        """Refuse reads/writes of a missing path when an existing file with that (or a typo-like) name exists elsewhere."""
        if not self._require_known_paths:
            return
        file_tools = self.context.plugins.get("file_tools")
        workspace = getattr(file_tools, "workspace", None)
        if workspace is None:
            return
        path = arguments.get("path")
        verdict = classify_path(Path(workspace), name, path if isinstance(path, str) else "", self._current_request)
        if not verdict.wrong_path:
            return
        listed = ", ".join(verdict.candidates)
        raise PolicyRejection(
            f"{path} does not exist. Existing file(s) with a matching name: {listed}. "
            "Use one of these exact paths.",
            reason="wrong_path",
            details={"conflict": verdict.conflict, "candidates": verdict.candidates},
        )

    def _enforce_named_read_before_mutation(self, name: str, arguments: dict[str, Any], target: Optional[Path]) -> None:
        """A file the request names may be changed only after that exact path was read with read_file this run.
        Reading another candidate for the same name does not count, nor do contents shown by a guard refusal."""
        if not self._require_read_named_files or name not in ("write_file", "replace_text", "patch_json", "edit_symbol") or target is None:
            return
        workspace = getattr(self.context.plugins.get("file_tools"), "workspace", None)
        if workspace is None:
            return
        try:
            rel = target.relative_to(Path(workspace)).as_posix()
        except ValueError:
            return
        named = {path for alternatives in self._named_file_requirements for path in alternatives}
        if rel in named and rel not in self._successful_reads:
            raise PolicyRejection(
                f"{rel} is named by the task and has not been read. Read {rel} first, then make the change.",
                reason="named_file_unread",
            )

    def _workspace_relative(self, target: Optional[Path]) -> Optional[str]:
        workspace = getattr(self.context.plugins.get("file_tools"), "workspace", None)
        if target is None or workspace is None:
            return None
        try:
            return target.relative_to(Path(workspace)).as_posix()
        except ValueError:
            return None

    def _enforce_read_before_evidence(self, name: str, arguments: dict[str, Any]) -> None:
        """Read-before-evidence (gate qwen_evidence_v1): a diagnosis may reference only a file read in full this run
        and unchanged since (the read fingerprint still matches the file)."""
        if not self._read_before_evidence or name != "diagnose":
            return
        path = str(arguments.get("path", ""))
        target = self._resolve_path(path)
        if target is not None and target.is_file() and self._read_fingerprints.get(target) == self._fingerprint(target):
            return
        raise PolicyRejection(
            f"Not recorded: {path} has not been read in this task (or changed since it was read). Read {path} first, then quote the exact lines from it.",
            reason="evidence_requires_read",
        )

    def _diagnose_from_snapshot(self, name: str, arguments: dict[str, Any]) -> str:
        """Gate qwen_extract_v1: resolve the model's selector against the frozen read snapshot of that path only.
        No disk read, no other file, no index or search; exact selector matching; failures give no suggestions."""
        path = str(arguments.get("path", ""))
        target = str(arguments.get("target", ""))
        cause, change = str(arguments.get("cause", "")).strip(), str(arguments.get("change", "")).strip()
        rel = self._workspace_relative(self._resolve_path(path))
        snapshot = self._read_snapshots.get(rel) if rel is not None else None
        if snapshot is None:
            raise ToolError(f"{path} has no complete read in this task to take evidence from.")
        if not cause or not change:
            raise ToolError("diagnose needs a cause and a change.")
        span = target_line_span(rel, snapshot, target)
        if span is None:
            if rel.endswith(".json"):
                raise ToolError(f"JSON pointer {target} does not resolve in {path} as you read it.")
            if rel.endswith(".py"):
                raise ToolError(f"{target} is not a function, class, method or assignment defined in {path} as you read it.")
            raise ToolError(f"{path}: evidence targets are supported only for .py and .json files.")
        lines = snapshot.splitlines()[span[0] - 1:span[1]]
        where = f"line {span[0]}" if span[0] == span[1] else f"lines {span[0]}-{span[1]}"
        digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        return (f"Diagnosis recorded for {path} ({where}):\n" + "\n".join(lines)
                + f"\nCause: {cause} Change: {change}\nsnapshot_sha256: {digest}")

    def _enforce_diagnosis(self, name: str, target: Optional[Path]) -> None:
        """Diagnose-before-mutation: an existing file changes only after a successful diagnose for that exact path."""
        if not self._diagnose_before_mutation or name not in ("write_file", "replace_text", "patch_json", "edit_symbol") or target is None or not target.is_file():
            return
        rel = self._workspace_relative(target)
        if rel is None or rel in self._diagnosed_paths:
            return
        raise PolicyRejection(
            f"Before changing {rel}, send diagnose with the exact text from {rel} that shows the problem, the cause, and the change you will make.",
            reason="diagnosis_required",
        )

    def _enforce_structured_overwrite(self, name: str, arguments: dict[str, Any], target: Optional[Path]) -> None:
        """With structured edits, write_file only creates new files; existing files change via replace/patch_json;
        JSON files change only via patch_json (a text replace can rename a key and still parse)."""
        if self._localized_edits and name == "write_file" and target is not None and target.is_file():
            # Gate qwen_localedit_v1: existing files change only through the bounded edit action.
            raise PolicyRejection(
                f"{arguments.get('path')} already exists; change it with edit (path, target, replacement).",
                reason="overwrite_existing_file",
            )
        if not self._structured_edits or target is None or not target.is_file():
            return
        path = str(arguments.get("path"))
        if name == "replace_text" and path.lower().endswith(".json"):
            raise PolicyRejection(
                f"{path} is a JSON file; change it with patch_json, e.g. {{\"path\": \"{path}\", \"set\": {{\"/key\": value}}}}.",
                reason="json_requires_patch",
            )
        if name != "write_file":
            return
        how = "patch_json with {\"/key\": value}" if path.lower().endswith(".json") else "replace with the exact old text and the new text"
        raise PolicyRejection(
            f"{path} already exists and cannot be overwritten. Change it with {how}.",
            reason="overwrite_existing_file",
        )

    def _enforce_read_before_write(self, name: str, arguments: dict[str, Any], target: Optional[Path], signature: str) -> None:
        """Invariant: an existing file is overwritten or edited only if its current contents were seen this run.
        Edits are included because a short unique token (e.g. "port") matches without any knowledge of the file."""
        if not self._require_read_before_write or name not in ("write_file", "replace_text", "patch_json", "edit_symbol") or target is None or not target.is_file():
            return
        editing = name != "write_file"
        # A blind write stays rejected until the model has had a turn to see the contents shown (blocks same-round retries).
        if self._blind_write_sigs.get(signature) == self._round:
            raise PolicyRejection(
                f"This change to {arguments.get('path')} was produced before its contents were read. "
                "Base the change on the contents shown.",
                reason="blind_write_retry",
            )
        current_fp = self._fingerprint(target)
        if current_fp is not None and self._read_fingerprints.get(target) == current_fp:
            return
        self._blind_write_sigs[signature] = self._round
        try:
            current = self.context.plugins["file_tools"].read_file(str(arguments.get("path")))
        except ToolError as exc:
            raise PolicyRejection(f"{arguments.get('path')} already exists and could not be shown ({exc}); it was not overwritten.", reason="unshowable_overwrite") from exc
        if len(current.encode("utf-8")) > self._max_result_bytes:
            raise PolicyRejection(f"{arguments.get('path')} already exists and is too large to show in full; it was not overwritten.", reason="unshowable_overwrite")
        if current_fp is not None:
            self._read_fingerprints[target] = current_fp
        # Small models ignore "read first" instructions; showing the contents makes the next attempt informed.
        if editing:
            raise PolicyRejection(
                f"{arguments.get('path')} was not read before editing. Current contents:\n{current}\n"
                "Make the change based on these exact contents.",
                reason="unread_edit",
            )
        raise PolicyRejection(
            f"{arguments.get('path')} already exists and was not read. Current contents:\n{current}\n"
            "Write the full updated file, keeping everything that should stay.",
            reason="unread_overwrite",
        )

    def _shown_in_full(self, name: str, result: Any, pruned_result: Any) -> bool:
        """True only if no later transform (pruner, byte cap, compact compression) will hide or alter the result."""
        if not isinstance(result, str) or pruned_result != result:
            return False
        if len(result.encode("utf-8")) > self._max_result_bytes:
            return False
        if self._schema_router is not None and getattr(self._schema_router, "compact_mode", False):
            return self._schema_router.compress_tool_output(name, result) == result
        return True

    def _workspace_file_set(self) -> set[str]:
        workspace = getattr(self.context.plugins.get("file_tools"), "workspace", None)
        return set(index_for(Path(workspace)).files) if workspace is not None else set()

    def _unsupported_declarations(self, text: str) -> list[str]:
        files = self._workspace_file_set()
        declared = list(dict.fromkeys(normalize(p) for p in declared_paths(text)))
        return [p for p in declared if p not in files or p not in self._evidence_paths]

    def _record_evidence(self, name: str, target: Optional[Path], result: Any) -> None:
        """Paths the run has actually established: a successful read, or paths named in repository/search output."""
        if not (self._evidence_gated_completion or self._targeted_grounding):
            return
        workspace = getattr(self.context.plugins.get("file_tools"), "workspace", None)
        if workspace is None:
            return
        if name == "read_file" and target is not None:
            try:
                self._evidence_paths.add(target.relative_to(Path(workspace)).as_posix())
            except ValueError:
                pass
        elif name in _EVIDENCE_OUTPUT_TOOLS and isinstance(result, str):
            files = self._workspace_file_set()
            self._evidence_paths |= {p for p in (normalize(r) for r in declared_paths(result)) if p in files}

    def _unmet_named_file_reads(self) -> list[list[str]]:
        return [
            alternatives for alternatives in self._named_file_requirements
            if not any(a in self._successful_reads or a in self._deleted_paths for a in alternatives)
        ]

    def _record_file_state(self, name: str, target: Optional[Path], shown_in_full: bool) -> None:
        if name in _MUTATING_TOOLS:
            self._mutation_version += 1
        if target is None:
            return
        workspace = getattr(self.context.plugins.get("file_tools"), "workspace", None)
        if workspace is not None and name in ("read_file", "delete_file"):
            try:
                rel = target.relative_to(Path(workspace)).as_posix()
            except ValueError:
                rel = None
            if rel is not None:
                (self._successful_reads if name == "read_file" else self._deleted_paths).add(rel)
        if name == "delete_file":
            self._read_fingerprints.pop(target, None)
            return
        if name == "read_file" and not shown_in_full:
            self._read_fingerprints.pop(target, None)
            return
        fp = self._fingerprint(target)
        if fp is not None:
            self._read_fingerprints[target] = fp

    def _execute_tool_call(self, call: dict[str, Any]) -> str:
        fn = call.get("function", {})
        name = fn.get("name")
        if not isinstance(name, str):
            raise ToolError("Tool call has no valid function name.")

        # Defense-in-depth: if a compact-schema call_tool reaches dispatch
        # without prior expansion, expand it here.
        if name == "call_tool" and self._schema_router is not None and getattr(self._schema_router, "enabled", False):
            expanded = self._schema_router.expand_call(call)
            if expanded is None:
                # 'done' or unknown — no real tool to execute
                return json.dumps({"status": "done", "tool": "call_tool", "arguments": {}}, ensure_ascii=False)
            call = expanded
            fn = call.get("function", {})
            name = fn.get("name", "")

        arguments = self._parse_arguments(fn.get("arguments"))
        handler = self._tool_handlers.get(name)
        if handler is None:
            raise ToolError(f"Unknown tool requested by model: {name}")

        call_id = call.get("id") or f"call_{uuid.uuid4().hex[:8]}"
        signature = self._sig(call)

        if self._blocked(signature):
            error_msg = json.dumps({"error": f"Tool '{name}' blocked after repeated failures", "tool": name, "arguments": arguments, "blocked": True}, ensure_ascii=False)
            if self.context and self.context.plugins.get("event_logger"):
                self.context.plugins["event_logger"].emit("tool.result", {"tool_name": name, "call_id": call_id, "arguments": arguments, "success": False, "result": error_msg, "blocked": True})
            return error_msg

        logger = self.context.plugins.get("event_logger") if self.context else None
        step = None
        if logger is not None:
            step = logger.start_step(name, arguments)
            flags = PreFlightGuard.check(name, arguments, {"recent_tool_calls": []})
            if flags:
                step.governance_check_passed = False

        if self.context is not None:
            self.context.events.emit("tool.invoked", {"tool_name": name, "call_id": call_id, "arguments": arguments})
            self.context.events.emit(TOOL_CALL_START, {"tool_name": name, "call_id": call_id, "arguments": arguments})

        target = self._resolve_path(str(arguments.get("path", ""))) if name in _FILE_STATE_TOOLS else None
        # A policy rejection, not a tool failure: raised before failure bookkeeping (quarantine notes, fail counts).
        try:
            if self._navigation_only and name not in _NAVIGATION_TOOLS:
                raise PolicyRejection(f"{name} is not allowed: this task only locates code. Use read, list or the repository tools, then finish with done.", reason="navigation_only")
            self._enforce_known_path(name, arguments)
            self._enforce_named_read_before_mutation(name, arguments, target)
            self._enforce_diagnosis(name, target)
            self._enforce_read_before_evidence(name, arguments)
            self._enforce_structured_overwrite(name, arguments, target)
            self._enforce_read_before_write(name, arguments, target, signature)
        except PolicyRejection as rejection:
            if rejection.reason in ("wrong_path", "overwrite_existing_file", "json_requires_patch", "navigation_only"):
                # Re-proposing a missing path against unchanged state is never correct; let repeat detection escalate it.
                self._failed_repeat_keys.add(self._repeat_key(name, arguments))
            self.context.events.emit("guard.rejected", {
                "reason": rejection.reason, "tool": name, "path": arguments.get("path"),
                "round": self._round, "mutation_version": self._mutation_version, **rejection.details,
            })
            self.context.events.emit(TOOL_CALL_END, {"tool_name": name, "call_id": call_id, "success": False, "error": str(rejection)})
            if step is not None:
                logger.finish_step(step, error=str(rejection))
            raise

        try:
            result = retry_with_backoff(
                handler,
                name,
                arguments,
                policy=self._retry_policy,
                should_retry=lambda exc: self._classify_failure(
                    exc, {"tool_name": name, "arguments": arguments}
                ) in (FailureType.TRANSIENT, FailureType.ARGUMENT),
            )
        except Exception as exc:
            if self.context is not None:
                self.context.events.emit(TOOL_CALL_END, {"tool_name": name, "call_id": call_id, "success": False, "error": str(exc)})
            if step is not None:
                logger.finish_step(step, error=str(exc))
            self._record_fail(signature)
            self._failed_repeat_keys.add(self._repeat_key(name, arguments))
            failure_type = self._classify_failure(exc, {"tool_name": name, "arguments": arguments})
            self._quarantine(self.context, signature, exc)
            healing = self._healing.handle_failure(failure_type, {"tool_name": name, "arguments": arguments})
            action = healing.get("action", "abstain")
            # retry_with_backoff already exhausted execution-layer retries;
            # preserve historical behavior by skipping the repair message on
            # retry-class failures.
            if action != "retry":
                repair = RepairMessageBuilder.build(name, failure_type, healing)
                self.context.append_message("system", repair)
                self.context.events.emit(SYSTEM_MESSAGE, {"content": repair})
            raise

        # Post-execute: prune or spill oversized results.
        pruned_result = result
        if self._tool_result_pruner is not None:
            try:
                pruned_result, _pruned, _spill = self._tool_result_pruner.prune(name, call_id, result)
            except Exception:
                pruned_result = result

        shown_in_full = self._shown_in_full(name, result, pruned_result)
        self._record_file_state(name, target, shown_in_full=shown_in_full)
        if name == "read_file" and shown_in_full and isinstance(result, str):
            rel = self._workspace_relative(target)
            if rel is not None:
                self._read_snapshots[rel] = result  # the exact text the model received in full
        self._record_evidence(name, target, result)
        if name == "diagnose" and self._diagnose_before_mutation:
            rel = self._workspace_relative(self._resolve_path(str(arguments.get("path", ""))))
            if rel is not None:
                self._diagnosed_paths.add(rel)

        if step is not None:
            verified = ToolResultVerifier.verify(name, arguments, pruned_result)
            step.governance_check_passed = verified
            logger.finish_step(step, output=pruned_result)

        if self.context is not None:
            self.context.events.emit(TOOL_CALL_END, {"tool_name": name, "call_id": call_id, "success": True})

        return pruned_result

    def _get_session_id(self) -> str:
        event_logger = self.context.plugins.get("event_logger") if self.context else None
        if event_logger is not None and hasattr(event_logger, "continuity"):
            return event_logger.continuity.session_id
        return "default"

    def _build_manifest(self, system_prompt: str) -> Manifest:
        active_schemas = self._get_active_tool_schemas()
        sch_json = json.dumps(active_schemas, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        sch_hash = hashlib.sha256(sch_json.encode("utf-8")).hexdigest()
        profile = self.context.config.get("profile", "lite") if self.context else "lite"
        digest = hashlib.sha256(
            json.dumps(
                {
                    "system_prompt": system_prompt,
                    "tool_schema_hash": sch_hash,
                    "profile": profile,
                    "budget_tokens": self._token_budget,
                    "serializer_version": "v1",
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return Manifest(
            digest=digest,
            tool_schema_hash=sch_hash,
            prompt_hash=hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
            serializer_version="v1",
            profile=profile,
            budget_tokens=self._token_budget,
        )

    def _compile_request_envelope(self, session_id: str, system_prompt: str) -> RequestEnvelope:
        if self._projector is None:
            self._projector = RealityProjector(self.context.plugins["event_logger"].event_log)
        if self._manifest is None:
            self._manifest = self._build_manifest(system_prompt)
        self._projector.invalidate_cache(session_id)
        active_schemas = self._get_active_tool_schemas()
        return self._projector.compile_request(session_id, self._manifest, system_prompt, active_schemas, self._token_budget)

    @staticmethod
    def _consume_stream(chunks: Any, on_stream: Optional[Callable[[Message], None]] = None) -> Message:
        final = None
        for chunk in chunks:
            final = chunk
            if on_stream is not None:
                on_stream(chunk)
        return final or Message("assistant", "")

    def _record_tool_result(self, tool_name: str, arguments: dict, result: str, success: bool) -> None:
        if isinstance(result, str):
            # 33k window protection (calibration-separation axiom): a single tool
            # result must never occupy more than its calibrated share of the
            # window. The file keeps its full content on disk; the model works
            # on the first chunk and the marker tells it the file continues.
            raw = result.encode("utf-8")
            if len(raw) > self._max_result_bytes:
                result = raw[: self._max_result_bytes].decode("utf-8", errors="ignore") + f"\n…[truncated: showing first {self._max_result_bytes} bytes of a larger file]"
            # Compact-schema result compression (file contents are only length-truncated, never rewritten)
            if self._schema_router is not None and getattr(self._schema_router, "compact_mode", False):
                result = self._schema_router.compress_tool_output(tool_name, result)
        call_id = f"zt_{tool_name}_{hashlib.md5(str(arguments).encode()).hexdigest()[:8]}"
        if self.context is not None:
            self.context.events.emit("tool.invoked", {"tool_name": tool_name, "call_id": call_id, "arguments": arguments})
            self.context.events.emit("tool.result", {"tool_name": tool_name, "call_id": call_id, "arguments": arguments, "success": success, "result": result})
        self.context.append_message("tool", result, tool_name=tool_name)

    def _resolve_path(self, user_path: str) -> Optional[Path]:
        file_tools = self.context.plugins.get("file_tools") if self.context else None
        if file_tools is None:
            return None
        try:
            return file_tools._resolve(user_path)
        except Exception:
            return None

    def _try_multi_domain(self, user_text: str) -> None:
        if self._multi_domain_router is None or self._aggregator is None:
            return

        multi = self._multi_domain_router.route_multi(user_text, self.context)
        if multi is None:
            return

        deterministic = [r for r in multi.results if r.response is not None]
        unresolved = [r for r in multi.results if r.response is None]

        if not deterministic:
            return

        # Zero-token guarantee (P0): the LLM fallback for unresolved fragments is a
        # routing LLM step — allowed ONLY in the full profile AND with explicit
        # --enable-semantic-router. Otherwise abandon multi-domain routing and let
        # the query fall through to the deterministic routers + normal agent loop.
        if unresolved and not (
            self.context.config.get("profile") == "full"
            and self.context.config.get("semantic_router_enabled", False)
        ):
            return

        if unresolved:
            for frag in unresolved:
                llm_answer = self._call_llm_directly(frag.fragment.text)
                deterministic.append(type(frag)(fragment=frag.fragment, domain=frag.domain, response=llm_answer))

        self._multi_domain_results = deterministic

    def _call_llm_directly(self, text: str) -> str:
        # Fail-loud: if the model call fails here (Ollama down, model error),
        # the main agent loop would fail too — surface the real error instead
        # of appending a silently empty fragment to the aggregated answer.
        model = self.context.plugins.get("ollama_model") if self.context else None
        if model is None:
            return ""
        response = model.chat([Message(role="user", content=text)], tools=[])
        return response.content or ""

    def run(self, user_text: str, on_stream: Optional[Callable[[Message], None]] = None) -> str:
        assert self.context is not None
        model = self.context.plugins["ollama_model"]
        summarizer = Summarizer()
        self._context_builder = self.context.plugins.get("context_builder")

        self.context.reset_cancel()
        self._failed_calls.clear()
        self._successful_calls.clear()
        self._success_versions = {}
        self._duplicate_notices = set()
        self._missing_path_notices = set()
        self._read_snapshots = {}
        self._current_request = user_text
        self._successful_reads = set()
        self._deleted_paths = set()
        self._done_gate_rejections = 0
        self._evidence_paths = set()
        self._evidence_gate_rejections = 0
        self._diagnosed_paths = set()
        self._named_file_requirements = []
        if self._require_read_named_files:
            workspace = getattr(self.context.plugins.get("file_tools"), "workspace", None)
            if workspace is not None:
                self._named_file_requirements = named_existing_files(Path(workspace), user_text)
        self._read_fingerprints.clear()
        self._blind_write_sigs.clear()
        self._mutation_version = 0
        # Latch state is reset per task (this run), never per model round.
        self._latched = False
        self._latch_version = 0
        self._latch_rejections = 0
        self._failed_repeat_keys.clear()
        self._replan_count = 0
        self._parse_retry_count = 0

        # Reset per-run state for optional plugins (zero-drag invariant)
        if self._array_helper is not None and hasattr(self._array_helper, "reset_run_state"):
            self._array_helper.reset_run_state()

        self.context.append_message("user", user_text)
        if self.context is not None:
            self.context.events.emit("user.message", {"content": user_text})

        session_id = self._get_session_id()
        self.context.events.emit("turn.start", {
            "user_text": user_text,
            "session_id": session_id,
        })

        self._try_multi_domain(user_text)

        if not self._multi_domain_results:
            fast_result = self._routers.try_zero_thought(user_text) if self._routers else None
            if fast_result is not None:
                self._log_routing_decision("zero_thought", user_text, fast_result)
                return fast_result

            # P0 FIX: SemanticRouter is gated (default OFF) to preserve zero-token guarantee
            # Only route semantically if enabled via config or constructor
            if self._semantic_router is not None and getattr(self._semantic_router, "enabled", False):
                semantic_result = self._semantic_router.route(user_text)
                if semantic_result is not None:
                    self._log_routing_decision("semantic_router", user_text, semantic_result)
                    return semantic_result

            math_result = try_math_router(user_text, self.context)
            if math_result is not None:
                self._log_routing_decision("math_router", user_text, math_result)
                return math_result

            datetime_result = try_datetime_router(user_text, self.context)
            if datetime_result is not None:
                self._log_routing_decision("datetime_router", user_text, datetime_result)
                return datetime_result

            units_result = try_units_router(user_text, self.context)
            if units_result is not None:
                self._log_routing_decision("units_router", user_text, units_result)
                return units_result

        if self._multi_domain_results:
            return self._aggregator.aggregate(self._multi_domain_results) if self._aggregator else str(self._multi_domain_results)

        task_state = {"goal": user_text, "files_touched": [], "tools_used": [], "unresolved_subtasks": []}

        # --- Optional ArrayHelper integration (zero-drag when irrelevant) ---
        # Analyze task relevance deterministically (reset already done in run() preamble)
        array_facts: dict[str, Any] = {}
        array_facts_changed = False

        if self._array_helper is not None:
            array_analysis = self._array_helper.analyze_task(user_text)
            if array_analysis.get("relevant") and array_analysis.get("confidence") in ("medium", "high"):
                array_facts = {
                    "operation": array_analysis.get("operation"),
                    "risks": array_analysis.get("risks", []),
                }
                array_facts_changed = True
                if self.context is not None:
                    self.context.events.emit("array.analysis.completed", {
                        "session_id": session_id,
                        "relevant": True,
                        "operation": array_analysis.get("operation"),
                        "confidence": array_analysis.get("confidence"),
                    })

        # Track A 3x: Minimal guidance only when explicitly lite (tests without profile keep full for backward compat)
        is_lite = (self.context.config.get("profile") == "lite") if self.context and "profile" in self.context.config else False
        compact_mode = (
            self._schema_router is not None
            and getattr(self._schema_router, "enabled", False)
            and getattr(self._schema_router, "compact_mode", False)
        )
        if compact_mode:
            # The compact action format is the same in every profile; its prompt must match (and match constrained decoding).
            guidance_text = LITE_COMPACT_GUIDANCE_STRUCTURED if self._structured_edits else LITE_COMPACT_GUIDANCE
            if self._repo_tools:
                guidance_text += REPO_TOOLS_GUIDANCE
            if self._diagnose_before_mutation:
                guidance_text += DIAGNOSE_TARGET_GUIDANCE if self._evidence_extraction else DIAGNOSE_GUIDANCE
            if self._localized_edits:
                edit_lines = SELECTOR_KIND_EDIT_GUIDANCE if self._explicit_selector_kind else LOCALIZED_EDIT_GUIDANCE
                if self._explicit_selector_kind and self._replacement_format_contract:
                    edit_lines = (edit_lines.replace(REPLACEMENT_PLACEHOLDER_PY, REPLACEMENT_CONTRACT_PY)
                                  .replace(REPLACEMENT_PLACEHOLDER_JSON, REPLACEMENT_CONTRACT_JSON))
                guidance_text = guidance_text.replace(LITE_WRITE_LINE, LOCALIZED_WRITE_LINE) + edit_lines
            tool_guidance = json.dumps({"role": "system", "content": guidance_text}, ensure_ascii=False)
        elif is_lite:
            tool_guidance = json.dumps({
                "role": "system",
                "content": (
                    "33k Tools: write_file(path,content) read_file(path) list_directory\n"
                    "JSON: {\"tool_calls\":[{\"function\":{\"name\":\"write_file\",\"arguments\":{\"path\":\"a.txt\",\"content\":\"hi\"}}}]} "
                    "ONE per turn. Check exists first. /math for math. TEMPLATE:todo:index.html expands to full file (use for todo app)."
                )
            }, ensure_ascii=False)
        else:
            tool_guidance = json.dumps({
                 "role": "system",
                 "content": "You are a tool-using agent. You have access to the following tools:\n" +
                 "\n".join([f"- {s['function']['name']}: {s['function'].get('description', '')}" for s in self._tool_schemas]) +
                 "\n\nTool schemas:\n" +
                 "\n".join([json.dumps(s['function'], ensure_ascii=False) for s in self._tool_schemas]) +
                 "\n\nRULES:\n" +
                 "1. When you need to use a tool, respond with ONLY a JSON object in this exact format:\n" +
                 '{"tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "tool_name", "arguments": {"param1": "value1", "param2": "value2"}}}]}\n' +
                 "2. Call EXACTLY ONE tool per response. Do not call multiple tools in a single response.\n" +
                 "3. Do not include any other text, markdown, or code blocks in your response when calling a tool.\n" +
                 "4. For search/find tasks: use list_directory or read_file to check existence. If a file does not exist, report that it does not exist. Do NOT create the file.\n" +
                 "5. After tool results are provided, you may continue the conversation or call another tool if needed.\n" +
                 "6. For mathematical problems (algebra, calculus, limits, matrices), the /math command can be used for exact symbolic computation. Use tools for non-math tasks only.\n" +
                 "7. For simple chat/greetings (e.g., 'Say hello'), respond directly with text and do NOT use tools."
             }, ensure_ascii=False)
        self._system_prompt = tool_guidance
        self.context.append_message("system", tool_guidance)
        if not is_lite and self.context is not None:
            self.context.events.emit("system.message", {"content": tool_guidance})

        if self._targeted_grounding:
            workspace = getattr(self.context.plugins.get("file_tools"), "workspace", None)
            facts, grounded = targeted_grounding(Path(workspace), user_text) if workspace is not None else ([], set())
            self._evidence_paths |= grounded
            if facts:
                note = "Repository facts for names in the task:\n" + "\n".join(facts)
                self.context.append_message("system", note)
                self.context.events.emit(SYSTEM_MESSAGE, {"content": note, "provenance": "targeted_grounding"})
            self.context.events.emit("request.grounded", {"lines": facts, "evidence": sorted(grounded), "chars": sum(len(f) for f in facts)})

        if self._ground_request_paths:
            workspace = getattr(self.context.plugins.get("file_tools"), "workspace", None)
            grounding = ground_request(Path(workspace), user_text) if workspace is not None else []
            if grounding:
                note = "Workspace paths for files named in the request:\n" + "\n".join(grounding)
                self.context.append_message("system", note)
                self.context.events.emit(SYSTEM_MESSAGE, {"content": note, "provenance": "path_grounding"})
            self.context.events.emit("request.grounded", {"lines": grounding, "chars": sum(len(line) for line in grounding)})

        session_id = self._get_session_id()
        for round_idx in range(self.max_rounds):
            self._round = round_idx + 1
            self.context.check_cancelled()
            # P1 FIX: Unified single pruner (was dual: Summarizer.fold + prune). Now single ContextPruner handles both
            # token budget and message count (per-model via core.context calibration), preserves assistant tool_calls
            needs_prune = False
            est_tokens = Summarizer.estimate_tokens(str(self.context.messages))
            if est_tokens > self._token_budget or len(self.context.messages) > self._context_pruner.max_messages:
                needs_prune = True
            if needs_prune:
                pruned = self._context_pruner.prune(self.context.messages, task_state)
                self.context.messages = pruned.messages
                if self.context is not None:
                    self.context.events.emit("context.pruned", {
                        "removed_count": pruned.removed_count,
                        "estimated_tokens_before": pruned.estimated_tokens_before,
                        "estimated_tokens_after": pruned.estimated_tokens_after,
                        "strategy": pruned.strategy,
                        "estimated_tokens": est_tokens,
                    })

            if self._context_builder is not None:
                session_id = self._get_session_id()
                built = self._context_builder.build(session_id, user_text)
                memory_context = built.get("memory", "")
                if memory_context:
                    memory_msg = json.dumps({"role": "system", "content": memory_context}, ensure_ascii=False)
                    self.context.append_message("system", memory_msg)
                    if self.context is not None:
                        self.context.events.emit("memory.augmented", {"session_id": session_id, "context_length": len(memory_context)})
                    self.context.events.emit(SYSTEM_MESSAGE, {"content": memory_context, "provenance": "memory"})

            # P0 FIX: Removed duplicate turn.start emit (was firing per-round + outer). Use turn.round for per-round.
            active_schemas = self._get_active_tool_schemas()
            self.context.events.emit("turn.round", {
                "user_text": user_text,
                "session_id": session_id,
                "round": round_idx,
                "tools_available": [s["function"]["name"] for s in active_schemas],
            })

            # P1 FIX: Harden prompt injections — inject as user with prefix, not system (prevents privilege escalation)
            for injection in list(self.context.prompt_injections):
                safe_content = f"[injected context] {injection.content}"
                self.context.append_message("user", safe_content)
                if self.context is not None:
                    self.context.events.emit(USER_MESSAGE, {"content": safe_content, "provenance": "injection"})
            self.context.prompt_injections.clear()

            # Inject array guidance if facts changed (bounded, controlled API)
            if self._array_guidance and self._array_helper is not None and array_facts_changed and array_facts:
                guidance = self._array_helper.build_guidance(array_facts)
                if guidance:
                    self.context.prompt_injections.append(
                        Message("user", f"[array context] {guidance}")
                    )
                array_facts_changed = False

            if is_lite:
                messages = self._compile_request_envelope(session_id, tool_guidance).messages
            else:
                messages = self.context.messages
            if self.stream:
                chunks = model.stream_chat(messages, active_schemas)
                response = self._consume_stream(chunks, on_stream=on_stream)
            else:
                response = model.chat(messages, active_schemas)

            response, tool_calls = self._interpret_response(response, active_schemas)
            if self._progress_recovery and len(tool_calls) == 1 and getattr(model, "last_done_reason", None) != "length":
                notice = self._missing_path_recovery(tool_calls[0])
                if notice is not None:
                    self._deliver_recovery(session_id, response.content or "", tool_calls, [notice], "repeated_missing_path")
                    continue
            if self._repeat_retry_temperature is not None:
                # Truncated output is never an answer; a call that already failed against unchanged state is never re-executed.
                truncated = getattr(model, "last_done_reason", None) == "length"
                repeated = [] if truncated else self._repeated_failures(tool_calls)
                if truncated or repeated:
                    if truncated:
                        self.context.events.emit("emission.truncated", {"session_id": session_id, "round": round_idx})
                    else:
                        self.context.events.emit("repeat.detected", {"session_id": session_id, "round": round_idx, "calls": repeated})
                    if not hasattr(model, "options"):
                        self._escalate(model, session_id, "repeat_retry_unavailable", repeated, task_state, user_text)
                    saved_options = model.options
                    model.options = {**(saved_options or {}), "temperature": self._repeat_retry_temperature}
                    try:
                        response, tool_calls = self._interpret_response(model.chat(messages, active_schemas), active_schemas)
                    finally:
                        model.options = saved_options
                    self.context.events.emit("model.resampled", {"session_id": session_id, "round": round_idx, "temperature": self._repeat_retry_temperature})
                    if getattr(model, "last_done_reason", None) == "length":
                        self._escalate(model, session_id, "truncated_output", [], task_state, user_text)
                    repeated = self._repeated_failures(tool_calls)
                    if repeated:
                        self._escalate(model, session_id, "repeated_failed_call", repeated, task_state, user_text)

            # P0 FIX: Filter out duplicate-successful tool calls BEFORE appending assistant message.
            # This prevents small models from copying their own prior tool calls in the context.
            duplicate_filtered = False
            if tool_calls:
                filtered_calls = [call for call in tool_calls if not self._is_duplicate_success(call)]

                if (not filtered_calls and self._progress_recovery
                        and all(str(c.get("function", {}).get("name", "")) == "read_file" for c in tool_calls)):
                    # gemma_progress_v1 treatment: answer the repeated read itself, using only facts from the model's own reads.
                    self._duplicate_read_notice(tool_calls)  # same repeat-marking thresholds as the control arm
                    self._deliver_recovery(session_id, response.content or "", tool_calls,
                                           [self._repeated_read_recovery(c) for c in tool_calls], "repeated_successful_read")
                    continue

                if not filtered_calls:
                    # All tool calls are duplicates of previously successful ones: skip execution this round.
                    duplicate_filtered = True
                    if all(str(c.get("function", {}).get("name", "")) in _MUTATING_TOOLS for c in tool_calls):
                        # A repeated mutation that already succeeded: the requested change is in place.
                        for c in tool_calls:  # refused without execution: the mutation version does not increase
                            self._observe_mutation_attempt(str(c.get("function", {}).get("name", "")), self._mutation_version)
                        assistant_content = response.content or "Task already completed."
                        content = (
                            "You already completed the requested task successfully. "
                            "Do not call any tools again. Finish now: reply with a short text message, "
                            "or {\"tool\": \"done\", \"args\": {\"summary\": \"...\"}} if you must reply in JSON."
                        )
                    else:
                        # A repeated read-only call proves nothing was completed (observed: this message used to say
                        # "completed ... Finish now" after a repeated read, and 1B models then declared done).
                        assistant_content = response.content or ""
                        content = self._duplicate_read_notice(tool_calls)
                    guidance = json.dumps({"role": "system", "content": content}, ensure_ascii=False)
                    self.context.append_message("system", guidance)
                    if self.context is not None:
                        self.context.events.emit("system.message", {"content": guidance})

                    # Skip tool execution for this round; model should respond with text on next round.
                    tool_calls = []
                else:
                    tool_calls = filtered_calls
                    assistant_content = response.content
            else:
                assistant_content = response.content

            self.context.append_message("assistant", assistant_content, tool_calls=tool_calls)
            if self.context is not None:
                self.context.events.emit("assistant.message", {"content": assistant_content, "tool_calls": tool_calls})

            if duplicate_filtered:
                # Skip tool execution for this round; model should respond with text on next round.
                continue

            if not tool_calls and self._parse_retry_count < 2 and response.content:
                looks_like_tool_use = any(name.lower() in response.content.lower() for name in [s["function"]["name"] for s in self._tool_schemas])
                if looks_like_tool_use:
                    self._parse_retry_count += 1
                    guidance = json.dumps({
                        "role": "system",
                        "content": "You did not emit a tool call. You MUST respond with a JSON object containing tool_calls. Available tools: " +
                        ", ".join([s["function"]["name"] for s in self._tool_schemas]) +
                        ". Example: {\"tool_calls\": [{\"id\": \"call_1\", \"type\": \"function\", \"function\": {\"name\": \"write_file\", \"arguments\": {\"path\": \"a.txt\", \"content\": \"hello\"}}}]}"
                    }, ensure_ascii=False)
                    self.context.append_message("system", guidance)
                    if self.context is not None:
                        self.context.events.emit("system.message", {"content": guidance})
                    continue

            if not tool_calls and self._evidence_gated_completion:
                unsupported = self._unsupported_declarations(response.content or "")
                if unsupported:
                    self._evidence_gate_rejections += 1
                    self.context.events.emit("done.rejected", {"session_id": session_id, "round": self._round, "reason": "unsupported_declaration", "paths": unsupported})
                    if self._evidence_gate_rejections >= 2:
                        self._escalate(model, session_id, "unsupported_declaration", unsupported, task_state, user_text)
                    listed = "; ".join(unsupported)
                    check = (f"[completion check] No evidence for: {listed}. A path you name must exist and must have been "
                             "located or inspected in this task (repository facts, a repository tool result, or read). "
                             "Locate or inspect it before finishing.")
                    self.context.append_message("user", check)
                    self.context.events.emit(USER_MESSAGE, {"content": check, "provenance": "evidence_gate"})
                    continue

            if not tool_calls and self._require_read_named_files:
                unmet = self._unmet_named_file_reads()
                if unmet:
                    self._done_gate_rejections += 1
                    self.context.events.emit("done.rejected", {"session_id": session_id, "round": self._round, "unread": unmet})
                    if self._done_gate_rejections >= 2:
                        self._escalate(model, session_id, "completion_prerequisites_unmet", [" | ".join(a) for a in unmet], task_state, user_text)
                    listed = "; ".join(" or ".join(alternatives) for alternatives in unmet)
                    check = f"[completion check] The task names files you have not read yet: {listed}. Read them before finishing."
                    self.context.append_message("user", check)
                    self.context.events.emit(USER_MESSAGE, {"content": check, "provenance": "completion_check"})
                    continue

            if not tool_calls and self._completion_latch_enabled and self._latched:
                self._latch_rejections += 1
                self.context.events.emit("done.rejected", {"session_id": session_id, "round": self._round, "reason": "mutation_not_applied"})
                if self._latch_rejections >= 2:
                    self._emit_latch("escalated", "completion_after_failed_mutation")
                    self._escalate(model, session_id, "completion_after_failed_mutation", [], task_state, user_text)
                self._emit_latch("blocked", "mutation_not_applied")
                check = "[completion check] Under this condition, completion is unavailable: the most recent attempted change was not applied."
                self.context.append_message("user", check)
                self.context.events.emit(USER_MESSAGE, {"content": check, "provenance": "completion_latch"})
                continue

            if not tool_calls:
                # App Completion Verifier gate: when the model declares completion
                # (text response, no tool calls), run deterministic verification before
                # allowing the agent to return. If verification fails, inject feedback
                # and continue to the next round.
                if self._app_verifier is not None:
                    # Define criteria on first completion attempt
                    if not task_state.get("verifier_criteria_defined"):
                        self._app_verifier.define_criteria(user_text, task_state)
                        task_state["verifier_criteria_defined"] = True

                    workspace = self.context.config.get("workspace", ".") if self.context else "."
                    all_passed = self._app_verifier.verify_completion(workspace, task_state)

                    if not all_passed:
                        feedback = self._app_verifier.get_feedback()
                        # Inject as user message per injection-hardening invariant
                        self.context.append_message("user", f"[verification feedback] {feedback}")
                        if self.context is not None:
                            self.context.events.emit(USER_MESSAGE, {"content": f"[verification feedback] {feedback}", "provenance": "verifier"})
                            self.context.events.emit("verification.failed", {
                                "session_id": session_id,
                                "failed_count": len([r for r in self._app_verifier._results if not r.passed]),
                            })
                        continue  # Keep working — don't return yet

                    # All criteria passed
                    if self.context is not None:
                        self.context.events.emit("verification.passed", {
                            "session_id": session_id,
                            "total_criteria": len(self._app_verifier._criteria),
                        })

                # Mark session outcome for training data collection
                self._mark_session_outcome(user_text, session_id, task_state)

                self.context.events.emit("turn.end", {"final_result": response.content, "session_id": session_id})
                return response.content

            failed_this_round: list[str] = []
            successful_results: list[str] = []
            for call in tool_calls:
                self.context.check_cancelled()
                fn = call.get("function", {})
                if not isinstance(fn, dict):
                    continue
                name = str(fn.get("name", ""))
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                call_sig = self._sig(call)
                version_before = self._mutation_version

                if self._blocked(call_sig):
                    result = json.dumps({
                        "error": f"Duplicate failed call detected: {name} with same arguments. Aborting to prevent infinite loop.",
                        "tool": name,
                        "arguments": args,
                    }, ensure_ascii=False)
                    self.context.append_message("tool", result, tool_name=name)
                    self.context.events.emit("tool.result", {
                        "tool": name,
                        "arguments": args,
                        "result": result,
                        "success": False,
                    })
                    failed_this_round.append(name)
                    self._observe_mutation_attempt(name, version_before)
                    continue

                # 3x 100% success: block duplicate successful calls (prevents 1.5B loop on 'Say hello' -> write_file hello.txt repeatedly)
                if self._is_duplicate_success(call):
                    result = json.dumps({
                        "error": f"Tool '{name}' already succeeded with same arguments. Do not repeat.",
                        "tool": name,
                        "arguments": args,
                        "duplicate": True,
                    }, ensure_ascii=False)
                    self.context.append_message("tool", result, tool_name=name)
                    self.context.events.emit("tool.result", {
                        "tool": name,
                        "arguments": args,
                        "result": result,
                        "success": False,
                    })
                    # Guide model to chat instead of re-hallucinating tool
                    already_done = json.dumps({"role":"system","content": f"Tool '{name}' already succeeded. Do not call it again with same arguments. For simple chat like 'Say hello', respond directly without tools."}, ensure_ascii=False)
                    self.context.append_message("system", already_done)
                    self.context.events.emit(SYSTEM_MESSAGE, {"content": already_done})
                    failed_this_round.append(name)
                    self._observe_mutation_attempt(name, version_before)
                    continue

                try:
                    start_time = time.perf_counter()
                    # Optional ArrayHelper action review for write-related tools
                    if self._array_guidance and self._array_helper is not None and name == "write_file" and array_facts:
                        review = self._array_helper.review_action(name, args, array_facts)
                        if review["status"] == "warn" and self.context is not None:
                            self.context.events.emit("array.action.reviewed", {
                                "session_id": session_id,
                                "status": "warn",
                                "reason": review["reason"],
                            })
                            # Inject bounded warning guidance
                            warning = f"Array helper: {review['reason']}"
                            self.context.prompt_injections.append(
                                Message("user", f"[array context] {warning}")
                            )

                    result = self._execute_tool_call(call)
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    self._log_tool_decision(name, args, result, success=True, duration_ms=duration_ms)
                except Exception as exc:
                    result = json.dumps({"error": str(exc), "tool": name, "arguments": args}, ensure_ascii=False)
                    failed_this_round.append(name)
                    self._log_tool_decision(name, args, result, success=False, error=str(exc))
                    # Guide model away from non-existent tools after first failure
                    if "Unknown tool" in str(exc):
                        guidance = json.dumps({
                            "role": "system",
                            "content": f"Tool '{name}' does not exist. Respond with text instead of tools.",
                        }, ensure_ascii=False)
                        self.context.append_message("system", guidance)
                        if self.context is not None:
                            self.context.events.emit("system.message", {"content": guidance})
                    recovery = self.context.plugins.get("error_recovery")
                    if recovery is not None:
                        failure_type = self._classify_failure(exc, {"tool_name": name, "arguments": args}).value
                        action = recovery.handle_failure(failure_type, {
                            "tool_name": name,
                            "arguments": args,
                            "result": result,
                        })
                        if action.action == "retry":
                            try:
                                result = self._execute_tool_call(call)
                                failed_this_round.remove(name)
                            except Exception:
                                pass
                        elif action.action == "fallback":
                            result = json.dumps({
                                "error": f"{name} failed after retries. Fallback not yet implemented.",
                                "tool": name,
                                "arguments": args,
                             }, ensure_ascii=False)
                    self.context.append_message("tool", result, tool_name=name)
                    self.context.events.emit("tool.result", {
                        "tool": name,
                        "arguments": args,
                        "result": result,
                        "success": False,
                    })
                    self._observe_mutation_attempt(name, version_before)
                else:
                    self._successful_calls.add(call_sig)
                    # Version after this call's own effect, so a read is "already seen" only while nothing has changed since.
                    self._success_versions[call_sig] = self._mutation_version
                    # Compress tool results for compact-schema mode to save context tokens
                    if self._schema_router is not None and getattr(self._schema_router, "compact_mode", False):
                        result = self._schema_router.compress_tool_output(name, result)
                    self.context.append_message("tool", result, tool_name=name)
                    if name not in task_state["tools_used"]:
                        task_state["tools_used"].append(name)
                    if name == "write_file":
                        path = args.get("path", "")
                        if path and path not in task_state["files_touched"]:
                            task_state["files_touched"].append(path)

                    self.context.events.emit("tool.result", {
                        "tool": name,
                        "arguments": args,
                        "result": result,
                        "success": True,
                    })
                    successful_results.append(result)
                    self._observe_mutation_attempt(name, version_before)

                    # Optional ArrayHelper context analysis after read_file
                    if self._array_helper is not None and name == "read_file":
                        context_analysis = self._array_helper.analyze_context(
                            result[:self._array_helper._MAX_EXCERPT_LENGTH]
                        )
                        if context_analysis.get("confidence") in ("medium", "high"):
                            merged_facts = {**array_facts, **context_analysis}
                            if self._array_helper.update_facts(merged_facts):
                                array_facts = merged_facts
                                array_facts_changed = True
                                if self.context is not None:
                                    self.context.events.emit("array.context.updated", {
                                        "session_id": session_id,
                                        "representation": context_analysis.get("representation"),
                                        "shape": context_analysis.get("shape"),
                                        "confidence": context_analysis.get("confidence"),
                                    })

            # Pre-existing: continue until model emits no tool_calls (not auto-done after first write) — enables multi-file app builds within 33k
            if len(failed_this_round) > 1 and self._replan_count < 2:
                replan_msg = RepairMessageBuilder.global_replan(failed_this_round)
                self.context.append_message("system", replan_msg)
                if self.context is not None:
                    self.context.events.emit(SYSTEM_MESSAGE, {"content": replan_msg})
                    self.context.events.emit("replan", {"failed_tools": failed_this_round, "replan_count": self._replan_count})

        self.context.events.emit("turn.end", {"final_result": "", "error": "max_rounds_exceeded", "session_id": session_id})

        # Mark session failure for training data collection
        if self.context is not None:
            self._mark_session_outcome_failure(user_text, session_id, task_state)

        raise ToolError(f"Agent exceeded maximum tool-call rounds ({self.max_rounds}).")

    def _mark_session_outcome(self, user_text: str, session_id: str, task_state: dict[str, Any]) -> None:
        """Mark the session outcome for training data collection.

        Called when the agent successfully completes a task. If AppVerifier
        is present and passed, outcome is "success". Otherwise "success"
        (no verifier = trust model completion).
        """
        if self.context is None:
            return
        event_logger = self.context.plugins.get("event_logger")
        if event_logger is None or not hasattr(event_logger, "mark_session_outcome"):
            return

        # Determine app type from user request
        request_lower = user_text.lower()
        if any(kw in request_lower for kw in {"todo", "task list"}):
            app_type = "todo"
        elif any(kw in request_lower for kw in {"auth", "login", "signup"}):
            app_type = "auth"
        elif any(kw in request_lower for kw in {"crud", "api", "endpoint"}):
            app_type = "crud"
        elif any(kw in request_lower for kw in {"calculat", "math", "sum", "total"}):
            app_type = "calculator"
        elif any(kw in request_lower for kw in {"dashboard", "chart"}):
            app_type = "dashboard"
        else:
            app_type = "generic"

        metadata: dict[str, Any] = {
            "files_created": task_state.get("files_touched", []),
            "tools_used": task_state.get("tools_used", []),
            "app_type": app_type,
            "model_turns": self._round,
        }
        event_logger.mark_session_outcome("success", metadata)

    def _mark_session_outcome_failure(self, user_text: str, session_id: str, task_state: dict[str, Any]) -> None:
        """Mark the session as failed for training data collection.

        Called when the agent fails to complete a task (e.g., max rounds exceeded).
        """
        if self.context is None:
            return
        event_logger = self.context.plugins.get("event_logger")
        if event_logger is None or not hasattr(event_logger, "mark_session_outcome"):
            return

        request_lower = user_text.lower()
        if any(kw in request_lower for kw in {"todo", "task list"}):
            app_type = "todo"
        elif any(kw in request_lower for kw in {"auth", "login", "signup"}):
            app_type = "auth"
        elif any(kw in request_lower for kw in {"crud", "api", "endpoint"}):
            app_type = "crud"
        elif any(kw in request_lower for kw in {"calculat", "math", "sum", "total"}):
            app_type = "calculator"
        elif any(kw in request_lower for kw in {"dashboard", "chart"}):
            app_type = "dashboard"
        else:
            app_type = "generic"

        metadata: dict[str, Any] = {
            "files_created": task_state.get("files_touched", []),
            "tools_used": task_state.get("tools_used", []),
            "app_type": app_type,
            "model_turns": self._round,
            "failure_reason": "max_rounds_exceeded",
        }
        event_logger.mark_session_outcome("failure", metadata)
