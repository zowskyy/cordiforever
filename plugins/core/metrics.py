from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class PluginMetrics:
    plugin: str
    counters: dict[str, int] = field(default_factory=dict)
    timers: dict[str, float] = field(default_factory=dict)
    last_updated: float = field(default_factory=time.time)


class MetricsPlugin(EventDrivenPlugin):
    name = "metrics"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self._metrics: dict[str, PluginMetrics] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def increment(self, plugin: str, counter: str, amount: int = 1) -> None:
        if plugin not in self._metrics:
            self._metrics[plugin] = PluginMetrics(plugin=plugin)
        self._metrics[plugin].counters[counter] = self._metrics[plugin].counters.get(counter, 0) + amount
        self._metrics[plugin].last_updated = time.time()

    def record_timer(self, plugin: str, timer: str, value: float) -> None:
        if plugin not in self._metrics:
            self._metrics[plugin] = PluginMetrics(plugin=plugin)
        self._metrics[plugin].timers[timer] = value
        self._metrics[plugin].last_updated = time.time()

    def get_metrics(self, plugin: str) -> PluginMetrics | None:
        return self._metrics.get(plugin)

    def get_all_metrics(self) -> dict[str, PluginMetrics]:
        return dict(self._metrics)

    def on_turn_start(self, event: Any) -> None:
        self.increment("system", "turns_started")

    def on_tool_result(self, event: Any) -> None:
        payload = event.payload if hasattr(event, "payload") else {}
        tool = payload.get("tool", "unknown")
        if payload.get("success"):
            self.increment(tool, "success_count")
        else:
            self.increment(tool, "failure_count")

    def on_turn_end(self, event: Any) -> None:
        payload = event.payload if hasattr(event, "payload") else {}
        if payload.get("final_result") == "" and payload.get("error") == "max_rounds_exceeded":
            self.increment("system", "max_rounds_exceeded")
