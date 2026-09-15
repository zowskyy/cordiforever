from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class ConfigValidationIssue:
    plugin: str
    key: str
    message: str
    severity: str = "error"
    timestamp: float = field(default_factory=time.time)


class ConfigValidationPlugin(EventDrivenPlugin):
    name = "config_validation"
    dependencies = ("formal_contracts",)

    def __init__(self) -> None:
        super().__init__()
        self._issues: list[ConfigValidationIssue] = []

    def start(self) -> None:
        self.validate_all()

    def stop(self) -> None:
        pass

    def validate_plugin_config(self, plugin_name: str, plugin: Any, config: dict[str, Any]) -> list[ConfigValidationIssue]:
        issues: list[ConfigValidationIssue] = []
        schema = getattr(plugin, "__config_schema__", {})
        required = schema.get("required", [])
        for key in required:
            if key not in config:
                issues.append(ConfigValidationIssue(
                    plugin=plugin_name,
                    key=key,
                    message=f"Missing required config key: {key}",
                    severity="error",
                ))
        return issues

    def validate_all(self) -> dict[str, list[ConfigValidationIssue]]:
        results: dict[str, list[ConfigValidationIssue]] = {}
        if self.context is None:
            return results
        for name, plugin in self.context.plugins.items():
            issues = self.validate_plugin_config(name, plugin, self.context.config or {})
            if issues:
                results[name] = issues
                self._issues.extend(issues)
                for issue in issues:
                    self.context.events.emit("config.violation", {
                        "plugin": issue.plugin,
                        "key": issue.key,
                        "message": issue.message,
                        "severity": issue.severity,
                        "timestamp": issue.timestamp,
                    })
        return results

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
