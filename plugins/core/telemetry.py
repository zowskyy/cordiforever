from __future__ import annotations

from core.telemetry import AgentTelemetry
from core.plugin import EventDrivenPlugin


class TelemetryPlugin(EventDrivenPlugin):
    name = "telemetry"
    dependencies = ("event_logger",)

    def __init__(self) -> None:
        super().__init__()
        self._telemetry = None

    def register(self, context) -> None:
        super().register(context)
        event_log = context.plugins.get("event_logger")
        if event_log is not None:
            self._telemetry = AgentTelemetry(event_log.event_log)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def on_turn_start(self, event) -> None:
        self._trace_turn_start(event)

    def on_turn_end(self, event) -> None:
        self._trace_turn_end(event)

    def _trace_turn_start(self, event) -> None:
        if self._telemetry is None:
            return
        payload = event.payload if hasattr(event, "payload") else {}
        session_id = payload.get("session_id", "default")
        round_idx = payload.get("round", 0)
        user_text = payload.get("user_text", "")
        try:
            self._telemetry.trace("agent", "model_call", {
                "session_id": session_id,
                "round": round_idx,
                "user_text": user_text,
            })
        except Exception:
            pass

    def _trace_turn_end(self, event) -> None:
        if self._telemetry is None:
            return
        payload = event.payload if hasattr(event, "payload") else {}
        session_id = payload.get("session_id", "default")
        try:
            self._telemetry.trace("agent", "turn_end", {
                "session_id": session_id,
                "final_result": payload.get("final_result", ""),
            })
        except Exception:
            pass

    def trace(self, layer: str, event: str, data: dict) -> None:
        if self._telemetry is not None:
            self._telemetry.trace(layer, event, data)
