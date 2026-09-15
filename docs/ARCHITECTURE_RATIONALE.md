# Architecture Rationale — Continuity Kernel

This document maps each core design choice to authoritative guidance from
2024–2026. It is intended for auditors, contributors, and operators who need
to understand why the harness is built the way it is.

## 1. Plugin Registry with Topological Sort

**Choice:** `core/registry.py` — dependency-aware topological ordering, explicit
`register()` / `register_class()` / `discover()` lifecycle.

**Backing:**
- **CNCF Plugin Working Group** — standard lifecycle, avoid side effects in
  discovery.
- **Python `importlib` + `pkgutil`** — stdlib-only auto-discovery; no parallel
  loader.

## 2. Event-Driven Architecture with SQLite Event Log

**Choice:** `core/event_log.py` — append-only SQLite event store with base64 +
zlib compressed snapshots.

**Backing:**
- **OpenTelemetry Logs Data Model** — structured events with severity/body/attributes.
- **NIST SP 800-92** — append-only, centralized review, integrity protection.
- **W3C Trace Context** — `parent_event_id` enables correlating agent tool chains.

## 3. Single-Pruner Preservation

**Choice:** `core/context_pruner.py` — one authoritative pruning path that
preserves `assistant` messages containing `tool_calls`.

**Backing:**
- **1.5B Coherence Requirement** — small models lose track of pending tool
  calls if pruned; single path avoids post-prune cleanup races.

## 4. Injection Hardening

**Choice:** Injected context is always appended as a `user` message prefixed
with `[injected context]`.

**Backing:**
- **OWASP Top 10 for LLM Applications 2025** — prevent prompt injection from
  overriding system instructions.

## 5. Profile Philosophy (Lite vs Full)

**Choice:** `lite` = 24 deterministic, zero-token plugins. `full` = 47 plugins
with optional observability/memory. SemanticRouter disabled by default.

**Backing:**
- **1.5B Capacity Ceiling** — 32768 token window, 3000 token working pruner
  budget, ~1000 KV headroom.
- **Zero-Token Guarantee** — any new route/dispatch/classifier used by `lite`
  must be deterministic (regex, parsers, structured matching, symbolic methods).

## 6. Calibration Separation

**Choice:** Model-specific numbers live only in `core.context.MODEL_PRESETS`
and ride along in `Context.config["calibration"]`.

**Backing:**
- **Capacity Model** — `tokens = guidance + base_overhead + N * per_file +
  folds * delta`.
- **Calibration Table** — re-measurement path: `scripts/capacity_calculator.py
  --verify` → live benchmark pool → update table.

## 7. Protected File Enforcement

**Choice:** Tool boundary enforces protected-file rules via
`PreFlightGuard.check()`.

**Backing:**
- **Sandbox Integrity** — no untrusted execution bypasses the registered plugin
  path through `core.registry.py`.

## 8. Event Hygiene

**Choice:** Exactly one `turn.start` per outer turn, exactly one `turn.round`
per loop iteration.

**Backing:**
- **Event Taxonomy Immutability** — duplicate emissions break downstream
  consumers (UI, telemetry, training data).

## 9. Snapshot and Cache Integrity

**Choice:** Event-log snapshots are base64 + zlib. Cache payloads keep `entries`
nested to avoid collisions with reserved top-level keys.

**Backing:**
- **Deterministic Serialization** — avoids cache key collisions and enables
  reproducible replay.

## 10. Self-Optimizing Data Pipeline

**Choice:** Session outcomes are exported to JSONL for fine-tuning, enabling
`session outcomes → export → fine-tune → swap`.

**Backing:**
- **Reinforcement Learning from Human Feedback (RLHF)** — trajectory quality
  drives model improvements; fine-tuned models replace base models via hot-swap.

## References (URLs)

| ID | Resource |
|----|----------|
| R1 | https://opentelemetry.io/docs/specs/otel/logs/data-model/ |
| R2 | https://www.nist.gov/itl/ai-risk-management-framework |
| R3 | https://owasp.org/www-project-top-10-for-large-language-model-applications/ |
| R4 | https://www.ntia.gov/page/software-bill-materials |
| R5 | https://docs.sigstore.dev/logging/overview/ |
| R6 | https://huggingface.co/docs/peft |
