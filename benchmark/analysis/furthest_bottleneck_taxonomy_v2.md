# Furthest-Reached Bottleneck Taxonomy — D3-v2 amendment (guard-admitted evidence cutoff)

Status: candidate methodology amendment, not yet frozen. Methodology v1
(`benchmark/analysis/furthest_bottleneck_taxonomy.md`,
`cf5b8764fd15088a95c729d1a8388f8dc95adff07128d62d552a46062f354ce5`) remains authoritative and unmodified. This
amendment changes exactly one fact, D3, and nothing else. It has never been executed against real trajectory rows;
every statement below was developed and tested on synthetic fixtures only.

## 1. Scope

Changed: the cutoff round used by D3 for each defect gold file.

Unchanged and inherited verbatim from v1:

- the set of evidence-dependent actions: `diagnose` and `edit_symbol` on a gold file (`write_file`, `replace_text`,
  `patch_json` and `delete_file` are not evidence-dependent actions in v1 or v2; changing that set would be a separate
  amendment);
- what counts as a complete view (`read_views` entry with `complete is True` for that exact path);
- same-round semantics: a view at round `r` counts for a cutoff at round `r` (`view.round <= cutoff`);
- the per-file view decision order: any complete view → TRUE; else any malformed view record anywhere → UNKNOWN; else
  all-False (including no view of the file) → FALSE; else UNKNOWN;
- per-file aggregation with `tri_and`, and UNKNOWN when `calls` is not a list;
- the gold-file domain D3 ranges over — exactly v1's: a gold file participates when its seed file exists, it appears
  in the reference patch, and it is `.py` or `.json`, i.e. whenever v1 creates its `regions`/`changed_json` key
  (`furthest_bottleneck.py:823-841, 865`). An empty, `None` or unparseable region does not narrow the domain in v1 and
  must not narrow it here;
- D0–D2, D4–D12, and `classify` — v2 calls v1's `classify` unchanged.

Invariant retained: UNKNOWN is not FALSE. UNKNOWN is never reduced to a determined value to classify more trajectories.

## 2. Normative definition

> **D3 (v2).** For every defect gold file g, complete evidence of g was available before the system permitted an
> evidence-dependent action on g to proceed. The cutoff is the first `diagnose` or `edit_symbol` call on g that passed
> every pre-execution admission gate.
>
> An attempt the system refused before execution did not permit anything to proceed and therefore does not set the
> cutoff. Whether the admitted action then succeeded, was usable, or hit the defect is irrelevant: D3-v2 asks whether
> required evidence preceded permitted evidence-dependent work, not whether that work was any good. D3-v2 is not
> D3-c (effective-step cutoff).

The construct measured: *was the required complete gold-file evidence available before the system was permitted to
proceed with an evidence-dependent downstream action?*

## 3. Admission observability (established from harness and evaluator code)

The following was established by reading `plugins/agent/loop.py`, `plugins/core/error_recovery.py`,
`core/failure_taxonomy.py`, `benchmark/repo_task_eval.py` and `benchmark/agent_task_eval.py` at commit
`fe956cd07555c9de841e42f4897952171697d3ed`.

1. Guards run before handler execution (`loop.py:803-811`); a `PolicyRejection` emits `guard.rejected` and re-raises
   (`loop.py:812-823`).
2. **Guards are not the only pre-handler non-admission path.** A repeat-blocked call (`loop.py:1446-1461`), a
   duplicate-success call (`loop.py:1464-1484`) and an unknown-tool or argument-parse failure (`loop.py:775-778`)
   each produce a failed `tool.result` with no `guard.rejected`. Therefore **absence of a guard-rejection record is
   not evidence of admission.**
3. **The error-recovery retry path does not apply to evaluator-produced rows.** `ErrorRecoveryPlugin` is registered
   only under `profile == "full"` (`main.py:159, 177`), and the evaluator builds its application with
   `profile="lite"` (`repo_task_eval.py:584`), so `self.context.plugins.get("error_recovery")` is `None` and the
   retry branch at `loop.py:1519-1532` never runs for these rows. Two earlier drafts of this specification built an
   argument on that branch; both are withdrawn, and nothing below depends on it. (Independently, for `edit_symbol`
   such a retry could not reach the handler anyway: `_enforce_read_before_write` sets
   `_blind_write_sigs[signature] = self._round` at `loop.py:672` before raising `unread_edit` at `683-687`, and a
   same-round retry is caught by the blind-write-retry check at `662-668`, which precedes the fingerprint
   short-circuit at `669-671`.)
4. Malformed or partial capture is detectable only structurally (missing keys, wrong types, length mismatch);
   completeness of event capture is not detectable from the row.
5. `calls` and `guard_rejections` come from one timeline, but carry **different round counters**
   (`calls.round` counts `turn.round` events, `repo_task_eval.py:235-238`; `guard_rejections.round` is the loop's
   `_round`, `loop.py:818`). No per-call identifier is persisted in either list. **v2 never compares the two round
   fields and never pairs calls with rejections by count or by order.**

**Normative rule** (what the classifier may conclude from persisted evidence):

- Absence of a guard rejection never establishes admission.
- A guard rejection never establishes non-admission for `edit_symbol`.
- A failed `edit_symbol` call's admission is UNKNOWN.
- Aggregate guard-rejection counts are used only as a consistency check that can push a value to UNKNOWN. They never
  identify an individual call.

**Harness explanation** (why stronger inference is unavailable), each item verified at the cited lines and none of
them speculative:

- a repeat-blocked call produces a failed `tool.result` with no guard event and without reaching the handler
  (`loop.py:1446-1461`);
- so does a duplicate-success call (`loop.py:1464-1484`);
- so does a pre-handler argument error (`_parse_arguments`, `loop.py:499-512`, raising before the guards at
  `775-778`);
- no per-call identifier is persisted on either side: `calls` entries carry round/tool/args/success/result head
  (`repo_task_eval.py:247-249`) and `guard_rejections` entries carry reason/tool/path/round/outcome
  (`agent_task_eval.py:234-237`); `call_id` exists only on transient events.

Each of the first three is independently sufficient for the normative rule: a failed `edit_symbol` call with no guard
entry may have been blocked before the handler, so absence proves nothing, and with no per-call identifier a present
entry cannot be attributed to a particular call.

For `diagnose` the picture is better, and that advantage is kept: `diagnosis_records` (`repo_task_eval.py:299-321`)
emits one record per `diagnose` call carrying `refused`, and a guard rejection consumes the paired failed
`tool.result`. A synthetic producer run over the real loop confirmed the intended shape — two rejected diagnose calls
produced two guard events, two records and two call entries, one each. The alignment and count preconditions in §4
are therefore a consistency check on that correspondence: any construction or capture anomaly that breaks the
one-to-one relation trips them, and the stream degrades to UNKNOWN. They are not tied to any particular mechanism for
producing such an anomaly.

Conceptual symmetry is "guard-admitted action" for both tools. Operational observability legitimately differs by tool,
and the difference is recorded here rather than removed by inference in either direction.

## 3b. Layer 0 — `D3_PRODUCER_ENVELOPE_CONTRACT`

Validity is layered. Layer 0 checks only that the row is shaped the way the evaluator producer shapes rows, so that
its call entries can be inspected at all; Layer 1 (§3a) then checks relevant-call position and order; only then may
frozen v1 extraction run.

**Normative definition.** A row is envelope-valid iff:

1. `calls` exists;
2. `calls` is a list;
3. every entry of `calls` is a dict;
4. for every call entry, a **present and non-null** `args` is a dict. Absent `args`, `args = None` and `args = {}` are
   all valid.

Violation raises `RowEnvelopeViolation`, a subclass of `RowContractViolation` carrying
`contract = "D3_PRODUCER_ENVELOPE_CONTRACT"`, so existing handling keeps working while the two causes stay
distinguishable.

**The boundary, by example.**

| | values |
|---|---|
| **ACCEPT** | `args` absent · `args = None` · `args = {}` · `args = {"path": …}` |
| **REJECT** | `args = []` · `""` · `0` · `False` · `"x"` · `7` · `True` · any other non-null non-dict |

**Why falsy non-dicts are still rejected.** `(call.get("args") or {}).get(...)` happens not to raise on `[]`, `""`,
`0` or `False`, so rejecting them is not required to avoid today's `AttributeError`. They are rejected anyway because
**Layer 0 defines the admitted producer-envelope shape, not the set of values that incidentally survive one current
downstream expression** — a different accessor, or a future reader of `args`, would not share that accident. The
producer always constructs `args` as a dict (`repo_task_eval.py:247`). Absent and `None` are *deliberate, documented
methodology relaxations*, admitted because the methodology's own `or {}` idiom makes them indistinguishable from
`{}`. Arbitrary non-null non-dicts are not admitted.

**Producer guarantee vs methodology minimum.** The current producer always writes `args` and always builds it with a
dict comprehension (`repo_task_eval.py:247`), so absent/`None` `args` is producer-impossible. Requirement 4 is
nonetheless the weaker *methodology minimum*: it tolerates absent and `None`, which both v1
(`furthest_bottleneck.py:859`) and v2 read through `(call.get("args") or {}).get(...)`. A requirement belongs in
Layer 0 only when the producer provably guarantees it **and** methodology safety depends on it.

**Deliberately not required:** `tool` present or a string; `success` present or a bool; `args["path"]` a string (the
producer legitimately summarizes a string longer than 300 characters into `{chars, sha256, head}`,
`repo_task_eval.py:193-196`); `result_head`/`result_chars`; `read_views`, `diagnoses`, `guard_rejections`, or any
other row field. **Layer 0 is not a general schema validator.**

**Producer proof** (read-only source analysis at commit `fe956cd07555c9de841e42f4897952171697d3ed`; no real row was
opened). `run_task` has exactly one row-returning statement, and it always sets `"calls"`
(`repo_task_eval.py:629-663`); the other `return` in that function body belongs to the nested `recording_chat`
closure (`:602`) and returns a model reply, not a row. `call_log` builds
that list, appending only dict literals (`:232, 247-249`) whose `args` is a dict comprehension over
`arguments.items()` — a non-mapping there raises inside `call_log`, so no such row is ever persisted; `append_row`
writes rows whole (`:507-515`); resume skips whole completed tasks (`:761-768`); `load_rows` is a shape-preserving
`json.loads` (`:524-526`); `agent_task_eval.py` writes a different file, and no import path constructs rows. Rows
from an older producer version cannot be inspected under the real-data firewall, which is exactly why Layer 0
validates rather than assumes.

**Validation precedence is normative.** The supported entry point runs, in this order: `d1_region_files` → Layer 0 →
Layer 1 → frozen v1 extraction → v2 evidence substitution → classification. A row violating both layers reports the
**Layer 0** error. No envelope-invalid and no position-invalid row may reach frozen v1 extraction — v1 dereferences
every call entry unguarded (`furthest_bottleneck.py:858-859`), so without Layer 0 such a row surfaced as an
`AttributeError` instead of a methodology verdict.

## 3a. Layer 1 — `D3_CALL_POSITION_CONTRACT`

The contract covers **call position as well as call order**. (It was introduced under the narrower name
`D3_CALL_ORDER_CONTRACT`; that name is retired, and no frozen artifact refers to it.)

**Normative definition.** A *relevant call* is an entry of `calls` that is a dict, whose `tool` is `diagnose` or
`edit_symbol`, and whose normalized `args.path` lies in the D3 gold-file domain (§1). A row satisfies the contract
when, for every relevant call:

1. it is structurally inspectable enough to be identified as a relevant call;
2. it contains a `round` key;
3. `type(call["round"]) is int`;

and, over the relevant-call subsequence in recorded `calls` order:

4. the rounds are **non-decreasing**.

Round `0` is valid; equal consecutive rounds are valid; rounds are never required to be strictly positive or strictly
increasing. Breach of 2, 3 or 4 is a structural producer-contract violation.

`type(...) is int`, not `isinstance`: `bool` subclasses `int`, so `type(True) is int` is false and a `True`/`False`
round is **invalid**, not round 1 or 0. This applies to relevant *call* rounds only — see §5a for view rounds.

The subsequence is **row-level and global across the whole gold-file domain**; the comparison is never restarted per
file. `diagnose` on gold A at round 4 followed, in recorded order, by `diagnose` on gold B at round 2 violates the
contract even though each file carries one call.

Payload `round` fields on events are never consulted, here or anywhere in v2.

**Derivation from the producer proof** (obtained without opening any real row, at commit
`fe956cd07555c9de841e42f4897952171697d3ed`). `call_log` (`repo_task_eval.py:228-259`) owns the construction of
persisted `calls`: it scans the timeline once forward, initialises a local counter as the integer `0`, advances it by
integer increments on `turn.round` only, writes that value into every appended entry, never consults a
payload-supplied round, and never rewrites, sorts or merges calls afterwards (`append_row`, `507-515`; resume skips
whole completed tasks, `761-768`). Every evaluator-produced relevant call is therefore necessarily positioned with a
plain integer round, and the relevant-call subsequence is necessarily non-decreasing. Requirements 2, 3 and 4 are the
same structural fact, so the contract is aligned with the producer domain. It is **not** justified by making any
theorem pass: the v1/v2 theorem in §7 is a consequence re-tested afterwards, never the reason.

**Methodology domain.** There is one structural domain. A row satisfying `D3_CALL_POSITION_CONTRACT` is in it; the
v1/v2 comparison theorem of §7 is stated over exactly that domain. Handwritten rows outside it may still be passed to
lower-level helpers for adversarial unit testing, but they are not valid methodology-entry inputs.

**Surface.** `check_call_positions` runs at the supported entry point (`extract_facts_v2`, and therefore
`classify_row_v2`) before any extraction, and raises `RowContractViolation`. The exception is never caught inside the
methodology. A violating row is never given a D3 value, an `evidence_unknown`, an `INTERFACE_UNSUPPORTED`, or any
F-label; no new label is introduced. A future real-data runner (not authorized, not designed here) must handle
structural invalidity explicitly rather than recording such a row as a classification.

**Scope of the guarantee.** The guarantee applies to the supported entry path. `d3_v2`, `d3_file`, `cutoff_bounds`,
`descriptive_facts` and the admission helpers remain callable directly for unit testing and diagnostic reasoning and
do **not** independently enforce the contract; redundant validation is deliberately not added to them. Their
conservative behaviour on off-domain input comes from the `UNPOSITIONED` rule in §5, which `d3_file` applies before
any view evaluation, and is protected by tests — so UNKNOWN cannot become a determined value there either.

**Three layers, not two conditions.** Earlier drafts framed malformed telemetry as "epistemic rather than
structural" and placed `calls` missing/not-a-list and non-dict entries on the epistemic side. That was wrong at the
entry point, and is corrected here:

| Layer | Condition | Result |
|---|---|---|
| **0 — structural producer invalidity** | the row is not shaped as the producer shapes rows: `calls` absent/not a list, a non-dict entry, or a present, non-null non-dict `args` — falsy ones (`[]`, `""`, `0`, `False`) included (§3b) | `RowEnvelopeViolation` at the entry point |
| **1 — structural position invalidity** | an *identifiable* relevant call has no round, a non-`int` round, or the relevant rounds decrease | `RowContractViolation` at the entry point |
| **3 — epistemic uncertainty inside off-domain helper input** | a lower-level helper is deliberately handed data outside the supported producer domain and cannot position the relevant action | `Lmin = UNPOSITIONED` → D3 **UNKNOWN** (defence-in-depth only) |

Layer 3 behaviour **never** implies a row is valid methodology input: every shape that reaches it through malformed
telemetry is refused at Layer 0. Among the shapes Layer 0 rejects, a *truthy* non-dict `args` is the one where a
directly-called helper raises rather than degrading gracefully — a statement about helper behaviour, not about the
Layer-0 boundary, which rejects falsy non-dicts too (§3b). That raise is stated honestly rather than given
speculative semantics, and Layer 0 refuses the shape at the supported entry.

*Correction of record:* earlier drafts claimed the conservative result came from evaluating views at −∞. It does not:
`view_value` at −∞ returns FALSE (no view precedes it), so before the §5 rule existed a row with an uninspectable
entry could return a determined FALSE even with a complete view above `Lmax`. The conservative behaviour is now
produced explicitly at the decision layer, from a single normalization point in `cutoff_bounds` — `calls`
missing/not-a-list and a non-dict entry both set `UNPOSITIONED` there, and **no second normative D3 decision guard
exists outside that canonical cutoff/bounds path**.

`descriptive_facts` inspects the same raw condition independently, and deliberately so: it answers a *descriptive*
question (was an attempt observed, was it pre-evidence) whose output never reaches `classify`, while `cutoff_bounds`
answers the *normative* question of whether the D3 cutoff can be positioned. Sharing one predicate would couple them,
so a later refinement of the descriptive notion would silently move the D3 cutoff — the opposite of the isolation this
amendment maintains. A test and a mutation pin the independence: the descriptive predicate may drift without changing
any D3 value.

## 4. Operational admission

For a `diagnose` or `edit_symbol` call c on a gold file, `admitted(c)` is tri-state:

- **P1 (positive admission, both tools).** `c["success"] is True` → TRUE. This state is reachable only after the handler
  returned (`loop.py:1562-1567`).
- **P2 (positive refusal, `diagnose` only).** All A5 preconditions hold and the aligned `diagnoses` record has
  `refused` set to a non-empty string → FALSE.
- **P3 (everything else).** UNKNOWN. This includes: `success` False with `refused is None`, repeat-blocked and
  duplicate-success calls, argument errors, any failed `edit_symbol` call, malformed records, and any case where the
  A5 preconditions fail.

**A5 preconditions** (all required; they are the only route to a FALSE admission):

1. `calls` is a list and `diagnoses` is a list;
2. `len(diagnoses)` equals the number of `diagnose` entries in `calls`;
3. normalized paths agree pairwise, in order, between the `diagnose` entries of `calls` and the records of `diagnoses`;
4. `guard_rejections` is a list of dicts, and the number of its entries with `tool == "diagnose"` equals the number of
   `diagnoses` records with a non-null `refused`;
5. every `diagnoses` record is a dict whose `refused` is a string or `None`.

Precondition 4 is consistency evidence about the stream as a whole. It is never used to decide which individual call
was rejected, and never applies to `edit_symbol`.

## 5. Cutoff and decision

For each gold file g in scope, over the attempt calls on g in `calls` order:

- **Lmax(g)** = the round of the **first** attempt, in recorded `calls` order, with `admitted` TRUE, else +∞.
- **Lmin(g)** = the round of the **first** attempt, in recorded `calls` order, with `admitted` in {TRUE, UNKNOWN},
  else +∞.

**Recorded call-list order is normative for action ordering**, inherited from v1
(`furthest_bottleneck.py:857-861`, `first_round.setdefault`, which takes the first entry in list order). v2 does not
redefine "first" as the smallest numeric round and never sorts or reorders `calls`. The amendment changes only which
actions qualify as the cutoff, not how "first" is determined — that is what keeps it single-factor. Numeric rounds are
used only to decide whether a read occurred no later than the selected cutoff, exactly as in v1.

Unreliability collapses to the appropriate bound rather than to a flag:

- any non-dict entry in `calls`, or an attempt on g with a non-integer round whose admission is not FALSE, makes the
  earliest possible cutoff unknown: **Lmin(g) = UNPOSITIONED** (represented as −∞);
- an attempt with admission TRUE and a non-integer round makes the latest possible cutoff unknown: **Lmax(g) = +∞**.

`UNPOSITIONED` is a sentinel for *"the earliest potentially relevant or admitted downstream action cannot be
positioned from this telemetry"*. It is epistemic uncertainty about where the cutoff lies, **not** a temporal cutoff
before every view, and the decision layer treats it as such. On a contract-valid row it is unreachable through
relevant calls (Lemma 0); it remains reachable through uninspectable entries and through direct helper calls.

With `V(g, L)` the unchanged v1 per-file view logic evaluated at cutoff L:

```
if Lmin is UNPOSITIONED:            D3_file(g) = UNKNOWN
elif V(g, Lmin) is TRUE:            D3_file(g) = TRUE
elif V(g, Lmin) == V(g, Lmax):      D3_file(g) = that value
else:                               D3_file(g) = UNKNOWN
```

The first branch is normative, not an optimisation: agreement between `V(UNPOSITIONED)` and `V(Lmax)` must never
manufacture a determined FALSE, because `V` at −∞ is FALSE for the trivial reason that no view precedes it.
`view_value` keeps its ordinary meaning — which views exist at or before a concrete cutoff — and inherited v1 view
semantics are untouched.

`D3 = tri_and(...)` over the files in scope, UNKNOWN if the scope is empty, and UNKNOWN if `calls` is not a list —
all as in v1.

Rationale for the first branch: V is monotone non-decreasing in L, and the true cutoff is at least Lmin, so a complete
view already present at Lmin is present at any admissible cutoff.

### 5a. View rounds are unchanged v1 semantics

The structural contract concerns persisted relevant **call** positions only. Read-view rounds keep frozen v1's
behaviour verbatim, `isinstance(v.get("round"), int)` (`furthest_bottleneck.py:871-872`), so a view with a `bool`
round acts as round 1 there. `type(...) is int` is **not** a global requirement for every round-bearing object in v2,
and this amendment does not redefine view-round semantics; any change there would be a separate reviewed amendment.

### Case treatment

| Case | Treatment |
|---|---|
| Positively refused diagnose (A5 established) | not a cutoff; the walk continues |
| Admitted and succeeded (either tool) | is the cutoff |
| Admitted but failed, with no positive evidence of admission | UNKNOWN: bounds the cutoff from below only |
| Failed `edit_symbol` (any guard-rejection pattern) | UNKNOWN; never inferred TRUE or FALSE |
| Repeat-blocked or duplicate-success call | UNKNOWN (no normative dependence on loop control flow) |
| Refused diagnose → complete read → admitted diagnose | cutoff is the admitted call; D3 TRUE |
| Refusal with no later admitted action | Lmax = +∞: TRUE if any complete view of g exists, FALSE if every view is incomplete or absent |
| No attempt on g | Lmin = Lmax = +∞; identical to v1 |

## 6. Descriptive facts

Two descriptive facts are reported next to the classification. **Neither is a field of `TrajectoryFacts` and neither
reaches `classify`.** Both are descriptive process-ordering signals with no causal content.

- **`D3_ATTEMPT_OBSERVED`** — TRUE if at least one `diagnose`/`edit_symbol` call on a gold file in scope is recorded;
  FALSE if none is; UNKNOWN if `calls` is not a list or contains a non-dict entry.
- **`D3_OBSERVED_PRE_EVIDENCE_ATTEMPT`** — TRUE if some attempt c on some gold file g in scope has `V(g, c.round)`
  FALSE; FALSE if every observed attempt has `V(g, c.round)` TRUE, **including the case of no attempt at all**;
  UNKNOWN otherwise.

Required interpretation: `D3_OBSERVED_PRE_EVIDENCE_ATTEMPT == FALSE` means only *"no pre-evidence attempt was
observed."* It does **not** by itself mean the model correctly waited for evidence; that reading requires
`D3_ATTEMPT_OBSERVED == TRUE` alongside it.

## 7. Theoretical label transitions

`facts.evidence` is read at exactly one point in `classify` (`furthest_bottleneck.py:225-230`), reachable only when
D0_HARNESS is TRUE, `defect_known` is TRUE, R7–R10 are all FALSE, `localized` is FALSE, no gold edit proposal exists
and `usable_diagnosis` is FALSE. There: FALSE → F0, TRUE → F1 (sub-label from `diagnosis_attempted`), UNKNOWN →
UNDETERMINED `evidence_unknown`.

**Comparison domain.** Every claim below is stated over rows satisfying **both** `D3_PRODUCER_ENVELOPE_CONTRACT`
(§3b) and `D3_CALL_POSITION_CONTRACT` (§3a), which together are the
domain both methodologies are intended to operate on. Nothing is claimed about arbitrary dictionaries. This is a
domain restriction derived from the producer contract and the two definitions, not an exception carved out after
observing outcomes; each claim is additionally searched for counterexamples over the synthetic state space in
`tests/test_furthest_bottleneck_v2.py` and is not asserted from the proof argument alone.

Write, per gold file g in the (identical) domain: `R1(g)` for v1's cutoff — the round of the first positioned
relevant call on g in recorded order (`furthest_bottleneck.py:857-861`) — and `Lmin(g)`, `Lmax(g)` as in §5.

**Lemma 0 (total positioning).** On a contract-valid row every relevant call satisfies `type(round) is int`
(requirements 2 and 3 of §3a). Hence no relevant call is unpositioned, the −∞ and +∞ collapses of §5 for unpositioned
calls are unreachable, and v1's `isinstance(..., int)` filter at `furthest_bottleneck.py:860` drops nothing: v1 and v2
range over the *same* relevant calls on g. *This lemma is what the earlier narrower contract lacked; without it a
relevant call with a `"two"`, absent or `bool` round made `Lmin = −∞ < R1` and the theorem was false.*

**Lemma 1 (bounds ordering).** By Lemma 0, `R1(g)` is the round of the first relevant call on g, and `Lmin(g)`,
`Lmax(g)` are rounds of relevant calls on g occurring at or after it in recorded order — v2 skips only positively
refused calls and never reorders. Requirement 4 makes the relevant-call rounds non-decreasing in recorded order, and
the calls on a single g are a subsequence of that sequence, so `R1(g) ≤ Lmin(g) ≤ Lmax(g)`, with `+∞` for absent
bounds preserving the inequality.

**Lemma 2 (V monotone in L).** Views at or before a larger cutoff are a superset. If `V(g,L)` is TRUE a complete view
already lies at or before L and still does at `L' ≥ L`. If `V(g,L)` is UNKNOWN, either a malformed view record exists
— a row-global condition, so UNKNOWN persists — or a `complete is None` view lies at or before L and still does, so
the completes are not all-False. Hence V never moves from TRUE or UNKNOWN to FALSE as L grows.

**Theorem (valid domain).**
- `v1 D3 = TRUE ⇒ v2 D3 = TRUE`: every file has `V(g,R1)` TRUE; by L1 and L2 `V(g,Lmin)` is TRUE; v2's first branch
  returns TRUE per file; `tri_and` of all-TRUE is TRUE.
- `v1 D3 = UNKNOWN ⇒ v2 D3 ∈ {UNKNOWN, TRUE}`: no file is FALSE under v1; a file with `V(g,R1)` TRUE gives TRUE, and
  a file with `V(g,R1)` UNKNOWN has `V(g,Lmin) ∈ {TRUE, UNKNOWN}` by L2 while v2 returns FALSE only when both bounds
  are FALSE; `tri_and` over {TRUE, UNKNOWN} is in {TRUE, UNKNOWN}.

Since `extract_facts_v2` replaces only `evidence` and the gold-file domain is identical to v1's, every other
`TrajectoryFacts` field is equal between v1 and v2 — asserted by test, not assumed.

**Resulting label transitions on contract-valid input.** Possible: F0 → F1, F0 → UNDETERMINED(`evidence_unknown`),
UNDETERMINED(`evidence_unknown`) → F1. Impossible: F1 → F0 (needs TRUE → FALSE), F1 → UNDETERMINED (needs
TRUE → UNKNOWN), UNDETERMINED(`evidence_unknown`) → F0 (needs UNKNOWN → FALSE), and any change to F2–F8,
INTERFACE_UNSUPPORTED, other UNDETERMINED sub-labels, F6 subtypes, guard judgements, reach or history — those paths
never read `evidence`, and all other facts are equal.

Off-domain rows are not covered by any of this: they are refused by §3a before classification.

Central construct property, protected by test: adding an earlier positively guard-rejected diagnosis attempt, leaving
admitted actions and read views unchanged, does not change D3-v2, and may change
`D3_OBSERVED_PRE_EVIDENCE_ATTEMPT`. The corresponding property does **not** hold for failed `edit_symbol` attempts,
whose admission is UNKNOWN; there the result may move toward UNKNOWN, and the tests assert that it does so rather
than inventing an admission status.

## 8. Relationship to v1 artifacts

v2 imports v1 and modifies nothing in it. The frozen v1 artifacts and their SHA-256 values are unchanged:

- `benchmark/analysis/furthest_bottleneck_taxonomy.md` `cf5b8764fd15088a95c729d1a8388f8dc95adff07128d62d552a46062f354ce5`
- `benchmark/analysis/furthest_bottleneck.py` `6817e1a73454aecfbd81c161a96b0218561a362aad3da10985c7ddcd1f5aff1b`
- `benchmark/analysis/furthest_bottleneck_mutations.py` `8352890c0ede42ddf4140dc665463e5ba12b0a840f37b4a19856b5686f18685a`
- `tests/test_furthest_bottleneck.py` `055873e8909ef2b0ec6393ad0f327ddcc17567441406299422e04bb9ad825451`
- `tests/test_furthest_bottleneck_mutations.py` `658e4aa9608ce845b6c0e5b4b8fe3ee6b750da6234dad6d62a3660b195324615`

There is no v2 real-data runner and no v2 output directory. The authoritative v1 classification
(`benchmark/analysis/output/`) is not reclassified, recomputed or reinterpreted by this amendment.

## 9. Known limitations

- Failed `edit_symbol` admission is unobservable in the persisted row, so such calls stay UNKNOWN. Positive per-call
  admission would require harness-side logging (for example an `admitted` flag on `tool.result`), which is out of
  scope for this amendment.
- A complete view falling strictly between Lmin and Lmax yields UNKNOWN rather than a determined value.
- Within a single round, a read recorded after an attempt still counts for that attempt (`<=`), inherited from v1.
