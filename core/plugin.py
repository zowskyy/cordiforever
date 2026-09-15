from __future__ import annotations

from typing import Any

from .context import Context, EventBus
from .events import Event


class Plugin:
    name = "plugin"
    dependencies: tuple[str, ...] = ()
    __contract__: dict[str, Any] = {}
    __config_schema__: dict[str, Any] = {}

    def __init__(self) -> None:
        self.context: Context | None = None

    def register(self, context: Context) -> None:
        self.context = context

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def unregister(self) -> None:
        self.context = None

    def health(self) -> dict[str, Any]:
        return {"name": self.name, "healthy": True}

    def health_check(self) -> dict[str, Any]:
        """Return health status. Override in subclasses for custom checks."""
        return {"healthy": True}

    def get_metrics(self) -> dict[str, Any]:
        """Return performance metrics. Override in subclasses for custom metrics."""
        return {}

    def on_event(self, event: Event) -> None:
        pass


class EventDrivenPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__()
        self._events: EventBus | None = None

    def register(self, context: Context) -> None:
        super().register(context)
        self._events = context.events
        self._subscribe()

    def _subscribe(self) -> None:
        if self._events is None:
            return
        self._events.on("turn.start", self.on_turn_start)
        self._events.on("tool.result", self.on_tool_result)
        self._events.on("turn.end", self.on_turn_end)

    def on_event(self, event: Event) -> None:
        pass

    def on_turn_start(self, event: Event) -> None:
        pass

    def on_tool_result(self, event: Event) -> None:
        pass

    def on_turn_end(self, event: Event) -> None:
        pass
