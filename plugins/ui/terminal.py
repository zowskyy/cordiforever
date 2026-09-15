from __future__ import annotations

import sys
from core.plugin import Plugin
from plugins.agent.routers import try_datetime_router, try_math_router, try_units_router


class TerminalUI(Plugin):
    name = "terminal_ui"
    dependencies = ("agent_loop", "ollama_model", "file_tools")

    def __init__(self) -> None:
        super().__init__()
        self._running = False

    def run(self) -> None:
        assert self.context is not None
        agent = self.context.plugins["agent_loop"]
        model = self.context.plugins["ollama_model"]
        files = self.context.plugins["file_tools"]

        self._running = True
        print("Cordis-Lite Phase 0-1")
        print(f"Model: {model.model}")
        print(f"Workspace: {files.workspace}")
        print("Commands: /help /models /clear /workspace /health /metrics /trace /plugins /math <expr> /datetime <expr> /units <expr> /quit")

        while self._running:
            try:
                text = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not text:
                continue

            if text == "/quit":
                break
            if text == "/help":
                print("/models   list installed Ollama models")
                print("/clear    clear conversation history")
                print("/workspace show workspace path")
                print("/math <expr>  solve math (e.g. /math solve x^2-4=0, /math limit (x^2-1)/(x-1) as x->1)")
                print("/datetime <expr>  date/time ops (e.g. /datetime today, /datetime add 5 days to 2024-01-01)")
                print("/units <expr>  unit conversions (e.g. /units convert 100 km to miles, /units 100 km in miles)")
                print("/quit     exit")
                continue
            if text == "/models":
                try:
                    for name in model.list_models():
                        print(f"- {name}")
                except Exception as exc:
                    print(f"Error: {exc}")
                continue
            if text == "/clear":
                self.context.clear_messages()
                print("Conversation cleared.")
                continue
            if text == "/workspace":
                print(str(files.workspace))
                continue
            if text == "/health":
                health = self.context.plugins.get("health_monitoring")
                if health is not None:
                    statuses = health.check_all()
                    for name, status in statuses.items():
                        print(f"  {name}: {'ok' if status.healthy else 'FAIL'} {status.message}")
                else:
                    print("Health monitoring not available")
                continue
            if text == "/metrics":
                metrics = self.context.plugins.get("metrics")
                if metrics is not None:
                    all_metrics = metrics.get_all_metrics()
                    for name, m in all_metrics.items():
                        print(f"  {name}: counters={m.counters} timers={m.timers}")
                else:
                    print("Metrics not available")
                continue
            if text == "/trace":
                tracing = self.context.plugins.get("tracing")
                if tracing is not None:
                    spans = tracing._spans[-10:]
                    for span in spans:
                        print(f"  {span.plugin}.{span.event_type}: {span.duration_ms:.1f}ms")
                else:
                    print("Tracing not available")
                continue
            if text == "/plugins":
                for name, plugin in self.context.plugins.items():
                    deps = getattr(plugin, "dependencies", ())
                    status = "ok" if getattr(plugin, "health", lambda: {})().get("healthy", True) else "FAIL"
                    print(f"  {status} {name} deps={list(deps)}")
                continue
            if text == "/ci":
                ci = self.context.plugins.get("ci_plugin")
                if ci is not None:
                    status = ci.get_status()
                    print(f"CI: {status['message']}")
                    if status.get("url"):
                        print(f"  {status['url']}")
                else:
                    print("CI plugin not available")
                continue
            if text.startswith("/math ") or text.startswith("/datetime ") or text.startswith("/units "):
                router_out = try_math_router(text, self.context)
                if router_out is None:
                    router_out = try_datetime_router(text, self.context)
                if router_out is None:
                    router_out = try_units_router(text, self.context)
                if router_out is not None:
                    print(router_out)
                else:
                    print("Error: router not available")
                continue

            try:
                if getattr(agent, "stream", False):
                    print("\n[streaming] ", end="", flush=True)
                    buffer = ""
                    tool_calls_started = False

                    def on_stream(chunk):
                        nonlocal buffer, tool_calls_started
                        if chunk.tool_calls:
                            tool_calls_started = True
                            if buffer:
                                print(buffer, end="", flush=True)
                                buffer = ""
                            print(f"\n[tool_calls: {len(chunk.tool_calls)}]", flush=True)
                        elif chunk.content and not tool_calls_started:
                            buffer += chunk.content
                            print(chunk.content, end="", flush=True)

                    answer = agent.run(text, on_stream=on_stream)
                    if buffer:
                        print(buffer, flush=True)
                    if answer and not tool_calls_started:
                        print(answer)
                else:
                    answer = agent.run(text)
                    if answer:
                        print(answer)
            except Exception as exc:
                print(f"Error: {exc}")
