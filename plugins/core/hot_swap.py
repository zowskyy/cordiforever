from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class HotSwapResult:
    plugin: str
    success: bool
    message: str = ""
    timestamp: float = field(default_factory=time.time)


class HotSwapPlugin(EventDrivenPlugin):
    name = "hot_swap"
    dependencies = ("health_monitoring",)

    def __init__(self) -> None:
        super().__init__()
        self._history: list[HotSwapResult] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def reload_plugin(self, registry: Any, name: str) -> HotSwapResult:
        try:
            registry.reload(name)
            result = HotSwapResult(plugin=name, success=True, message="Reloaded successfully")
        except Exception as exc:
            result = HotSwapResult(plugin=name, success=False, message=str(exc))
        self._history.append(result)
        if self.context is not None:
            self.context.events.emit("hot_swap.result", {
                "plugin": result.plugin,
                "success": result.success,
                "message": result.message,
                "timestamp": result.timestamp,
            })
        return result

    def get_history(self) -> list[HotSwapResult]:
        return list(self._history)

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
