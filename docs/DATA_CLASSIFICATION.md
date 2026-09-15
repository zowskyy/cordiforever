# Data Classification — Continuity Kernel

## Public (committed to git / safe to store in runtime directories)

| Path | Classification | May contain |
|------|----------------|-------------|
| `continuity/continuity.db` | **Internal — local runtime** | Session events, tool calls, model responses, step traces |
| `event_log snapshots` | **Internal — local runtime** | Compressed base64+zlib session state |
| `finetune_data/*.jsonl` | **Internal — local runtime** | Exported session trajectories for fine-tuning |
| `logs/` | **Internal — local runtime** | Decision logs, review queue drafts, metrics history |
| `workspace/` | **Working directory** | User-generated files |

### MUST NOT appear in committed files

- Raw user prompts that contain PII (use hashes or redacted excerpts only)
- API tokens, passwords, private keys
- Email addresses, personal legal statements (full text)
- Private repo source content

## Private (runtime-only, gitignored or local)

| Path | Classification |
|------|----------------|
| `continuity/continuity.db` (local only) | **Session data** — may contain user prompts |
| `logs/review_queue/` | **Internal** — low-confidence routing drafts |
| `.cache/` | **Internal** — runtime cache |
| `workspace/` | **Working directory** — user-controlled |

## GDPR / Retention

- **Lawful basis:** Legitimate interest (engineering audit trail) — document in
  your privacy policy.
- **Retention:** Default 90 days for session exports.
- **Erasure (DSAR):** Delete session_id and all associated events on request.

## SOC2 Controls (Target)

| Control | Implementation |
|---------|----------------|
| Integrity | SQLite WAL mode; append-only events; hash-chain (Phase 2) |
| Validation | `scripts/verify_plugin_security.py` in CI |
| Access | Protected-file enforcement at tool boundary |
| Monitoring | `plugins/core/health_monitoring.py`, `plugins/core/metrics.py` |
