from __future__ import annotations

from core.lifecycle import LifecycleConsolidator
from core.plugin import EventDrivenPlugin


class LifecycleConsolidatorPlugin(EventDrivenPlugin):
    name = "lifecycle"
    dependencies = ("event_logger",)

    def __init__(self, cluster_threshold: int = 20, salience_threshold: float = 0.5) -> None:
        super().__init__()
        self.cluster_threshold = cluster_threshold
        self.salience_threshold = salience_threshold
        self._lifecycle = None

    def register(self, context) -> None:
        super().register(context)
        event_log = context.plugins.get("event_log")
        if event_log is not None:
            self._lifecycle = LifecycleConsolidator(
                event_log,
                cluster_threshold=self.cluster_threshold,
                salience_threshold=self.salience_threshold,
            )

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def on_turn_end(self, event) -> None:
        self._maybe_consolidate(event)

    def _maybe_consolidate(self, event) -> None:
        if self._lifecycle is None:
            return
        payload = event.payload if hasattr(event, "payload") else {}
        session_id = payload.get("session_id", "default")
        try:
            summaries = self._lifecycle.maybe_consolidate(session_id)
            if summaries:
                self.context.events.emit("lifecycle.consolidated", {
                    "session_id": session_id,
                    "summaries": summaries,
                })
        except Exception:
            pass

    def maybe_consolidate(self, session_id: str):
        if self._lifecycle is not None:
            return self._lifecycle.maybe_consolidate(session_id)
        return []
