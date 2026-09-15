from __future__ import annotations

import ast
import inspect
import time
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class ContractViolation:
    rule_id: str
    message: str
    severity: str
    plugin: str = ""
    timestamp: float = field(default_factory=time.time)


class FormalContractsPlugin(EventDrivenPlugin):
    name = "formal_contracts"
    dependencies = ("linting",)

    def __init__(self) -> None:
        super().__init__()
        self._violations: list[ContractViolation] = []
        self._contracts: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        self._load_default_contracts()

    def stop(self) -> None:
        pass

    def register_contract(self, plugin_name: str, contract: dict[str, Any]) -> None:
        self._contracts[plugin_name] = contract

    def validate_plugin(self, plugin_name: str, plugin: Any) -> list[ContractViolation]:
        violations: list[ContractViolation] = []
        contract = self._contracts.get(plugin_name)
        if contract is None:
            return violations

        required_attributes = contract.get("required_attributes", [])
        for attr in required_attributes:
            if not hasattr(plugin, attr):
                violations.append(ContractViolation(
                    rule_id="missing-attribute",
                    message=f"Plugin '{plugin_name}' missing required attribute '{attr}'",
                    severity="error",
                    plugin=plugin_name,
                ))

        required_methods = contract.get("required_methods", [])
        for method_name in required_methods:
            if not hasattr(plugin, method_name):
                violations.append(ContractViolation(
                    rule_id="missing-method",
                    message=f"Plugin '{plugin_name}' missing required method '{method_name}'",
                    severity="error",
                    plugin=plugin_name,
                ))
                continue
            method = getattr(plugin, method_name)
            if not callable(method):
                violations.append(ContractViolation(
                    rule_id="method-not-callable",
                    message=f"Plugin '{plugin_name}' attribute '{method_name}' is not callable",
                    severity="error",
                    plugin=plugin_name,
                ))
                continue
            expected_sig = contract.get("method_signatures", {}).get(method_name)
            if expected_sig is not None:
                try:
                    actual_sig = inspect.signature(method)
                    if len(actual_sig.parameters) != len(expected_sig):
                        violations.append(ContractViolation(
                            rule_id="signature-mismatch",
                            message=f"Plugin '{plugin_name}' method '{method_name}' signature mismatch",
                            severity="error",
                            plugin=plugin_name,
                        ))
                except (ValueError, TypeError):
                    pass

        return violations

    def validate_all(self) -> dict[str, list[ContractViolation]]:
        results: dict[str, list[ContractViolation]] = {}
        if self.context is None:
            return results
        for name, plugin in self.context.plugins.items():
            violations = self.validate_plugin(name, plugin)
            if violations:
                results[name] = violations
                self._violations.extend(violations)
                for violation in violations:
                    self.context.events.emit("contract.violation", {
                        "plugin": violation.plugin,
                        "rule_id": violation.rule_id,
                        "message": violation.message,
                        "severity": violation.severity,
                        "timestamp": violation.timestamp,
                    })
        return results

    def on_turn_start(self, event: Any) -> None:
        if self._should_revalidate():
            self.validate_all()

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass

    def _should_revalidate(self) -> bool:
        return len(self._violations) > 0 and random.random() < 0.1

    def _load_default_contracts(self) -> None:
        self._contracts["agent_loop"] = {
            "required_attributes": ["_tool_schemas", "_tool_handlers", "max_rounds"],
            "required_methods": ["run", "start", "stop"],
        }
        self._contracts["file_tools"] = {
            "required_attributes": ["workspace", "max_read_bytes", "max_write_bytes"],
            "required_methods": ["read_file", "write_file", "list_directory", "schemas"],
        }
        self._contracts["event_logger"] = {
            "required_attributes": ["_db_path", "_event_log", "_continuity"],
            "required_methods": ["emit", "start_step", "finish_step"],
        }
        self._contracts["ollama_model"] = {
            "required_attributes": ["model", "base_url", "timeout"],
            "required_methods": ["chat", "stream_chat", "list_models"],
        }
        self._contracts["terminal_ui"] = {
            "required_attributes": ["_running"],
            "required_methods": ["run", "stop"],
        }
        self._contracts["health_monitoring"] = {
            "required_attributes": ["_statuses", "_event_log"],
            "required_methods": ["check_all", "register_plugin", "system_healthy"],
        }
        self._contracts["error_recovery"] = {
            "required_attributes": ["_retry_counts", "_max_retries"],
            "required_methods": ["handle_failure", "reset", "reset_all"],
        }
        self._contracts["formal_contracts"] = {
            "required_attributes": ["_contracts", "_violations"],
            "required_methods": ["validate_plugin", "validate_all"],
        }
