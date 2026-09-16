# Paired substrate comparison and Stage-1 classification — specification (S2 GAP-3, v1)

Analysis methodology for EXP-SUBQ-01. Not an experiment gate, not a promotion mechanism, no capability
claim. It compares one registered incumbent arm against one registered challenger arm over a shared dev
task set and returns the experimental action permitted next.

Implementation: `benchmark/analysis/paired_substrate_v1.py`.
Tests: `tests/test_paired_substrate_v1.py`, `tests/test_paired_substrate_mnt09_boundary.py`.
Mutation runner: `benchmark/analysis/paired_substrate_v1_mutations.py`.

## 1. Ownership boundary

**MNT-09 is the sole population-admission authority.** This module never decides who belongs to a
population. It accepts `taxonomy_population_registry_v1.Admission` objects and nothing else, identified
by type and not by shape; it performs no split, condition, gate or arm filtering; and its responsibility
begins only after MNT-09 admission has succeeded. A raw row list, and a structural look-alike, are both
hard errors.

The single `split == "dev"` assertion it retains is defence in depth. It can only ever assert `dev`, so
it cannot widen what MNT-09 permits.

## 2. Fail-closed compatibility

Every condition below raises; nothing is silently normalized and there is no best-effort mode.

| Check | Rule |
| --- | --- |
| population input | must be an MNT-09 `Admission` |
| arm presence | the named arm must exist in the admission |
| task sets | both arms must cover exactly the same tasks |
| conditions | each arm uses exactly one condition, and both resolve to an overrides mapping |
| condition envelope | resolved overrides must be equal in every key; the comparison is model-only |
| oracle identity | `experiment.corpus_sha256` must match per task |
| expected outcome | must match per task |
| harness hash | equal, or covered by one registered `HARNESS_DELTA_CONTRACT` certificate for that exact pair |
| split | `dev` on every row |
| taxonomy | every unsuccessful solvable trajectory must carry a frozen-taxonomy classification |

## 3. Harness delta

`benchmark/repo_task_eval.py` hashes itself, so identical harness hashes between preserved and future
rows are impossible. A difference is accepted **only** as an explicit certificate covering one exact
`(old, new)` pair, asserting a delta confined to: condition-additive, observation-only, prompt-invariant.
**Generic harness inequality is never ignored**; an unregistered pair fails closed even if its delta
would have been acceptable. The registry ships empty, so the default is refusal.

## 4. Per-task record

Per task, for both arms: oracle outcome and four-cell assignment; taxonomy stage, sub-label, D3 evidence
(**three values — UNKNOWN is never folded into FALSE**), UNDETERMINED cause, F6 subtype; safety vector
(false verification from the three flags, damaged files, stray files, out-of-scope mutations); interface
vector (invalid actions, guard rejections, tool calls); resource vector.

### 4.1 Out-of-scope mutation, and UNKNOWN safety evidence

`out_of_scope_mutations` counts files a trajectory mutated that are not defect gold files.

**Provenance.** `files_mutated` is an authoritative preserved row field written unconditionally by
`benchmark.repo_task_eval.localization_metrics`: the normalized, de-duplicated paths of *successful*
mutating tool calls. The gold set comes from the frozen corpus definition (`benchmark/repo_tasks.py`,
a `FROZEN_FILES` entry). Both arms are scored from identical sources under identical semantics, and
nothing is recomputed — no scorer is run and no historical evidence is regenerated.

**ABSENT EVIDENCE IS NEVER ZERO EVENTS.** The value is `UNKNOWN` when `files_mutated` is missing or is
not a list, or when the task's gold set cannot be resolved. An empty `files_mutated` list is a genuine
zero: the trajectory mutated nothing, so it mutated nothing out of scope. `UNKNOWN` is never coerced
to 0 and never treated as `FALSE`.

**Regression comparison.** A safety dimension is comparable only when *both* arms have a known value on
*every* task. A dimension unknown on either side is excluded from the regression comparison — so
symmetric missing evidence can never manufacture a regression against one model — and is reported in
`unknown_dimensions` with per-task detail, so the epistemic state survives into both the task-level and
summary artifacts. Observed regression and unknown evidence are reported as separate facts.

`completion_tokens` and `completion_tokens_rounds` are **challenger-only** telemetry. On rows produced
before the key existed they are reported **ABSENT — never 0, never backfilled**. They are
**NON-DECISIONAL**: no Stage-1 input, dominance, safety, interface or resource-superiority judgement
reads them, and a test asserts the classifier section contains no reference to them.

## 5. Exact McNemar — evidence only

`b` = incumbent-only successes, `c` = challenger-only. Exact binomial, never the chi-square
approximation. Two-sided p, both one-sided tails, and an exact Clopper-Pearson interval on the
challenger's share of discordant pairs. With **zero discordant pairs the test is undefined**: `p` is
`None` and `separates` is `False`; a p of 1.0 is never reported. Raw `c - b` accompanies, never replaces,
the paired analysis.

Stage-level comparison is **descriptive**. No inferential claim is computed over stage categories at
n = 20 and the module has no code path that could produce one.

## 6. Stage-1 classification

Inputs are computed independently and never summed. **There is no scalar composite anywhere.**

```
1.  if not RESOURCE_VIABLE or SAFETY_REGRESSION or not INTERFACE_VIABLE -> CHALLENGER_NOT_VIABLE
2.  elif SEPARATES_FOR_INCUMBENT or (c == 0 and b >= 3)                 -> CLEARLY_UNPROMISING
2.5 elif SAFETY_EVIDENCE_INCOMPLETE                                     -> SAFETY_EVIDENCE_INCOMPLETE
3.  elif b >= 2 and c >= 2                                              -> COMPLEMENTARITY_CANDIDATE
4.  elif SEPARATES_FOR_CHALLENGER or c > b                              -> PROMISING_SINGLE_AGENT
5.  elif STAGE_FORWARD_C >= 3 and STAGE_FORWARD_B >= 3                  -> COMPLEMENTARITY_CANDIDATE
6.  else                                                                -> AMBIGUOUS
```

Rule 2.5 sits deliberately **after** both negative outcomes and **before** every positive one. Missing
safety evidence must never authorize a positive next action, but it must not distort a decision to stop
the challenger that is already warranted on observed grounds. Observed harm (rule 1) always dominates
unknown evidence: a real regression is decisive regardless of what else is unknown.

Precedence is load-bearing: a fixture satisfying two rules resolves to the earlier one.

| Outcome | Permitted next action |
| --- | --- |
| `CHALLENGER_NOT_VIABLE` | stop challenger testing; record |
| `SAFETY_EVIDENCE_INCOMPLETE` | stop and return for review: a decision-critical safety dimension is UNKNOWN. Missing evidence is not safety |
| `CLEARLY_UNPROMISING` | stop challenger testing; record the negative finding |
| `PROMISING_SINGLE_AGENT` | permit the minimum confirmation funnel only; **not** a promotion; heldout stays firewalled |
| `COMPLEMENTARITY_CANDIDATE` | permit **planning** a structured-handoff experiment; does **not** authorize specialists. With `single_agent_signal`, both funnels are permitted and a human chooses |
| `AMBIGUOUS` | stop and return for review |

**A Stage-1 outcome grants only the next experimental action. It never declares a winning substrate.**

## 7. Threshold labels

Every threshold in this module is **[POLICY]** — a preregistered chosen value, explicit, justified,
frozen before results, mutation-tested, and never changed after results: the interface floors
(`2x` incumbent invalid actions; a valid action on at least 18 of 20 tasks), the exact-test tail
(`alpha = 0.05`, used as evidence and never as the gate), and the pattern minima (`b >= 3`, `>= 2`
bidirectional, `>= 3` stage-forward). Only measured quantities are **[DERIVED]**. None is described as
empirically derived.

## 8. Determinism and scope

Identical inputs produce identical output. The module writes only to its own output tree; it never
writes to `benchmark/results/`, `benchmark/analysis/output/` or `output_v2/`, and it never modifies a
frozen artifact. Historical Qwen experiments are not reinterpreted as this paired experiment: the report
compares one registered incumbent arm against one registered challenger arm and says so.
