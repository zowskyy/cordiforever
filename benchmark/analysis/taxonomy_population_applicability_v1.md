# Taxonomy population applicability — specification (MNT-09, v1)

Applicability/scope amendment. **Not a classifier revision.** This document defines when the already-frozen
Furthest-Reached Bottleneck Taxonomy (MNT-07, and its D3 amendment MNT-08) may be applied to a population other than
the historical one, and it defines nothing else.

It involves no model inference, no scorer execution, no training and no modification of frozen evidence.
This specification is hashed before any new population is admitted. It is not changed in response to observed rows,
observed labels or observed outcomes.

Implementation: `benchmark/analysis/taxonomy_population_registry_v1.py`.
Synthetic tests: `tests/test_taxonomy_population_registry_v1.py`.
Mutation runner: `benchmark/analysis/taxonomy_population_registry_v1_mutations.py`.

## 1. External amendment (Option 4-A)

MNT-09 is **external**. It references the immutable MNT-07/MNT-08 artifacts by exact path and sha256 and
**does not edit, append to, re-freeze or otherwise mutate any of them**. Their hashes and their completed-execution
provenance (EXEC-D3V2-01, freeze commit `f30c5f6fee287774345e701041899668aaa3ec5d`, tag `d3-v2-methodology-freeze`)
remain exactly as recorded.

The ten referenced artifacts, and the constant that holds them, are `FROZEN_METHODOLOGY` in the implementation:

| Path | sha256 |
| --- | --- |
| `benchmark/analysis/furthest_bottleneck_taxonomy.md` | `cf5b8764fd15088a95c729d1a8388f8dc95adff07128d62d552a46062f354ce5` |
| `benchmark/analysis/furthest_bottleneck.py` | `6817e1a73454aecfbd81c161a96b0218561a362aad3da10985c7ddcd1f5aff1b` |
| `benchmark/analysis/furthest_bottleneck_mutations.py` | `8352890c0ede42ddf4140dc665463e5ba12b0a840f37b4a19856b5686f18685a` |
| `tests/test_furthest_bottleneck.py` | `055873e8909ef2b0ec6393ad0f327ddcc17567441406299422e04bb9ad825451` |
| `tests/test_furthest_bottleneck_mutations.py` | `658e4aa9608ce845b6c0e5b4b8fe3ee6b750da6234dad6d62a3660b195324615` |
| `benchmark/analysis/furthest_bottleneck_taxonomy_v2.md` | `4af9a3a414c3bf9ddad3a6f63190e4499f97387277349df9908a414a5e68abb2` |
| `benchmark/analysis/furthest_bottleneck_v2.py` | `e713ff4e99b967d3170ae8a41c9fc14eb706ae17065150424df0c085a923adef` |
| `benchmark/analysis/furthest_bottleneck_v2_mutations.py` | `4445c8e8d45e63008320da810ee3fe96bd9787afd09439af6b552bd67762b403` |
| `tests/test_furthest_bottleneck_v2.py` | `f2b897bb5a2dc16c61f0e582e7a2dc0b5dee2d6c5df4496a1c89534ff01f4725` |
| `tests/test_producer_call_round_contract.py` | `81c017bd162ada6c91f067cf28a9efa6e9c7a73e239bdc33c9e0737528af4205` |

## 2. Non-goals

MNT-09 changes none of: D0–D12; D3-v2; any F0–F6 stage definition; `INTERFACE_UNSUPPORTED`; `UNDETERMINED` or its
causes; F6 subtypes; oracle replay; precedence; any frozen historical classification.

MNT-09 does not: regenerate Qwen classifications; modify `benchmark/analysis/output/` or
`benchmark/analysis/output_v2/`; touch heldout; introduce any model-specific classification rule; authorize any
unregistered population.

The admission machinery is **pure and read-only**: it opens no file for writing, contacts no model, runs no oracle
and executes no scorer.

## 3. Population Registration Record (PRR)

A population may use the frozen taxonomy **only when** it is separately preregistered in a PRR, satisfies the frozen
input/row contracts, names the exact frozen methodology hashes, passes every admission rule below, and is
**explicitly** authorized for new-data application.

Absence of registration is refusal. Ambiguity is refusal. A malformed PRR is refusal. The default is **no**.

### 3.1 Preregistered structure — the only fields a future PRR may declare

These are knowable before the arm runs. They are structural facts about what will be executed, never about what it
produced.

| Field | Meaning |
| --- | --- |
| `population_id` | unique identifier for the registered population |
| `methodology` | mapping of frozen artifact path to sha256; must equal `FROZEN_METHODOLOGY` exactly |
| `new_data_application` | must satisfy `is True` (identity, never truthiness) for a non-historical population |
| `arms` | list of `{arm_id, role, condition, gate_sha256, split}` |
| `task_set` | exact task membership, as a list of task names |
| `expected_rows_per_arm` | structural: how many rows each arm will contribute |
| `expected_total_rows` | structural: `expected_rows_per_arm * len(arms)` |
| `input_contract_version` | the row-contract version the population claims to satisfy |
| `registration_ref` | `{gate_sha256, commit}` provenance of the registering experiment |

### 3.2 Outcome-dependent quantities are NOT preregistered

`solvable`, `unsuccessful_solvable`, `unsuccessful_per_arm`, and every taxonomy-derived or outcome-derived count
depend on model execution or on post-execution classification. **They cannot be known before a new arm runs and they
must not appear in a future PRR.** A future PRR declaring any of them is rejected (rule A11).

They are instead **computed after admission and reported as observed facts** on the admission result.

### 3.3 Historical reproduction assertions

`HISTORICAL_MNT07_DEV`, the single built-in PRR describing the six MNT-07 arms, may additionally carry
`historical_assertions` = `{solvable: 96, unsuccessful_solvable: 78, unsuccessful_per_arm: 13}`. These are already
frozen historical facts, and asserting them reproduces the existing runner's behaviour exactly.

This permission is **historical only**. Historical post-execution facts are never generalized into future
preregistration requirements: a PRR with `new_data_application is True` that carries `historical_assertions` is
rejected.

## 4. Admission rules

`admit_population(prr, rows, conditions)` raises `Stop` on any violation. There is no permissive mode, no warning
level and no best-effort path.

| Rule | Check |
| --- | --- |
| A1 | PRR present, parses, every required field present and well-typed; no unknown field; no duplicate `arm_id`; no two arms sharing a `(split, condition, gate_sha256)` selection triple |
| A2 | every entry of `methodology` matches `FROZEN_METHODOLOGY` on disk, exactly and completely |
| A3 | `new_data_application is True` for any non-historical population (identity, not truthiness) |
| A4 | every arm's `condition` resolves through `benchmark.repo_task_eval.CONDITIONS` to a `dict` of overrides |
| A5 | every arm's `split` is in `PERMITTED_SPLITS` (`{"dev"}`). **`heldout` is rejected unconditionally** |
| A6 | every selected row satisfies the row contract: required keys present, `calls` a list of dicts, `fingerprint` a non-empty string, `experiment.gate.sha256` present |
| A7 | selected rows per arm equal `expected_rows_per_arm`; total equals `expected_total_rows` |
| A8 | no duplicate task within an arm; each arm's task set equals `task_set` |
| A9 | a row not matching a declared `(condition, gate_sha256, split)` triple is never selected; a row matching a declared triple but failing any check rejects the whole admission |
| A10 | admission consults no model field. `model` and `model_digest` are provenance only |
| A11 | a PRR with `new_data_application is True` declares no outcome-dependent quantity and no `historical_assertions` |

### 4.1 Heldout firewall

`PERMITTED_SPLITS` is a module constant containing only `"dev"`. There is no PRR field, command-line flag,
environment variable, configuration option or alternate admission path capable of enabling heldout. Future heldout
applicability requires a separate methodology decision that names it explicitly.

### 4.2 Condition-resolution contract

The frozen classifier resolves a row's `condition` through `benchmark.repo_task_eval.CONDITIONS` to derive action
capabilities (`furthest_bottleneck.py:1052-1053`, `furthest_bottleneck_v2.py:372-373`). A4 therefore fails closed at
admission time rather than letting `action_capabilities` silently degrade to an empty capability set at
classification time.

### 4.3 Condition additivity

Because the frozen classifier imports `CONDITIONS`, adding a condition must not alter the resolved capabilities of
any existing condition. This is a required regression property, proven by test, not assumed. If adding a condition
ever changes an existing condition's resolved behaviour, that is stop condition N6: stop and report. The difference
is never normalized or explained away.

## 5. Two levels of historical equivalence

Historical reproduction is verified at two distinct levels, and the distinction is part of the contract:

- **Level A — selection identity.** The admitted historical population selects exactly the same rows, arms and tasks
  as `run_furthest_bottleneck_classification_v2.select_arms`.
- **Level B — classification identity.** Classifying those admitted rows with the unmodified frozen implementation
  reproduces the authoritative artifact `benchmark/analysis/output_v2/classification_v2.jsonl`
  (`1fbfd30bc46900b7d15845e5916200d227ac9a618c815c55db0038ff13d7b3a6`) at **byte identity**.

Byte identity is retained rather than weakened because EXEC-D3V2-01 already established it for this exact artifact
and operation: the two fresh-process realizations produced byte-identical `classification_v2.jsonl`, and the
serialization is canonical (`json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))` written with
`newline="\n"`). No timestamp, pid, duration or path enters that artifact.

Level B is verified locally as the authoritative evidence, because it replays oracles; the fast structural subset of
these checks runs in CI.

## 6. Observed facts

`admit_population` returns an `Admission` carrying, per arm and in total: the selected rows, and the **observed**
`solvable` and `unsuccessful_solvable` counts, computed from `expected_outcome == "verified_done"` and
`oracle_passed is not True` after admission. For the historical PRR these are additionally checked against
`historical_assertions`. For a future PRR they are reported and never checked against a preregistered value.

## 7. Stop conditions

- **N2** — historical classification differs at Level A or Level B: stop; MNT-09 is not additive.
- **N4** — the heldout prohibition cannot be made unconditional in code: stop.
- **N5** — admission cannot be made pure/write-free: redesign.
- **N6** — adding a condition changes an existing condition's resolved behaviour: stop and report.
- **N7** — pressure to let MNT-09 also change the classifier: refuse; that is a different amendment.
