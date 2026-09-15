from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class HealthStatus:
    name: str
    healthy: bool
    message: str = ""
    last_check: float = field(default_factory=time.time)


class HealthMonitoringPlugin(EventDrivenPlugin):
    name = "health_monitoring"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self._statuses: dict[str, HealthStatus] = {}
        self._event_log: list[dict[str, Any]] = []
        self._max_events = 1000

    def start(self) -> None:
        self._log_event({"event": "started", "timestamp": time.time()})

    def stop(self) -> None:
        self._log_event({"event": "stopped", "timestamp": time.time()})

    def register_plugin(self, name: str) -> None:
        self._statuses[name] = HealthStatus(name=name, healthy=True)

    def unregister_plugin(self, name: str) -> None:
        self._statuses.pop(name, None)

    def check_all(self) -> dict[str, HealthStatus]:
        results: dict[str, HealthStatus] = {}
        for name in list(self._statuses.keys()):
            plugin = self._get_plugin(name)
            healthy = True
            message = ""
            if plugin is None:
                healthy = False
                message = "Plugin not found in context"
            elif not hasattr(plugin, "health"):
                healthy = False
                message = "Plugin does not implement health()"
            else:
                try:
                    health = plugin.health()
                    if isinstance(health, dict):
                        healthy = bool(health.get("healthy", True))
                        message = str(health.get("message", ""))
                except Exception as exc:
                    healthy = False
                    message = str(exc)
            results[name] = HealthStatus(
                name=name,
                healthy=healthy,
                message=message,
                last_check=time.time(),
            )
        return results

    def system_healthy(self, critical_plugins: list[str] | None = None) -> bool:
        if critical_plugins is None:
            critical_plugins = ["event_logger", "agent_loop"]
        statuses = self.check_all()
        return all(
            statuses.get(name, HealthStatus(name=name, healthy=False)).healthy
            for name in critical_plugins
        )

    def on_turn_end(self, event: Any) -> None:
        payload = event.payload if hasattr(event, "payload") else {}
        if payload.get("final_result") == "" and payload.get("error") == "max_rounds_exceeded":
            self._log_event({
                "event": "anomaly",
                "detail": "max_rounds_exceeded",
                "timestamp": time.time(),
            })

    def _log_event(self, event: dict[str, Any]) -> None:
        self._event_log.append(event)
        if len(self._event_log) > self._max_events:
            self._event_log.pop(0)

    def _get_plugin(self, name: str):
        if self.context is None:
            return None
        return self.context.plugins.get(name)
