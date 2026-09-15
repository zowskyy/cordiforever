# Plugin Rules

Developer-facing rules for writing plugins in the Cordis-Lite runtime.

These rules describe the contract. Code and tests enforce the important invariants —
this document is guidance, not enforcement.

## 1. Plugins do not call the model directly.

Plugins communicate results through events and the shared context. Only the
canonical AgentLoop is permitted to call the model adapter.

## 2. Plugins do not execute tools directly.

Plugins must not call `FileTools.write_file()` or any registered tool from within
their own logic. They may propose structured results that the AgentLoop dispatches.

## 3. Plugins do not modify protected files.

Protected files (e.g., `AGENTS.md`) are enforced at the FileTools boundary.
Attempts to write, delete, or rename a protected file must fail deterministically
with a `ToolError` and emit `protected_file.violation`.

## 4. Plugins use the shared EventBus.

All state transitions must be observable through `context.events.emit(...)`.
Do not create a second event system. Follow the canonical event taxonomy:
`user.message`, `system.message`, `assistant.message`, `tool.invoked`,
`tool.result`, `turn.start`, `turn.round`, `turn.end`, `context.pruned`,
`replan`, etc.

## 5. Plugins use approved context-injection APIs.

Model-visible context may only be added through:

- `context.prompt_injections` (cleared after each turn)
- Explicitly documented context-builder APIs

Plugins must NOT directly append to `context.messages` unless using an
approved controlled API.

## 6. Plugins respect calibration and token budgets.

Token budgets, message caps, and tool-result limits are immutable after startup.
They resolve from the calibration table in `core/calibration.py`. Plugins must
NOT modify these values or disable pruning.

## 7. Plugins are optional.

Every plugin must degrade gracefully when absent. The AgentLoop must function
correctly with or without any optional plugin.

## 8. Plugins reset transient state per run.

Per-run state such as `_failed_calls`, `_successful_calls`, and `_replan_count`
must be cleared at the start of each `run()` call. No plugin may leak state
between tasks.

## 9. Plugins do not create competing task/session truth.

The single authoritative task state is `task_state` inside `AgentLoop.run()`.
The durable source of truth is the event/session log. Plugins must NOT maintain
independent goal tracking, completion state, or task history.

## 10. Plugins use the canonical Plugin contract.

Every plugin must subclass `Plugin` (or `EventDrivenPlugin`) from `core/plugin.py`,
declare `name` and `dependencies`, register through the existing `PluginRegistry`
mechanism, and participate in dependency-aware topological sorting.

## Lifecycle

```
START → validate dependencies → attach to shared Context → initialize temporary state
RUN   → perform capability-specific work → emit events → return structured result
STOP  → release resources → clear transient state
```

## Health Checks

Every plugin must implement `health_check()` returning:

```python
{"healthy": bool, ...capability-specific fields}
```

Critical plugins (SchemaRouter, FileTools, EventLogger) must verify their
required capabilities are present and functioning.
