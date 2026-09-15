from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    plugin: str
    event_type: str
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class TracingPlugin(EventDrivenPlugin):
    name = "tracing"
    dependencies = ("event_logger",)

    def __init__(self) -> None:
        super().__init__()
        self._spans: list[TraceSpan] = []
        self._active_spans: dict[str, TraceSpan] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def start_span(self, plugin: str, event_type: str, parent_span_id: str | None = None) -> TraceSpan:
        if parent_span_id is not None and parent_span_id in self._active_spans:
            trace_id = self._active_spans[parent_span_id].trace_id
        elif parent_span_id is not None:
            trace_id = parent_span_id[:32]
        else:
            trace_id = uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]
        span = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            plugin=plugin,
            event_type=event_type,
        )
        self._active_spans[span_id] = span
        if self.context is not None:
            self.context.events.emit("trace.span_start", {
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "plugin": plugin,
                "event_type": event_type,
                "timestamp": span.start_time,
            })
        return span

    def end_span(self, span: TraceSpan, metadata: dict[str, Any] | None = None) -> None:
        span.end_time = time.time()
        span.duration_ms = (span.end_time - span.start_time) * 1000
        if metadata:
            span.metadata = metadata
        self._spans.append(span)
        self._active_spans.pop(span.span_id, None)
        if self.context is not None:
            self.context.events.emit("trace.span_end", {
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "plugin": span.plugin,
                "event_type": span.event_type,
                "duration_ms": span.duration_ms,
                "timestamp": span.end_time,
            })

    def get_spans(self, trace_id: str) -> list[TraceSpan]:
        return [s for s in self._spans if s.trace_id == trace_id]

    def on_turn_start(self, event: Any) -> None:
        self.start_span("system", "turn.start")

    def on_tool_result(self, event: Any) -> None:
        payload = event.payload if hasattr(event, "payload") else {}
        tool = payload.get("tool", "unknown")
        span = self.start_span(tool, "tool.result")
        self.end_span(span, {"success": payload.get("success", False)})

    def on_turn_end(self, event: Any) -> None:
        payload = event.payload if hasattr(event, "payload") else {}
        span = self.start_span("system", "turn.end")
        self.end_span(span, {"final_result": payload.get("final_result", ""), "error": payload.get("error")})
