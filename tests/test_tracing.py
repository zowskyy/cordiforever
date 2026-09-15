from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.registry import PluginRegistry
from plugins.core.event_logger import EventLogger
from plugins.core.tracing import TracingPlugin


def test_tracing_start_and_end_span(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(EventLogger, db_path=tmp_path / "test.db")
    reg.register_class(TracingPlugin)
    reg.start_all()
    tracing = ctx.plugins["tracing"]
    span = tracing.start_span("test_plugin", "test_event")
    tracing.end_span(span)
    assert span.duration_ms is not None
    assert span.duration_ms >= 0


def test_tracing_get_spans_by_trace_id(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(EventLogger, db_path=tmp_path / "test.db")
    reg.register_class(TracingPlugin)
    reg.start_all()
    tracing = ctx.plugins["tracing"]
    span1 = tracing.start_span("a", "event1")
    span2 = tracing.start_span("b", "event2", parent_span_id=span1.span_id)
    tracing.end_span(span1)
    tracing.end_span(span2)
    spans = tracing.get_spans(span1.trace_id)
    assert len(spans) == 2


def test_tracing_event_emission(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(EventLogger, db_path=tmp_path / "test.db")
    reg.register_class(TracingPlugin)
    reg.start_all()
    tracing = ctx.plugins["tracing"]
    events = []
    def capture(event):
        events.append(event)
    ctx.events.on("trace.span_start", capture)
    ctx.events.on("trace.span_end", capture)
    span = tracing.start_span("test", "event")
    tracing.end_span(span)
    assert len(events) == 2
