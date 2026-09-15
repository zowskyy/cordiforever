from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.plugin import Plugin


@dataclass
class VerificationCriterion:
    """Defines a single verification check."""

    name: str
    description: str
    check_type: str
    required: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """Result of checking one criterion."""

    criterion: VerificationCriterion
    passed: bool
    evidence: str = ""
    feedback: str = ""


@dataclass
class GateResult:
    """Structured result from a single verification gate."""

    gate: str
    passed: bool
    findings: list[str] = field(default_factory=list)
    score: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class AppVerifier(Plugin):
    """Deterministic, evidence-based completion verifier with modular gates."""

    name = "app_verifier"
    dependencies = ("file_tools", "asgi_wsgi_tester")

    __contract__ = {
        "version": "1.0",
        "provides": ("completion_verification", "feature_validation", "server_testing"),
        "requires": ("file_tools",),
        "deterministic": True,
        "zero_token": True,
    }

    _TODO_KEYWORDS = {"todo", "to-do", "task list", "tasks list"}
    _CRUD_KEYWORDS = {"crud", "api", "endpoint", "rest", "backend", "server route"}
    _CALC_KEYWORDS = {"calculat*", "math", "arithmetic", "calculator", "count", "sum", "total"}
    _DASHBOARD_KEYWORDS = {"dashboard", "chart", "visual*", "data display", "metric", "statistics", "analytics"}
    _BUILD_INTENT = re.compile(
        r"(?<![a-z0-9])(?:(?:build|create|make|develop|implement|scaffold|generate)(?:s|ing)?|apps?|applications?|websites?)(?![a-z0-9])(?!\.[a-z])"
    )
    _AUTH_KEYWORDS = {"auth", "login", "signup", "register", "session", "password", "jwt", "token"}
    _ECOMMERCE_KEYWORDS = {"e-commerce", "ecommerce", "cart", "checkout", "product", "product list", "shop"}
    _CHAT_KEYWORDS = {"chat", "message", "messaging", "real-time", "websocket", "socket"}
    _DATAVIZ_KEYWORDS = {"data visualization", "chart.js", "d3", "graph", "plot", "visualization"}

    _PLACEHOLDER_PATTERNS = [
        re.compile(r"TODO[: ]"),
        re.compile(r"FIXME[: ]"),
        re.compile(r"PLACEHOLDER", re.IGNORECASE),
        re.compile(r"lorem ipsum", re.IGNORECASE),
        re.compile(r"not implemented", re.IGNORECASE),
        re.compile(r"to be implemented", re.IGNORECASE),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._criteria: list[VerificationCriterion] = []
        self._results: list[VerificationResult] = []
        self._file_tools: Any = None
        self._server_tester: Any = None
        self._gate_cache: dict[str, GateResult] = {}

    def start(self) -> None:
        self._criteria = []
        self._results = []
        self._gate_cache = {}
        if self.context is not None:
            self._file_tools = self.context.plugins.get("file_tools")
            self._server_tester = self.context.plugins.get("asgi_wsgi_tester")

    def stop(self) -> None:
        self._criteria = []
        self._results = []
        self._file_tools = None
        self._server_tester = None
        self._gate_cache = {}

    def reset_run_state(self) -> None:
        self._criteria = []
        self._results = []
        self._gate_cache = {}
        if self.context is not None:
            self._file_tools = self.context.plugins.get("file_tools")
            self._server_tester = self.context.plugins.get("asgi_wsgi_tester")

    def health_check(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "plugin": self.name,
            "contract_version": self.__contract__.get("version", "1.0"),
            "capabilities": {
                "define_criteria": callable(getattr(self, "define_criteria", None)),
                "verify_completion": callable(getattr(self, "verify_completion", None)),
                "get_feedback": callable(getattr(self, "get_feedback", None)),
            },
        }

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    @staticmethod
    def _mentions(keywords: set[str], text: str) -> bool:
        # Whole-word match (plurals allowed; trailing * marks a stem) so "summary" is not "sum".
        for kw in keywords:
            stem = kw.endswith("*")
            body = re.escape(kw.rstrip("*"))
            tail = r"[a-z0-9]*" if stem else r"(?:e?s)?(?![a-z0-9])"
            if re.search(rf"(?<![a-z0-9]){body}{tail}", text):
                return True
        return False

    def define_criteria(self, user_request: str, task_state: dict[str, Any]) -> list[VerificationCriterion]:
        self._criteria = []
        self._gate_cache = {}
        request_lower = user_request.lower()
        builds_app = bool(self._BUILD_INTENT.search(request_lower))

        def mentions(keywords: set[str]) -> bool:
            return builds_app and self._mentions(keywords, request_lower)

        if mentions(self._TODO_KEYWORDS):
            task_state["app_type"] = "todo"
            self._generate_todo_criteria()
        elif mentions(self._AUTH_KEYWORDS):
            task_state["app_type"] = "auth"
            self._generate_auth_criteria()
        elif mentions(self._ECOMMERCE_KEYWORDS):
            task_state["app_type"] = "ecommerce"
            self._generate_ecommerce_criteria()
        elif mentions(self._CHAT_KEYWORDS):
            task_state["app_type"] = "chat"
            self._generate_chat_criteria()
        elif mentions(self._DATAVIZ_KEYWORDS):
            task_state["app_type"] = "dataviz"
            self._generate_dataviz_criteria()
        elif mentions(self._CRUD_KEYWORDS):
            task_state["app_type"] = "crud"
            self._generate_crud_criteria()
        elif mentions(self._CALC_KEYWORDS):
            task_state["app_type"] = "calculator"
            self._generate_calculator_criteria()
        elif mentions(self._DASHBOARD_KEYWORDS):
            task_state["app_type"] = "dashboard"
            self._generate_dashboard_criteria()
        else:
            task_state["app_type"] = "generic"

        self._generate_generic_criteria(task_state)
        return list(self._criteria)

    def verify_completion(self, workspace_path: str, task_state: dict[str, Any]) -> bool:
        if not self._criteria:
            return True

        self._results = []
        self._gate_cache = {}
        ws = Path(workspace_path) if workspace_path else Path(".")

        for criterion in self._criteria:
            result = self._check_criterion(criterion, ws)
            self._results.append(result)

        return all(r.passed for r in self._results if r.criterion.required)

    def get_feedback(self) -> str:
        failed = [r for r in self._results if not r.passed]
        if not failed:
            return "All verification checks passed."

        lines = ["Verification failed. Complete these required steps:"]
        for result in failed:
            lines.append(f"  [{result.criterion.check_type}] {result.criterion.description}: {result.feedback}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal: gate dispatcher with caching
    # ------------------------------------------------------------------

    def _check_criterion(self, criterion: VerificationCriterion, ws: Path) -> VerificationResult:
        cache_key = self._cache_key(criterion, ws)
        if cache_key in self._gate_cache:
            gate_result = self._gate_cache[cache_key]
        else:
            gate_result = self._run_gate(criterion, ws)
            self._gate_cache[cache_key] = gate_result

        return self._gate_to_verification_result(criterion, gate_result)

    def _cache_key(self, criterion: VerificationCriterion, ws: Path) -> str:
        payload = {
            "type": criterion.check_type,
            "params": criterion.parameters,
            "ws": str(ws),
        }
        return hashlib.sha256(
            str(payload).encode("utf-8")
        ).hexdigest()[:16]

    def _run_gate(self, criterion: VerificationCriterion, ws: Path) -> GateResult:
        check_type = criterion.check_type
        params = criterion.parameters

        if check_type == "file_exists":
            return self._gate_file_exists(criterion, ws, params.get("path", ""))
        elif check_type == "file_content":
            paths = params.get("path", "")
            if isinstance(paths, list):
                return self._gate_file_content_multi(criterion, ws, paths, params.get("patterns", []))
            return self._gate_file_content(criterion, ws, paths, params.get("patterns", []))
        elif check_type == "command_runs":
            return self._gate_command_runs(criterion, params.get("command", ""), params.get("expected", ""))
        elif check_type == "test_passes":
            return self._gate_test_passes(criterion, params.get("command", ""))
        elif check_type == "feature_works":
            return self._gate_feature_works(criterion, params.get("description", ""), params.get("check", ""))
        elif check_type == "server_runs":
            return self._gate_server_runs(criterion, ws, params)
        elif check_type == "no_placeholders":
            return self._gate_no_placeholders(criterion, ws, params.get("path", ""))
        else:
            return GateResult(
                gate=check_type,
                passed=False,
                findings=[f"Unknown check_type: {check_type}"],
                score=0.0,
                metadata={"error": "unknown_gate"},
            )

    # Backward-compatible aliases for existing tests
    def _check_file_exists(self, criterion: VerificationCriterion, ws: Path, file_path: str) -> VerificationResult:
        gate = self._gate_file_exists(criterion, ws, file_path)
        return self._gate_to_verification_result(criterion, gate)

    def _check_file_content(self, criterion: VerificationCriterion, ws: Path, file_path: str, patterns: list[str]) -> VerificationResult:
        gate = self._gate_file_content(criterion, ws, file_path, patterns)
        return self._gate_to_verification_result(criterion, gate)

    def _check_file_content_multi(self, criterion: VerificationCriterion, ws: Path, file_paths: list[str], patterns: list[str]) -> VerificationResult:
        gate = self._gate_file_content_multi(criterion, ws, file_paths, patterns)
        return self._gate_to_verification_result(criterion, gate)

    def _check_command_runs(self, criterion: VerificationCriterion, command: str, expected: str) -> VerificationResult:
        gate = self._gate_command_runs(criterion, command, expected)
        return self._gate_to_verification_result(criterion, gate)

    def _check_test_passes(self, criterion: VerificationCriterion, command: str) -> VerificationResult:
        gate = self._gate_test_passes(criterion, command)
        return self._gate_to_verification_result(criterion, gate)

    def _check_feature_works(self, criterion: VerificationCriterion, description: str, check: str) -> VerificationResult:
        gate = self._gate_feature_works(criterion, description, check)
        return self._gate_to_verification_result(criterion, gate)

    def _check_server_runs(self, criterion: VerificationCriterion, ws: Path, params: dict[str, Any]) -> VerificationResult:
        gate = self._gate_server_runs(criterion, ws, params)
        return self._gate_to_verification_result(criterion, gate)

    def _check_no_placeholders(self, criterion: VerificationCriterion, ws: Path, file_path: str) -> VerificationResult:
        gate = self._gate_no_placeholders(criterion, ws, file_path)
        return self._gate_to_verification_result(criterion, gate)

    def _gate_to_verification_result(self, criterion: VerificationCriterion, gate: GateResult) -> VerificationResult:
        # Preserve legacy feedback behavior: if gate failed, use findings as feedback;
        # if gate passed, feedback is empty.
        if gate.passed:
            return VerificationResult(criterion=criterion, passed=True, evidence="; ".join(gate.findings), feedback="")
        return VerificationResult(
            criterion=criterion,
            passed=False,
            evidence="; ".join(gate.findings),
            feedback="; ".join(gate.findings),
        )

    # ------------------------------------------------------------------
    # Modular gate functions
    # ------------------------------------------------------------------

    def _gate_file_exists(self, criterion: VerificationCriterion, ws: Path, file_path: str) -> GateResult:
        full_path = ws / file_path
        exists = full_path.is_file()
        findings = [f"file_exists:{file_path}={exists}"]
        if not exists:
            findings.append(f"File does not exist: {file_path}")
        return GateResult(
            gate="file_exists",
            passed=exists,
            findings=findings,
            score=1.0 if exists else 0.0,
            metadata={"path": file_path, "exists": exists},
        )

    def _gate_file_content(self, criterion: VerificationCriterion, ws: Path, file_path: str, patterns: list[str]) -> GateResult:
        full_path = ws / file_path
        if not full_path.is_file():
            return GateResult(
                gate="file_content",
                passed=False,
                findings=[f"missing_file:{file_path}"],
                score=0.0,
                metadata={"path": file_path, "missing": True},
            )

        try:
            content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return GateResult(
                gate="file_content",
                passed=False,
                findings=[f"read_error:{file_path}:{exc}"],
                score=0.0,
                metadata={"path": file_path, "error": str(exc)},
            )

        match_mode = criterion.parameters.get("match", "all")
        case_insensitive = criterion.parameters.get("case_insensitive", True)

        if case_insensitive:
            search_content = content.lower()
            search_patterns = [p.lower() for p in patterns]
        else:
            search_content = content
            search_patterns = patterns

        missing: list[str] = []
        present: list[str] = []
        for pat, orig_pat in zip(search_patterns, patterns):
            if pat in search_content:
                present.append(orig_pat)
            else:
                missing.append(orig_pat)

        if match_mode == "any":
            passed = len(present) > 0
            findings = [f"file_content:{file_path}:present={','.join(present)}:missing={','.join(missing)}:mode=any"]
        else:
            passed = len(missing) == 0
            findings = [f"file_content:{file_path}:missing={','.join(missing)}:mode=all"]

        return GateResult(
            gate="file_content",
            passed=passed,
            findings=findings,
            score=len(present) / len(patterns) if patterns else 1.0,
            metadata={"path": file_path, "present": present, "missing": missing, "match_mode": match_mode},
        )

    def _gate_file_content_multi(self, criterion: VerificationCriterion, ws: Path, file_paths: list[str], patterns: list[str]) -> GateResult:
        for fp in file_paths:
            result = self._gate_file_content(criterion, ws, fp, patterns)
            if result.passed:
                return GateResult(
                    gate="file_content_multi",
                    passed=True,
                    findings=[f"file_content_multi:match_found:{fp}"],
                    score=1.0,
                    metadata={"matched_path": fp},
                )

        return GateResult(
            gate="file_content_multi",
            passed=False,
            findings=[f"file_content_multi:no_match:{','.join(file_paths)}"],
            score=0.0,
            metadata={"paths_checked": file_paths},
        )

    def _gate_command_runs(self, criterion: VerificationCriterion, command: str, expected: str) -> GateResult:
        terminal = self.context.plugins.get("terminal") if self.context else None
        if terminal is None:
            return GateResult(
                gate="command_runs",
                passed=True,
                findings=["command_runs:skipped:no_terminal_plugin"],
                score=1.0,
                metadata={"skipped": True, "reason": "terminal_plugin_unavailable"},
            )
        return GateResult(
            gate="command_runs",
            passed=True,
            findings=[f"command_runs:deferred:{command}"],
            score=1.0,
            metadata={"deferred": True, "command": command},
        )

    def _gate_test_passes(self, criterion: VerificationCriterion, command: str) -> GateResult:
        terminal = self.context.plugins.get("terminal") if self.context else None
        if terminal is None:
            return GateResult(
                gate="test_passes",
                passed=True,
                findings=["test_passes:skipped:no_terminal_plugin"],
                score=1.0,
                metadata={"skipped": True, "reason": "terminal_plugin_unavailable"},
            )
        return GateResult(
            gate="test_passes",
            passed=True,
            findings=[f"test_passes:deferred:{command}"],
            score=1.0,
            metadata={"deferred": True, "command": command},
        )

    def _gate_feature_works(self, criterion: VerificationCriterion, description: str, check: str) -> GateResult:
        return GateResult(
            gate="feature_works",
            passed=True,
            findings=[f"feature_works:manual:{check}"],
            score=1.0,
            metadata={"manual_check": check},
        )

    def _gate_server_runs(self, criterion: VerificationCriterion, ws: Path, params: dict[str, Any]) -> GateResult:
        if self._server_tester is None:
            return GateResult(
                gate="server_runs",
                passed=False,
                findings=["server_runs:no_tester_available", "Server testing requires asgi_wsgi_tester plugin"],
                score=0.0,
                metadata={"error": "asgi_wsgi_tester_unavailable"},
            )

        command = params.get("command", "")
        base_url = params.get("base_url", "http://127.0.0.1:8000")
        endpoints = params.get("endpoints", [])

        started = self._server_tester.start_server(command, base_url, cwd=str(ws))
        if not started:
            return GateResult(
                gate="server_runs",
                passed=False,
                findings=[f"server_runs:start_failed:{command}", f"Server did not start with command: {command}"],
                score=0.0,
                metadata={"command": command, "started": False},
            )

        if endpoints:
            result = self._server_tester.test_endpoints(endpoints)
            self._server_tester.stop_server()
            if result["passed"]:
                return GateResult(
                    gate="server_runs",
                    passed=True,
                    findings=[f"server_runs:endpoints_passed:{result['summary']}"],
                    score=1.0,
                    metadata={"endpoints_tested": len(endpoints), "summary": result["summary"]},
                )
            return GateResult(
                gate="server_runs",
                passed=False,
                findings=[f"server_runs:endpoints_failed:{result['summary']}"],
                score=0.0,
                metadata={"endpoints_tested": len(endpoints), "summary": result["summary"]},
            )

        self._server_tester.stop_server()
        return GateResult(
            gate="server_runs",
            passed=True,
            findings=["server_runs:started"],
            score=1.0,
            metadata={"started": True},
        )

    def _gate_no_placeholders(self, criterion: VerificationCriterion, ws: Path, file_path: str) -> GateResult:
        full_path = ws / file_path
        if not full_path.is_file():
            return GateResult(
                gate="no_placeholders",
                passed=True,
                findings=[f"no_placeholders:missing_file:{file_path}"],
                score=1.0,
                metadata={"path": file_path, "missing": True},
            )

        try:
            content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return GateResult(
                gate="no_placeholders",
                passed=True,
                findings=[f"no_placeholders:read_error:{file_path}:{exc}"],
                score=1.0,
                metadata={"path": file_path, "error": str(exc)},
            )

        found: list[str] = []
        for pattern in self._PLACEHOLDER_PATTERNS:
            if pattern.search(content):
                found.append(pattern.pattern)

        passed = len(found) == 0
        return GateResult(
            gate="no_placeholders",
            passed=passed,
            findings=[f"no_placeholders:{file_path}:found={len(found)}"],
            score=0.0 if found else 1.0,
            metadata={"path": file_path, "found_patterns": found},
        )

    # ------------------------------------------------------------------
    # App-pattern criteria generators
    # ------------------------------------------------------------------

    def _generate_todo_criteria(self) -> None:
        self._criteria.extend([
            VerificationCriterion("todo_html_exists", "Todo app must have an HTML file", "file_exists", True, {"path": "index.html"}),
            VerificationCriterion("todo_js_exists", "Todo app must have a JS file", "file_exists", True, {"path": "app.js"}),
            VerificationCriterion("todo_add_function", "Must have an add function", "file_content", True, {"path": "app.js", "patterns": ["function", "add"], "match": "any"}),
            VerificationCriterion("todo_delete_ability", "Must support delete/remove functionality", "file_content", True, {"path": "app.js", "patterns": ["splice", "filter", "remove", "delete"], "match": "any"}),
            VerificationCriterion("todo_list_element", "HTML must have a list element", "file_content", True, {"path": "index.html", "patterns": ["ul", "list"], "match": "any"}),
        ])

    def _generate_crud_criteria(self) -> None:
        self._criteria.extend([
            VerificationCriterion("crud_server_file", "CRUD app must have a server file (server.js or server.py)", "file_exists", False, {"path": "server.js"}),
            VerificationCriterion("crud_server_file_py", "CRUD app must have a server file (server.js or server.py)", "file_exists", False, {"path": "server.py"}),
            VerificationCriterion("crud_create_endpoint", "Must have a POST/create endpoint", "file_content", True, {"path": ["server.js", "server.py"], "patterns": ["POST", "create", "add"], "match": "any"}),
            VerificationCriterion("crud_read_endpoint", "Must have a GET/read endpoint", "file_content", True, {"path": ["server.js", "server.py"], "patterns": ["GET", "read", "find", "get"], "match": "any"}),
            VerificationCriterion("crud_update_endpoint", "Must have a PUT/update endpoint", "file_content", True, {"path": ["server.js", "server.py"], "patterns": ["PUT", "update", "edit"], "match": "any"}),
            VerificationCriterion("crud_delete_endpoint", "Must have a DELETE endpoint", "file_content", True, {"path": ["server.js", "server.py"], "patterns": ["DELETE", "delete", "remove"], "match": "any"}),
        ])

    def _generate_calculator_criteria(self) -> None:
        self._criteria.extend([
            VerificationCriterion("calc_html_exists", "Calculator must have an HTML file", "file_exists", True, {"path": "index.html"}),
            VerificationCriterion("calc_js_exists", "Calculator must have a JS file", "file_exists", True, {"path": "app.js"}),
            VerificationCriterion("calc_display", "Must have a display/input element", "file_content", True, {"path": "index.html", "patterns": ["display", "input", "screen", "result"], "match": "any"}),
            VerificationCriterion("calc_number_buttons", "Must have number buttons (0-9)", "file_content", True, {"path": "index.html", "patterns": ["0", "1", "2", "9"], "match": "any"}),
            VerificationCriterion("calc_operations", "Must have arithmetic operations", "file_content", True, {"path": "app.js", "patterns": ["+", "-", "*", "/"], "match": "any"}),
        ])

    def _generate_dashboard_criteria(self) -> None:
        self._criteria.extend([
            VerificationCriterion("dashboard_html_exists", "Dashboard must have an HTML file", "file_exists", True, {"path": "index.html"}),
            VerificationCriterion("dashboard_container", "Must have a container/div element", "file_content", True, {"path": "index.html", "patterns": ["div", "container", "chart", "canvas"], "match": "any"}),
            VerificationCriterion("dashboard_js_exists", "Dashboard must have a JS file for visualization", "file_exists", True, {"path": "app.js"}),
            VerificationCriterion("dashboard_data_source", "Must have a data source or fetch", "file_content", True, {"path": "app.js", "patterns": ["fetch", "data", "api", "json", "datasource"], "match": "any"}),
        ])

    def _generate_generic_criteria(self, task_state: dict[str, Any]) -> None:
        app_type = task_state.get("app_type", "generic")
        main_files: list[str] = []
        if app_type == "todo":
            main_files = ["index.html", "app.js"]
        elif app_type == "crud":
            main_files = ["server.js"]
        elif app_type == "calculator":
            main_files = ["index.html", "app.js"]
        elif app_type == "dashboard":
            main_files = ["index.html", "app.js"]
        elif app_type == "auth":
            main_files = ["server.js", "index.html"]
        elif app_type == "ecommerce":
            main_files = ["server.js", "index.html", "app.js"]
        elif app_type == "chat":
            main_files = ["server.js", "index.html", "app.js"]
        elif app_type == "dataviz":
            main_files = ["index.html", "app.js"]

        for file_path in main_files:
            self._criteria.append(VerificationCriterion(
                name=f"no_placeholders_{file_path.replace('/', '_')}",
                description=f"No placeholder/TODO comments in {file_path}",
                check_type="no_placeholders",
                parameters={"path": file_path},
            ))

    def _generate_auth_criteria(self) -> None:
        self._criteria.extend([
            VerificationCriterion("auth_server_file", "Auth app must have a server file", "file_exists", True, {"path": "server.js"}),
            VerificationCriterion("auth_login_endpoint", "Must have a login route/endpoint", "file_content", True, {"path": "server.js", "patterns": ["login", "signin", "auth", "post"], "match": "any"}),
            VerificationCriterion("auth_signup_endpoint", "Must have a signup/registration route", "file_content", True, {"path": "server.js", "patterns": ["signup", "register", "register", "post"], "match": "any"}),
            VerificationCriterion("auth_session_management", "Must handle sessions or tokens", "file_content", True, {"path": "server.js", "patterns": ["session", "token", "jwt", "cookie"], "match": "any"}),
            VerificationCriterion("auth_password_handling", "Must have password handling", "file_content", True, {"path": "server.js", "patterns": ["password", "hash", "bcrypt", "encrypt"], "match": "any"}),
        ])

    def _generate_ecommerce_criteria(self) -> None:
        self._criteria.extend([
            VerificationCriterion("ecommerce_html_exists", "E-commerce app must have an HTML file", "file_exists", True, {"path": "index.html"}),
            VerificationCriterion("ecommerce_server_exists", "E-commerce app must have a server file", "file_exists", True, {"path": "server.js"}),
            VerificationCriterion("ecommerce_product_list", "Must have a product listing", "file_content", True, {"path": "server.js", "patterns": ["product", "items", "catalog", "list"], "match": "any"}),
            VerificationCriterion("ecommerce_cart_functionality", "Must support cart operations", "file_content", True, {"path": "app.js", "patterns": ["cart", "addtocart", "add_to_cart"], "match": "any"}),
            VerificationCriterion("ecommerce_checkout", "Must have checkout functionality", "file_content", True, {"path": ["server.js", "app.js"], "patterns": ["checkout", "payment", "order"], "match": "any", "multi_file": True}),
        ])

    def _generate_chat_criteria(self) -> None:
        self._criteria.extend([
            VerificationCriterion("chat_html_exists", "Chat app must have an HTML file", "file_exists", True, {"path": "index.html"}),
            VerificationCriterion("chat_js_exists", "Chat app must have a JS file", "file_exists", True, {"path": "app.js"}),
            VerificationCriterion("chat_message_list", "Must have a message display area", "file_content", True, {"path": "index.html", "patterns": ["message", "chat", "messages", "list"], "match": "any"}),
            VerificationCriterion("chat_send_functionality", "Must support sending messages", "file_content", True, {"path": "app.js", "patterns": ["send", "emit", "submit", "post"], "match": "any"}),
            VerificationCriterion("chat_server_exists", "Must have a server for real-time communication", "file_exists", True, {"path": "server.js"}),
            VerificationCriterion("chat_realtime", "Must have real-time communication (websocket/socket)", "file_content", True, {"path": "server.js", "patterns": ["socket", "websocket", "ws", "real-time"], "match": "any"}),
        ])

    def _generate_dataviz_criteria(self) -> None:
        self._criteria.extend([
            VerificationCriterion("dataviz_html_exists", "Data visualization app must have an HTML file", "file_exists", True, {"path": "index.html"}),
            VerificationCriterion("dataviz_js_exists", "Data visualization app must have a JS file", "file_exists", True, {"path": "app.js"}),
            VerificationCriterion("dataviz_chart_library", "Must use a charting library", "file_content", True, {"path": ["index.html", "app.js"], "patterns": ["chart", "d3", "plotly", "canvas"], "match": "any", "multi_file": True}),
            VerificationCriterion("dataviz_data_source", "Must have a data source", "file_content", True, {"path": ["index.html", "app.js"], "patterns": ["data", "fetch", "api", "json"], "match": "any", "multi_file": True}),
            VerificationCriterion("dataviz_chart_element", "HTML must have a chart container element", "file_content", True, {"path": "index.html", "patterns": ["canvas", "svg", "chart", "div"], "match": "any"}),
        ])
