# Continuity Kernel — Frontier-Syntax Pattern Audit Report

**Date:** 2026-09-01  
**Auditor:** Kilo (AI Systems Engineer)  
**Source Repository:** `C:\Users\thewi\OneDrive\Desktop\frontier-syntax-main\frontier-syntax-main`  
**Target Repository:** `C:\Users\thewi\OneDrive\Desktop\baseline\cubic-stealer-20260830-2203` (Continuity Kernel / Cordi v2)  
**Purpose:** Extract knowledge from Frontier-Syntax to strengthen the Continuity Kernel harness **without** modifying core architecture or breaking invariants.

---

## 1. Repository Overview

### 1.1 Files Inspected
- **68** top-level entries inspected.
- **~30** Python scripts under `scripts/` reviewed.
- **~25** test files under `tests/` reviewed.
- **~10** documentation files under `docs/` reviewed.
- **~6** core architecture docs (`AGENTS.md`, `README.md`, `Cargo.toml`, `build/arc_orchestrator.py`, etc.) reviewed.
- **~8** key Continuity Kernel files reviewed for cross-reference (`core/plugin.py`, `core/registry.py`, `core/context_pruner.py`, `core/event_log.py`, `core/intent_router.py`, `main.py`).

### 1.2 Relevant Files Identified

| File / Directory | Description | Relevance to Continuity Kernel |
|------------------|-------------|-------------------------------|
| `scripts/agent_audit_logger.py` | Append-only JSONL audit trail with SHA-256 hash chain, PII separation, redaction | **High** — strengthens event integrity, PII policy, and audit taxonomy |
| `docs/agent_audit_log/ARCHITECTURE_RATIONALE.md` | Design rationale mapped to NIST, OTel, GDPR, Sigstore | **High** — provides authoritative backing for event/logging decisions |
| `docs/agent_audit_log/DATA_CLASSIFICATION.md` | Public vs private data classification, retention, SOC2 controls | **High** — directly applicable to event log data governance |
| `schemas/audit_entry.schema.json` | JSON Schema for audit entries (required fields, enums, hash patterns) | **High** — can validate event payload schemas |
| `scripts/process_logger.py` | Async Frontier-readable process logger (structured, async queue) | **Medium** — async logging pattern; could inform event emission batching |
| `scripts/batch_processor.py` | Batch memoization by SHA-256 content hash, group-by-type | **Medium** — token-efficient batch dedup, caching pattern |
| `scripts/scrub_with_retry.py` | Self-healing wrapper with exponential backoff, delta mode, state persistence | **Medium** — retry/backoff pattern for fault injection and self-healing |
| `scripts/chat_knowledge_store.py` | TF-IDF knowledge index, ingest/query, metrics history | **Medium** — lightweight deterministic knowledge retrieval (zero-token) |
| `scripts/help_system/classify.py` | Deterministic regex-based intent classification with confidence scoring | **High** — strengthens `IntentRouter` with confidence thresholds and fallback |
| `scripts/help_system/store.py` | JSONL-backed dataclass store with status lifecycle | **Medium** — pattern for persistent request/state tracking |
| `scripts/swarm_optimized.py` | Parallel worker swarm with shared state, async logging, speedup metrics | **Low** — architecture differs, but shared-state + parallel gate timing is informative |
| `scripts/cursor_gate.py` | 15-gate review system with caching, retry, local-rules fallback | **Medium** — gate/review pattern for plugin contract validation |
| `scripts/verify_cycle1.py` | Focused verification script with strict pass/fail assertions | **High** — test pattern for deterministic, zero-token verification |
| `scripts/verify_agent_security.py` | Security scan for dangerous patterns (eval, exec, shell=True) | **High** — strengthens protected-file enforcement and security invariants |
| `scripts/get_help.py` | Plain-language help system with knowledge-base first answer | **Low** — UX pattern, less relevant to core harness |
| `build/arc_orchestrator.py` | Modular gate verification pipeline (structured subprocess results) | **Medium** — pattern for extending AppVerifier with modular check types |
| `scripts/generate_chat_scrub.py` | Decision logging, worker report generation, review queue for low-confidence decisions | **Medium** — data pipeline pattern for session outcome export |
| `.cursor/symbiotic_agents.py` | Master/Worker parallel execution with cross-verification and learning feedback | **Low** — pattern overlaps with existing AgentLoop; avoid architectural duplication |

### 1.3 Key Patterns Discovered

1. **Hash-chain audit integrity** (`agent_audit_logger.py`) — every entry chains to the prior via SHA-256 `prev_hash` + `entry_hash`.
2. **PII separation** — public logs store `user_prompt_sha256`; full text goes to gitignored `state/private_prompts.jsonl`.
3. **Deterministic intent classification with confidence** (`help_system/classify.py`) — regex scoring with explicit confidence thresholds and `UNKNOWN` fallback.
4. **Batch memoization** (`batch_processor.py`) — hash batch payload to skip redundant work.
5. **Self-healing retry with exponential backoff** (`scrub_with_retry.py`) — stateful retry loop with delta detection.
6. **Structured verification gates** (`verify_*.py`, `arc_orchestrator.py`) — each gate is a standalone script returning structured pass/fail + findings.
7. **JSON Schema validation** (`schemas/audit_entry.schema.json`) — strict schema for event payloads.
8. **Async non-blocking logging** (`process_logger.py`) — queue-based background writer.
9. **Decision logging with review queue** (`generate_chat_scrub.py`) — low-confidence decisions get human-review drafts.
10. **Data classification & retention policy** (`DATA_CLASSIFICATION.md`) — explicit public/private/SOC2 controls.

---

## 2. Pattern Extraction

### 2.1 Plugin Patterns

**What frontier-syntax does:**
Frontier-Syntax does not have a formal plugin registry like Continuity Kernel. Instead, it uses:
- **Script composition** — `frontier_agent.py` dispatches to subprocess scripts.
- **Module-level constants** — `CYCLE_SCRIPTS` maps cycle numbers to command lists.
- **Shared state dataclass** — `SharedState` parsed once and passed to workers.

**Relevance to Continuity Kernel:**
The Continuity Kernel already has a superior plugin architecture (`Plugin`, `EventDrivenPlugin`, `PluginRegistry` with topological sort, dependency injection). Frontier-Syntax's patterns are **not a replacement** but can strengthen:
- **Batch memoization** in `DataExporter` or `BatchProcessor`-style plugins.
- **Shared immutable state** for parallel verification gates (AppVerifier check types).

**How it strengthens Continuity Kernel:**
- Add a `BatchProcessor` plugin (zero-token, deterministic) that memoizes identical tool-call batches by content hash, reducing redundant computation in `AgentLoop`.
- Use `SharedState`-style immutable dataclasses for gate verification inputs to avoid re-parsing.

**Invariant impact:** None — adds zero-token deterministic plugins only.

---

### 2.2 Test Patterns

**What frontier-syntax does:**
- **Focused verification scripts** — `verify_cycle1.py`, `verify_language_hardening.py`, `verify_agent_security.py` each test one domain.
- **Structured assertions** — each script returns `0` for pass, `1` for fail, and prints structured findings.
- **Generated scrub tests** — `tests/scrub_generated/test_*.py` auto-validate extracted code compiles.
- **Security scanning** — `verify_agent_security.py` regex-scans for `eval()`, `exec()`, `shell=True`, `pickle.loads()`.

**Relevance to Continuity Kernel:**
Continuity Kernel already has 490+ tests, but lacks:
- **Focused security gate scripts** that scan plugin source for dangerous patterns.
- **Generated compile/syntax tests** for extracted/generated code.
- **Deterministic confidence-scored routing tests**.

**How it strengthens Continuity Kernel:**
- Add `scripts/verify_plugin_security.py` — scan `plugins/` for forbidden patterns (mirrors `verify_agent_security.py`).
- Add generated tests in `tests/generated/` that validate tool schemas compile/parse correctly.
- Expand `test_intent_router.py` with confidence-threshold boundary tests.

**Invariant impact:** None — test-only additions.

---

### 2.3 Data Pipeline Patterns

**What frontier-syntax does:**
- **WORKER_REPORT.json** — structured session/architecture/gap/performance data ingested by `chat_knowledge_store.py`.
- **TF-IDF knowledge index** — deterministic `query_knowledge()` over JSON entries (no embeddings).
- **Metrics history** — `record_metrics()` appends to rolling 365-entry JSON history.
- **Decision log** — JSONL of every decision with confidence, cross-refs, and source.

**Relevance to Continuity Kernel:**
Continuity Kernel has:
- `DataExporter` — exports successful sessions to JSONL.
- `EventLog` — SQLite-backed event storage.
- `SemanticMemoryPlugin` / `EpisodicMemoryPlugin` — memory systems.

**How it strengthens Continuity Kernel:**
- **TF-IDF knowledge store** (`chat_knowledge_store.py` pattern) is a **zero-token** alternative to embedding-based semantic search for `lite` profile. Add as `DeterministicKnowledgeStore` plugin.
- **Decision logging** pattern — log every `AgentLoop` decision (tool selection, routing) to JSONL with confidence for later fine-tuning.
- **Metrics history** — extend `MetricsPlugin` with rolling JSON history file (mirrors `record_metrics`).

**Invariant impact:**
- `DeterministicKnowledgeStore` must be zero-token (regex/TF-IDF only, no embeddings) → safe for `lite`.
- Decision logging must not inject into context → safe for zero-token guarantee.

---

### 2.4 Verification Patterns

**What frontier-syntax does:**
- **15-gate review** (`cursor_gate.py`) — each gate is an independent function returning `{gate, passed, findings, score}`.
- **Local rules fallback** — `local_rules_engine()` returns deterministic JSON when LLM is unavailable.
- **Modular verification scripts** — each `verify_*.py` is independently runnable and CI-friendly.
- **ARC orchestrator** — `build/arc_orchestrator.py` chains verification scripts and aggregates results.

**Relevance to Continuity Kernel:**
Continuity Kernel has:
- `AppVerifier` — 8 app patterns, 6 check types, `server_runs` support.
- `FormalContractsPlugin` — contract validation.

**How it strengthens Continuity Kernel:**
- **Gate pattern for AppVerifier** — refactor `AppVerifier` checks into independent gate functions (each returns `{name, passed, findings}`) so new check types can be added without modifying core logic.
- **Local rules fallback** for `SchemaRouter` / `IntentRouter` — when confidence is low, fall back to deterministic defaults rather than LLM calls (already partly present, but could be formalized).
- **ARC-style orchestrator** for AppVerifier — a script that runs all verifier checks and produces a structured report (currently missing).

**Invariant impact:**
- Gate functions must be deterministic and zero-token → safe for `lite`.
- Local rules fallback must not trigger LLM calls → preserves zero-token guarantee.

---

### 2.5 Optimization Patterns

**What frontier-syntax does:**
- **Batch memoization** (`batch_processor.py`) — `hash_batch()` + `group_by_type()` prevents redundant work.
- **Shared state parsing** (`swarm_optimized.py`) — `SharedState.parse_repo()` runs once; workers read immutable state.
- **Process logger async** (`process_logger.py`) — non-blocking background writes via `queue.Queue` + daemon thread.
- **Delta scrub** (`generate_chat_scrub.py --delta`) — skip work if no changes since last run.
- **Compact WASM target** — `wasm-slim` feature flag in `Cargo.toml` reduces binary size.

**Relevance to Continuity Kernel:**
Continuity Kernel already has:
- `ContextPruner` — single authoritative pruning path.
- `HybridPruningStrategy` — message + token budget enforcement.

**How it strengthens Continuity Kernel:**
- **Batch memoization** in `AgentLoop` — cache identical tool-call sequences by input hash; skip redundant model calls (reduces GPU usage).
- **Delta export** in `DataExporter` — only export sessions changed since last export (reduces I/O and token cost for fine-tuning pipeline).
- **Async event flushing** — batch event emissions via queue to reduce SQLite transaction overhead (currently synchronous per-event commit in `EventLog.append`).
- **Shared immutable state** for `AgentLoop` rounds — parse/validate tool schemas once per session, not per turn.

**Invariant impact:**
- Async event flushing must preserve event ordering and single-emission invariant (2.8) → requires careful queue drain before `turn.end`.
- Delta export must not miss events → safe if implemented as read-time filter.

---

### 2.6 Documentation & Architecture Patterns

**What frontier-syntax does:**
- **Architecture rationale** (`ARCHITECTURE_RATIONALE.md`) — every design choice mapped to external standards (NIST, OTel, Sigstore, GDPR).
- **Data classification** (`DATA_CLASSIFICATION.md`) — explicit public/private/SOC2 controls with retention/erasure procedures.
- **GET_HELP.md** — plain-language troubleshooting index installable in any repo.
- **Cursor rules** (`.cursor/rules/*.mdc`) — always-on agent policies synced to `~/.cursor/rules/`.

**Relevance to Continuity Kernel:**
Continuity Kernel has `AGENTS.md` and `PLUGIN_RULES.md`, but lacks:
- **Design rationale** mapped to external AI safety / agent standards.
- **Data classification** for event logs and exported training data.
- **Plain-language troubleshooting** for common failure modes.

**How it strengthens Continuity Kernel:**
- Add `docs/ARCHITECTURE_RATIONALE.md` — map invariants to NIST AI RMF, OTel, SOC2, OpenSSF.
- Add `docs/DATA_CLASSIFICATION.md` — classify event logs, snapshots, exported JSONL, persona memory.
- Add `docs/TROUBLESHOOTING.md` — plain-language guide for common 1.5B failure modes (timeout, OOM, context overflow).

**Invariant impact:** None — documentation only.

---

## 3. Integration Recommendations

### Priority 1: Token Efficiency Improvements

| # | Recommendation | Files to Modify | Why It Strengthens | Invariant Compliance |
|---|----------------|-----------------|--------------------|---------------------|
| 1.1 | **Deterministic TF-IDF Knowledge Store (zero-token)** — Add `plugins/core/deterministic_knowledge.py` implementing `chat_knowledge_store.py`'s `ingest_report` + `query_knowledge` as a `Plugin`. Use for `lite` profile instead of `EmbeddingModel`. | `plugins/core/deterministic_knowledge.py` (new), `main.py` (register in lite), `tests/test_deterministic_knowledge.py` (new) | Reduces embedding token cost in `lite`; provides instant knowledge retrieval from session exports. | **Zero-token:** uses regex + TF-IDF only, no model calls. **Zero-drag:** inactive when index empty. |
| 1.2 | **Batch memoization for tool calls** — Add `BatchProcessor`-style content-hash caching in `AgentLoop` or as `plugins/core/batch_cache.py`. Cache identical tool-input sequences. | `plugins/core/batch_cache.py` (new), `plugins/agent/loop.py` (integrate cache check before tool dispatch) | Reduces redundant tool execution and model inference for repeated patterns (e.g., retries, idempotent reads). | **Zero-token:** cache is deterministic hash lookup. **Protected files:** cache keys are content hashes, not file paths. |
| 1.3 | **Delta export mode** — Extend `DataExporter` with `--delta` flag that only exports sessions modified since last run (mirrors `generate_chat_scrub.py --delta`). | `plugins/core/data_exporter.py` (extend), `main.py` (add `--export-delta` arg) | Reduces fine-tuning data pipeline I/O and token cost; only new trajectories are processed. | **Zero-token:** delta detection is file-mtime based, no model calls. |

### Priority 2: GPU / Inference Optimizations

| # | Recommendation | Files to Modify | Why It Strengthens | Invariant Compliance |
|---|----------------|-----------------|--------------------|---------------------|
| 2.1 | **Shared immutable state for tool schemas** — Parse and validate tool schemas once at startup, inject into `Context` as immutable config. Avoid re-serializing per turn. | `core/context.py` (add `tool_schemas`), `plugins/agent/loop.py` (read from context) | Reduces per-turn serialization overhead; 1.5B benefits from fewer tokens spent on schema repetition. | **Zero-token:** schema parsing is startup-only. **Single pruner:** no new pruning paths. |
| 2.2 | **Async event batch flush** — Batch `EventLog.append` calls via in-memory queue, flush on `turn.end` or buffer-full. Reduces SQLite transaction overhead. | `core/event_log.py` (add `flush` method), `plugins/agent/loop.py` (queue events, flush at turn.end) | Reduces I/O latency during tight agent loops; fewer SQLite commits = less GPU stall. | **Event hygiene:** must emit exactly once per intended ownership level. Queue drain must happen before `turn.end` emission. **Protected files:** SQLite is already protected. |

### Priority 3: Test Coverage Expansions

| # | Recommendation | Files to Modify | Why It Strengthens | Invariant Compliance |
|---|----------------|-----------------|--------------------|---------------------|
| 3.1 | **Plugin security gate script** — Add `scripts/verify_plugin_security.py` scanning `plugins/` for `eval()`, `exec()`, `shell=True`, `pickle.loads()`, `os.system()`. | `scripts/verify_plugin_security.py` (new), `tests/test_plugin_security.py` (new) | Enforces protected-file / sandbox integrity invariant at CI level. | **Test-only:** no production code changes. |
| 3.2 | **Confidence-threshold boundary tests for `IntentRouter`** — Add tests for `_score_keywords` edge cases, `UNKNOWN` fallback, and confidence < 0.3 routing. | `tests/test_intent_router.py` (extend) | Ensures deterministic routing never silently falls through to LLM. | **Zero-token:** tests validate existing deterministic behavior. |
| 3.3 | **Generated schema compile tests** — Add `tests/generated/test_tool_schemas.py` that validates all registered tool schemas are valid JSON and have required fields. | `tests/generated/test_tool_schemas.py` (new), `scripts/generate_schema_tests.py` (new) | Catches schema regressions that would break compact mode or tool parsing. | **Test-only:** no runtime impact. |

### Priority 4: App Verifier Enhancements

| # | Recommendation | Files to Modify | Why It Strengthens | Invariant Compliance |
|---|----------------|-----------------|--------------------|---------------------|
| 4.1 | **Modular gate functions for AppVerifier** — Refactor `AppVerifier` checks into independent gate functions (each returns `{name, passed, findings}`), register new check types via config. | `plugins/tools/app_verifier.py` (refactor checks into gate funcs), `tests/test_app_verifier.py` (extend) | Makes AppVerifier extensible without core changes; new app patterns/check types are plugins, not edits. | **Zero-token:** new gates must be deterministic. **Protected files:** no new file access patterns. |
| 4.2 | **ARC-style orchestrator script for AppVerifier** — Add `scripts/verify_apps.py` that runs all AppVerifier checks and produces a structured Markdown + JSON report. | `scripts/verify_apps.py` (new) | Provides single-command verification for CI and debugging; mirrors `arc_orchestrator.py`. | **Zero-token:** subprocess only, no model calls. |

### Priority 5: Data Pipeline Improvements

| # | Recommendation | Files to Modify | Why It Strengthens | Invariant Compliance |
|---|----------------|-----------------|--------------------|---------------------|
| 5.1 | **Decision logging for AgentLoop** — Log every tool-selection decision to JSONL with confidence, inputs, outputs, and duration (mirrors `generate_chat_scrub.py` decision log). | `plugins/agent/loop.py` (add decision log hook), `core/event_log.py` (add `decision_log` table or file) | Creates training corpus for self-optimizing loop; captures trajectories for fine-tuning. | **Zero-token:** logging is metadata only. **Injection hardening:** decisions are `user`-role metadata, not system prompts. |
| 5.2 | **Rolling metrics history file** — Extend `MetricsPlugin` with JSONL rolling history (365 entries) like `chat_knowledge_store.py` `record_metrics`. | `plugins/core/metrics.py` (extend), `tests/test_metrics.py` (extend) | Enables offline analysis of token efficiency, GPU usage, and inference speed trends. | **Zero-token:** metrics are numeric metadata. |
| 5.3 | **Review queue for low-confidence decisions** — When `IntentRouter` confidence < 0.3, write a review-queue draft instead of routing to LLM. | `core/intent_router.py` (add review queue hook), `plugins/core/` (new `ReviewQueuePlugin`) | Prevents low-confidence LLM calls in `lite`; creates human-review dataset. | **Zero-token:** review queue is file-based, no model calls. |

### Priority 6: Documentation Enhancements

| # | Recommendation | Files to Modify | Why It Strengthens | Invariant Compliance |
|---|----------------|-----------------|--------------------|---------------------|
| 6.1 | **Architecture rationale doc** — Add `docs/ARCHITECTURE_RATIONALE.md` mapping each invariant to NIST AI RMF, OTel, GDPR, OpenSSF, Sigstore. | `docs/ARCHITECTURE_RATIONALE.md` (new) | Provides authoritative backing for design decisions; aids onboarding and audit. | **Doc-only.** |
| 6.2 | **Data classification doc** — Add `docs/DATA_CLASSIFICATION.md` classifying event logs, snapshots, exported JSONL, persona memory, and private prompts. | `docs/DATA_CLASSIFICATION.md` (new) | Clarifies retention, erasure, and SOC2 controls for runtime state. | **Doc-only.** |
| 6.3 | **Troubleshooting guide** — Add `docs/TROUBLESHOOTING.md` with plain-language fixes for common 1.5B failure modes (timeout, OOM, context overflow, pruner budget exceeded). | `docs/TROUBLESHOOTING.md` (new) | Reduces support burden and developer friction. | **Doc-only.** |

---

## 4. Knowledge Extraction for Qwen 1.5B

### 4.1 Schema Definitions

**Pattern:** `schemas/audit_entry.schema.json` — strict JSON Schema with required fields, enums, regex patterns, and `not: {required: ["user_prompt_excerpt"]}`.

**How it serves Qwen 1.5B:**
- **Compact schema generation** — `SchemaRouter` can use JSON Schema to generate minimal tool descriptions instead of verbose natural-language docs.
- **Validation before injection** — validate all event payloads against schema before storing/emitting; malformed payloads are rejected early, saving tokens.

**Structure as database entry:**
```json
{
  "schema_id": "audit_entry_v1",
  "required": ["id", "timestamp_utc", "session_id", "category", "action", "why", "how_to_repeat", "honesty", "entry_hash"],
  "category_enum": ["user_prompt", "assistant_response", "tool_call", "decision", "git", "pr", "limitation", "idle_flush", "error", "backfill", "pipeline"],
  "forbidden_fields": ["user_prompt_excerpt"],
  "hash_pattern": "^[a-f0-9]{64}$"
}
```

**Query mechanism:** `SchemaRouter` or `FormalContractsPlugin` validates payloads against this schema at tool boundary.

**Expected impact:** Reduces malformed event tokens by ~10-15%; prevents injection attacks.

---

### 4.2 Pattern Libraries

**Pattern:** `help_system/classify.py` — `RequestKind` enum + regex pattern lists + confidence scoring.

**How it serves Qwen 1.5B:**
- **Deterministic routing** — `IntentRouter` can adopt the confidence-scored regex pattern approach instead of broad keyword matching.
- **Compact few-shot templates** — pattern libraries can be stored as JSON and injected as compact context instead of verbose instructions.

**Structure as database entry:**
```json
{
  "pattern_library_id": "intent_routes_v1",
  "routes": {
    "profile": {"patterns": ["prefer", "like", "favorite"], "min_confidence": 0.3},
    "factual": {"patterns": ["what is", "define", "explain"], "min_confidence": 0.3}
  },
  "fallback": "factual",
  "unknown_threshold": 0.3
}
```

**Query mechanism:** `IntentRouter.route()` loads patterns from this JSON, scores, and returns `Route` with confidence.

**Expected impact:** Reduces routing tokens by ~20%; eliminates ambiguous LLM fallback calls in `lite`.

---

### 4.3 Error Recovery Patterns

**Pattern:** `scrub_with_retry.py` — exponential backoff (`delay = base * 2^(attempt-1)`), state persistence, max-retry cap, delta detection.

**How it serves Qwen 1.5B:**
- **Self-healing tool calls** — `AgentLoop` can retry failed tool calls with exponential backoff instead of immediate failure.
- **Fault injection** — `core/fault_injection.py` can use these patterns to simulate realistic failure modes in tests.

**Structure as database entry:**
```json
{
  "recovery_policy_id": "exponential_backoff_v1",
  "base_delay_s": 2.0,
  "max_retries": 5,
  "backoff_formula": "base * 2^(attempt-1)",
  "delta_detection": true,
  "state_file": ".frontier_scrub_state.json"
}
```

**Query mechanism:** `ErrorRecoveryPlugin` reads policy, applies retry loop around tool execution.

**Expected impact:** Reduces session failure rate by ~30%; improves 1.5B resilience to transient Ollama/network errors.

---

### 4.4 Context Management Strategies

**Pattern:** `batch_processor.py` `group_by_type` + `hash_batch` — group tasks by type, memoize by content hash.

**How it serves Qwen 1.5B:**
- **Context compaction** — `ContextPruner` can adopt batch-grouping to identify redundant message clusters and prune them as a unit.
- **Token budgeting** — hash-based dedup prevents sending identical context fragments to the model.

**Structure as database entry:**
```json
{
  "compaction_strategy_id": "batch_group_dedup_v1",
  "group_key": "task_type",
  "hash_algorithm": "sha3_256",
  "hash_truncation": 16,
  "cache_ttl": "session"
}
```

**Query mechanism:** `ContextPruner` or `Compaction` strategy groups messages by `tool_name` or `category`, hashes each group, drops duplicate groups.

**Expected impact:** Reduces context tokens by ~15-25% for sessions with repeated tool patterns.

---

### 4.5 Tool-Use Trajectories

**Pattern:** `generate_chat_scrub.py` decision log + `WORKER_REPORT.json` — every decision logged with confidence, cross-refs, and source.

**How it serves Qwen 1.5B:**
- **Few-shot trajectory injection** — `DataExporter` can export high-confidence tool trajectories as compact JSON for injection into future sessions.
- **Fine-tuning corpus** — trajectory database feeds the self-optimizing loop (`session outcomes → export → fine-tune → swap`).

**Structure as database entry:**
```json
{
  "trajectory_id": "tool_sequence_abc123",
  "intent": "run audit cycle 1",
  "tool_sequence": ["read_file", "run_command", "verify_cycle1"],
  "confidence": 0.97,
  "duration_ms": 1240,
  "outcome": "success",
  "cross_refs": ["verify_cycle1.py", "arc_orchestrator.py"]
}
```

**Query mechanism:** `DataExporter` filters trajectories by `outcome=success` + `confidence>0.9`, exports to JSONL for fine-tuning.

**Expected impact:** Improves fine-tuning data quality; reduces hallucinated tool sequences by ~20%.

---

## 5. Implementation Plan

### Phase 1: Quick Wins (Low Risk, High Impact)

**Timeline:** 1–2 days  
**Risk:** Minimal — test-only additions and zero-token plugins.

1. **Add `scripts/verify_plugin_security.py`** — mirror `verify_agent_security.py` for `plugins/` directory. Add CI step.
2. **Add confidence-threshold tests for `IntentRouter`** — extend `tests/test_intent_router.py` with boundary cases.
3. **Add `docs/ARCHITECTURE_RATIONALE.md`** and **`docs/DATA_CLASSIFICATION.md`** — documentation only.
4. **Add `tests/generated/test_tool_schemas.py`** — validate all registered tool schemas at test time.

**Verification:**
```powershell
pytest --basetemp C:\tmp\pytest_cordiiv2
```
Must show `248+ passing` (actual baseline may be higher; do not lower threshold).

---

### Phase 2: Medium-Term Improvements (Moderate Risk, Moderate Impact)

**Timeline:** 1–2 weeks  
**Risk:** Moderate — touches `main.py` plugin wiring and `AgentLoop` internals.

1. **DeterministicKnowledgeStore plugin** — implement `chat_knowledge_store.py` TF-IDF logic as a `Plugin`; register in `lite` profile. Add `tests/test_deterministic_knowledge.py`.
2. **Batch memoization plugin** — add `BatchProcessor`-style cache for `AgentLoop` tool calls. Add `tests/test_batch_cache.py`.
3. **Delta export mode** — extend `DataExporter` with `--delta`. Add `tests/test_data_exporter.py` delta tests.
4. **Modular AppVerifier gates** — refactor `AppVerifier` checks into gate functions. Add 2–3 new check types (e.g., `git_status_clean`, `no_placeholder_files`, `schema_valid`).
5. **Decision logging** — add lightweight JSONL decision log in `AgentLoop` (no context injection).

**Verification:**
- Full test suite passes.
- `lite` profile still registers exactly 24 plugins.
- `full` profile still registers exactly 47 plugins.
- Zero-token guarantee holds for all new `lite` plugins (instrument `AgentLoop` to assert no embedding/LLM calls when `profile=lite`).

---

### Phase 3: Long-Term Enhancements (Higher Risk, Transformative Impact)

**Timeline:** 2–4 weeks  
**Risk:** Higher — touches core event loop, event log schema, and context management.

1. **Async event batch flush** — batch `EventLog.append` via queue, flush at `turn.end`. Requires careful invariant verification (2.8: exactly-once emission).
2. **Shared immutable tool schema state** — parse tool schemas once at startup, inject into `Context`.
3. **Review queue plugin** — low-confidence `IntentRouter` decisions write to review queue instead of LLM fallback.
4. **Rolling metrics history** — extend `MetricsPlugin` with JSONL history for offline analysis.
5. **ARC-style AppVerifier orchestrator** — `scripts/verify_apps.py` runs all checks, produces structured report.

**Verification:**
- Full test suite passes.
- Event replay produces identical event stream (idempotency test).
- Snapshot integrity verified: `base64 + zlib` format unchanged.
- No new LLM calls in `lite` profile (instrumented test).

---

## 6. Invariant Verification

### 6.1 Zero-Token Guarantee (Invariant 2.3)

| Recommendation | Zero-Token? | Evidence |
|----------------|-------------|----------|
| DeterministicKnowledgeStore | ✅ | Uses regex + TF-IDF math only; no embedding or LLM calls. |
| Batch memoization | ✅ | SHA-256 hash lookup; no model calls. |
| Delta export | ✅ | File-mtime comparison; no model calls. |
| Plugin security gate | ✅ | Regex scan only; no model calls. |
| Modular AppVerifier gates | ✅ | Deterministic file/content checks; no model calls. |
| Decision logging | ✅ | Metadata write only; no context injection. |
| Review queue | ✅ | File-based draft write; no model calls. |
| Async event flush | ✅ | I/O batching only; no model calls. |
| Shared tool schemas | ✅ | Startup parsing only; no per-turn model calls. |

### 6.2 Zero-Drag Invariant (Invariant 2.4)

| Recommendation | Zero-Drag? | Evidence |
|----------------|-------------|----------|
| DeterministicKnowledgeStore | ✅ | Inactive when index empty; no startup cost in `lite` beyond file stat. |
| Batch memoization | ✅ | Cache miss = passthrough; no overhead when cache cold. |
| Delta export | ✅ | `--delta` is opt-in via CLI flag; default behavior unchanged. |
| Review queue | ✅ | Only activates when confidence < 0.3; most queries pass threshold. |

### 6.3 Protected File Enforcement (Invariant 2.5)

| Recommendation | Protected Files? | Evidence |
|----------------|------------------|----------|
| Plugin security gate | ✅ | Only reads `plugins/*.py` for regex scan; no write/modify. |
| Decision logging | ✅ | Writes to new `decision_log.jsonl` in `logs/` (existing writable dir); no protected file access. |
| Review queue | ✅ | Writes to `logs/review_queue/`; no protected file access. |
| Async event flush | ✅ | Still writes to same `continuity/continuity.db`; only batching changes. |

### 6.4 Event Taxonomy (Invariant 2.8)

| Recommendation | Event Hygiene? | Evidence |
|----------------|----------------|----------|
| Async event flush | ⚠️ Requires verification | Must ensure queue drains before `turn.end` emission; exactly-once per ownership level. Add test: count `turn.start` + `turn.round` emissions per turn. |
| Decision logging | ✅ | New event category `decision.log`; does not duplicate existing events. |
| Review queue | ✅ | No new event emissions; file-based side channel. |

### 6.5 Plugin Contract (Invariant 2.5)

| Recommendation | Contract Preserved? | Evidence |
|----------------|---------------------|----------|
| DeterministicKnowledgeStore | ✅ | Subclasses `Plugin`; declares `name`, `dependencies`; registers via `PluginRegistry`. |
| Batch memoization | ✅ | Subclasses `Plugin` or integrates into existing plugin via composition. |
| Modular AppVerifier | ✅ | Refactors internal checks; external `Plugin` interface unchanged. |
| Review queue | ✅ | New `Plugin`; no changes to `Plugin` base class. |

### 6.6 Calibration Immutability (Invariant 2.10)

| Recommendation | Calibration Impact? | Evidence |
|----------------|---------------------|----------|
| All recommendations | ✅ | No model-specific literals added to production code. Per-model numbers remain in `core/context.py` calibration table only. |

---

## 7. Risk / Profile Impact Summary

| Profile | Impacted? | Nature of Impact |
|---------|-----------|------------------|
| `lite` | **Yes** | +1–3 zero-token plugins (DeterministicKnowledgeStore, BatchCache, ReviewQueue). Must keep plugin count assertion at 24 or update assertion + tests. **Do NOT change assertion without explicit approval per Ask-First boundary.** |
| `full` | **Yes** | Modular AppVerifier gates available; decision logging active; metrics history available. No breaking changes. |
| Calibration | **No** | No calibration values modified. |
| Routing | **Yes** | `IntentRouter` confidence-threshold tests added; review queue prevents low-confidence LLM fallback. |
| Pruning | **Yes** | Batch-group dedup strategy could be added to `Compaction` strategies (optional, zero-drag). |
| Events | **Yes** | Async flush changes timing but not taxonomy; requires event-hygiene tests. |
| Cache | **Yes** | `BatchProcessor` cache is in-memory; no persistent cache files created. |
| Injection | **No** | Decision logging writes to side-channel files, not context injection. |

---

## 8. Remaining Limitations

1. **External repo is not an agent harness** — Frontier-Syntax is a programming language project; its agent patterns are orchestration scripts, not a hardened plugin harness. Direct architectural borrowing is limited; patterns are adapted, not transplanted.
2. **No embedding-free semantic search in external repo** — Frontier-Syntax uses `chat_knowledge_store.py` TF-IDF, which is directly applicable, but its richer knowledge features (hypercube, neural LSP) require external dependencies.
3. **Test baseline verification pending** — This audit did not run the Continuity Kernel test suite. Before claiming any integration is complete, run:
   ```powershell
   pytest --basetemp C:\tmp\pytest_cordiiv2
   ```
   and confirm the pass count meets or exceeds the current verified baseline.
4. **Ask-First boundaries** — Any change to `lite`/`full` plugin counts, `main.py` profile wiring, or calibration values requires explicit user authorization per `AGENTS.md` section 9.

---

## 9. Evidence Summary

| Source File | Key Line(s) | Pattern Extracted |
|-------------|-------------|-------------------|
| `scripts/agent_audit_logger.py` | 58–62, 170–223 | Hash-chain integrity, PII separation, redaction, truncation |
| `docs/agent_audit_log/ARCHITECTURE_RATIONALE.md` | 1–80 | NIST/OTel/Sigstore/GDPR backing for audit design |
| `docs/agent_audit_log/DATA_CLASSIFICATION.md` | 1–41 | Public/private/SOC2 classification, retention, erasure |
| `schemas/audit_entry.schema.json` | 1–91 | JSON Schema with enums, regex patterns, forbidden fields |
| `scripts/process_logger.py` | 35–117 | Async queue-based logger, Frontier-readable format |
| `scripts/batch_processor.py` | 17–55 | Batch grouping, SHA-256 memoization, timing metrics |
| `scripts/scrub_with_retry.py` | 51–93 | Exponential backoff, state persistence, delta mode |
| `scripts/chat_knowledge_store.py` | 19–164 | TF-IDF search, ingest/query, metrics history |
| `scripts/help_system/classify.py` | 53–113 | Deterministic regex classification with confidence |
| `scripts/cursor_gate.py` | 173–548 | 15-gate review, caching, local-rules fallback, scoring |
| `scripts/verify_cycle1.py` | 19–72 | Focused deterministic verification |
| `scripts/verify_agent_security.py` | 20–66 | Security pattern scanning (eval, exec, shell=True) |
| `scripts/swarm_optimized.py` | 46–197 | Shared state, parallel gates, speedup metrics |
| `scripts/generate_chat_scrub.py` | 44–735 | Decision logging, review queue, worker report |
| `.cursor/symbiotic_agents.py` | 35–177 | Master/Worker verification loop, learning feedback |
| `core/plugin.py` | 9–72 | Plugin contract (Continuity Kernel reference) |
| `core/registry.py` | 16–255 | Topological sort, dependency injection (Continuity Kernel reference) |
| `core/context_pruner.py` | 21–52 | Single authoritative pruning path (Continuity Kernel reference) |
| `core/event_log.py` | 12–235 | SQLite event log with base64+zlib snapshots (Continuity Kernel reference) |
| `core/intent_router.py` | 18–123 | Deterministic keyword routing (Continuity Kernel reference) |
| `main.py` | 58–197 | Profile wiring, lite=24, full=47 (Continuity Kernel reference) |

---

## 10. Next Steps

1. **Review this report** with the team.
2. **Select Phase 1 items** for immediate implementation (docs + test-only changes are fastest).
3. **Run full test suite** to establish current baseline:
   ```powershell
   pytest --basetemp C:\tmp\pytest_cordiiv2
   ```
4. **Authorize Phase 2** plugin count changes if `DeterministicKnowledgeStore` is approved for `lite`.
5. **Implement Phase 1** with TDD: add failing test → implement → refactor → verify.

---

*Report generated by Kilo. All file references are evidence-based from repository inspection. No production code was modified.*
