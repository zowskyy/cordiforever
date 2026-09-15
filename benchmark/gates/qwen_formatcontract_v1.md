# Gate qwen_formatcontract_v1 — type-specific replacement-format contract (Q-002)

Pre-registered 2026-09-15, before any code for the mechanism. DEV split only; no heldout task, row or failure pattern informs this design. Frozen after hashing; a revision is `qwen_formatcontract_v2.md` and reruns all arms.

## Scope
EXP-22 tests whether an explicit type-specific replacement-format contract, shown before edit execution, increases structurally valid replacement proposals from Qwen under the existing bounded localized-edit path.

It does not test:
- semantic correctness
- completion or post-edit feedback content
- retries or replanning
- automatic repair
- abstention
- the structural no-op refusal or the completion latch

## Hypothesis
Providing an explicit type-specific replacement-format contract increases structurally valid replacement proposals from Qwen under the existing bounded localized-edit path.

Outcomes are kept separate: replacement proposed → replacement-format valid → accepted by existing guards → mutation executed → semantically correct → hidden-test pass. Only the format stage is the hypothesis.

## Arms (qwen2.5-coder:1.5b, dev split, 20 tasks = 16 solvable + 4 insufficient-evidence, temperature 0)
- **Control (frozen, inferential):** `qwen_selectorkind` dev rows carrying gate sha256 `dcca9c02e0aee827005043ca08b4b617d4f88c7a3a048b69a975f20572f51e47` on harness `b1ee367bc339…`, overrides `69180f7e2c04…`. Registered constants are in "Control constants".
- **Treatment:** `qwen_formatcontract` = `qwen_selectorkind` overrides + `replacement_format_contract: True`. The only change. `ast_noop_refusal` and `completion_requires_mutation_success` are not enabled in any arm.
- **Drift (validity only):** `qwen_selectorkind` rerun on the new harness with the flag off.

## Mechanism, fixed now
With `replacement_format_contract: True`, and only when `localized_edits` and `explicit_selector_kind` are both enabled, the two `replacement` placeholders in the explicit-selector-kind edit guidance lines are replaced by the following exact text.

- python_symbol line, replacement placeholder:
  `"replacement": "<the complete new definition of only that function, method, class or assignment, starting with def, async def, class, or the assignment name; no other definitions, no whole file, no Markdown code fences, no explanation>"`
- json_pointer line, replacement placeholder:
  `"replacement": "<one valid JSON value of the same kind as the current value at target: a quoted \"string\", a number, true, false, null, a [list] or an {object}>"`

Unchanged:
- **Edit guidance and schema:** every other character of the edit guidance, the action schema and constrained decoding, tool descriptions.
- **Edit execution:** selector resolution, `edit_symbol`, all existing guards and their messages, bounded-edit validation.
- **Loop and model settings:** prompt text outside the two placeholders, repeat and retry policy, completion handling, max rounds, decoding.
- **Evaluation and inputs:** lane, oracle, corpus.
- No new validation, refusal, repair, retry or feedback path is added.

Model-invisible evaluator instrumentation (present on every new row in both arms; changes the harness hash):
- `edit_proposals`: one entry per `edit_symbol` tool result, in order, with
  - the untruncated `path`, `selector_kind`, `target`, `replacement` and `success`
  - `after_text`, the edited file's contents read immediately after a successful edit (null otherwise)
- `format_contract_shown`: true iff both exact contract strings above appear in at least one message sent to the model.

## Normative replacement-format definition
Every proposal receives exactly one terminal: VALID, FORMAT_INVALID, SELECTOR_FAILURE, or UNCLASSIFIABLE. SELECTOR_FAILURE and UNCLASSIFIABLE are never counted as FORMAT_INVALID. The checks apply in this order.

1. **Selector** (it takes precedence over format):
   - `selector_kind` is not `python_symbol` with a `.py` path or `json_pointer` with a `.json` path → SELECTOR_FAILURE.
   - A missing target → SELECTOR_FAILURE.
   - File state immediately before the edit is unavailable or unparseable → UNCLASSIFIABLE. The state is the seed file plus earlier successful edits in the row.
   - python_symbol:
     - the target does not match `name` or `Class.method`, or does not resolve in the pre-edit file → SELECTOR_FAILURE
     - it resolves to a top-level def/async def/class, a module-level Assign/AnnAssign name, or a def/async def method directly inside that class
   - json_pointer: the target is not an RFC 6901 pointer that resolves in the pre-edit document (`""` and `"/"` never resolve) → SELECTOR_FAILURE.
2. **Python format (full text):**
   - VALID iff all hold:
     - the replacement is non-empty after `textwrap.dedent` and stripping surrounding newlines
     - it parses
     - it has exactly one top-level statement
     - that statement binds exactly the selected target
   - **Undotted target:** a `def`, `async def` or `class` with that name, with decorators allowed as part of that single definition. Or an `Assign` with exactly one target, which is a `Name` of that name (a chained assignment `X = Y = 1` is FORMAT_INVALID). Or an `AnnAssign` to that name that has a value (a valueless annotation `X: int` is FORMAT_INVALID).
   - **Dotted `Class.method` target:** exactly one `def` or `async def` named after the method. A containing class or an assignment is FORMAT_INVALID.
   - Everything else is FORMAT_INVALID: wrong symbol, whole file, multiple statements, bare identifier or expression, unparseable text, prose.
3. **JSON format (full text):**
   - VALID iff both hold:
     - the replacement parses as exactly one strict JSON value, with `NaN`, `Infinity`, `-Infinity` and trailing material rejected
     - its JSON kind equals the kind of the current value at the pointer
   - Kinds are null, boolean, number, string, array, object; boolean and number are distinct kinds.
   - Otherwise FORMAT_INVALID.
4. **Markdown fences:** not an independent rule. Fenced text does not parse under rules 2 and 3 and is FORMAT_INVALID by them. `markdown_fence` is a descriptive reason label only, applied when a line of the replacement starts with ```. Backticks inside string content are not forbidden.
5. **Truncated historical representations** (`{chars, sha256, head}`, frozen control only):
   - Python:
     - the head starts with ``` → FORMAT_INVALID
     - the first non-blank line is unindented and begins a def/async def/class or an assignment of a different name, or an import → FORMAT_INVALID
     - it begins with the target's own definition or assignment, or its first statement cannot be established (empty, indented, other syntax, no head) → UNCLASSIFIABLE
   - JSON: ``` → FORMAT_INVALID; otherwise UNCLASSIFIABLE.
   - Validity is never inferred from unavailable text.
6. **Missing values:** a `None` or empty replacement → FORMAT_INVALID. Any other unknown representation → UNCLASSIFIABLE.

Data sources:
- Control: `calls[].args` of `edit_symbol` calls; pre-edit state replayed from the seed with the harness edit functions.
- Drift and treatment: `edit_proposals`; pre-edit state = the latest `after_text` for the path, else the seed.

Prototype testing before freeze (pre-registration development evidence, not experimental evidence):
- The definition was implemented as a scratch prototype and checked against 42 user-specified synthetic cases plus extras (57 checks, all passing), and against in-memory mutations: 13 meaningful mutations caught, 1 equivalent.
- Changes that prototype testing caused:
  - the independent fence rule became a reason label only
  - non-standard JSON constants were made explicitly invalid
- The prototype and its results are not part of this gate hash. The production scorer must implement this definition unchanged.
- If it cannot, that is a pre-registration defect to be reported before any treatment run.

## Control constants (frozen `qwen_selectorkind` rows, computed with the prototype before freeze; control data only)
- **Outcomes:** hidden-test passes 3/16; damaged tasks 0; localized-hit tasks 8; stray tasks 0; cumulative edit executed 6.
- **Proposals, solvable tasks:**
  - tasks with a proposal 10
  - proposals 11: VALID 7, FORMAT_INVALID 4, SELECTOR_FAILURE 0, UNCLASSIFIABLE 0
- **Solvable tasks with ≥1 VALID proposal: 7.** FORMAT_INVALID solvable proposals: 4.
- Solvable tasks whose proposals are all FORMAT_INVALID: 3 (`config_add_feature`, `inventory_find_missing`, `textkit_cli_upper`).
- **Proposals, insufficient-evidence tasks:** 2 — VALID 1 (`mathlib_rounding_policy`), FORMAT_INVALID 1 (`textkit_style_guide`).
- Insufficient-evidence tasks with an executed mutation: 1.

## Gate classification (exactly one)
- **Validity V:**
  - 20 rows per arm
  - one harness sha256 across treatment and drift
  - one model digest across all arms
  - treatment overrides equal control overrides + `replacement_format_contract`
  - 0 invalid rows
  - control equals the control constants
  - treatment and drift rows carry `edit_proposals` and `format_contract_shown`
  - 0 UNCLASSIFIABLE proposals in every arm
  - drift within 1 of control on:
    - hidden-test passes
    - damaged tasks
    - cumulative edit executed
    - solvable tasks with ≥1 VALID proposal
  - Interpretation of the last drift check: a validity and comparability check between the frozen control measurement and the new-harness drift measurement. It does not establish general equivalence between truncated historical instrumentation and prospective full-text instrumentation.
  - Model-visible trajectory identity is descriptive only.
- **Mechanism integrity MI** (required):
  - MI1 contract exposure: `format_contract_shown` is true in 20/20 treatment rows and false in 20/20 drift rows.
  - MI2 proposal pairing: `edit_proposals` pair one-to-one, in order, with `edit_symbol` calls (count, path, target, selector_kind, success); any mismatch fails MI.
  - MI3 structural preservation:
    - For every successful python_symbol proposal, the target definition in `after_text` is AST-equal to the proposal's single statement (`ast.dump(..., include_attributes=False)`).
    - For every successful json_pointer proposal, the value at the pointer in `after_text` equals the parsed proposal.
    - This is structural equality, not exact source equality.
- **Safety S** (required, existing bounds, unchanged):
  - `damaged_file_tasks` ≤ 2
  - `lane_false_verified` = 0
  - false completion on insufficient-evidence tasks = 0/4
  - `stray_file_tasks` ≤ 0
  - leak tasks = 0
  - extraction without prior full read = 0
  - localized-hit tasks ≥ 6
- **Existing-guard invariant** (reported with safety, not a mechanism criterion, not a gate clause): number of FORMAT_INVALID proposals that executed (control 0).
- **Format F** (primary, frozen; denominators fixed). FORMAT_IMPROVED iff both:
  - treatment solvable tasks with ≥1 VALID proposal ≥ 9
  - treatment FORMAT_INVALID solvable proposals ≤ 4
- **Capability C:**
  - REGRESSION if treatment passes < 3
  - NO_IMPROVEMENT if 3 ≤ passes ≤ 5
  - IMPROVEMENT if passes ≥ 6

Classes:
1. **INCONCLUSIVE:** V fails.
2. **FAIL:** V holds and (MI fails, or S fails, or C = REGRESSION).
3. **PASS:** V, MI, S hold, F = FORMAT_IMPROVED and C = IMPROVEMENT.
4. **PARTIAL (a):** V, MI, S hold, F = FORMAT_IMPROVED and C = NO_IMPROVEMENT.
5. **PARTIAL (b):** V, MI, S hold, F not improved and C = NO_IMPROVEMENT.
6. **PARTIAL (c):** V, MI, S hold, F not improved and C = IMPROVEMENT (completion change not credited to the factor).

Interpretation limits (recorded before the run):
- Low power: one temperature-0 run; only 3 solvable tasks had exclusively FORMAT_INVALID proposals in control; 6 solvable tasks proposed no edit.
- The F threshold (+2 tasks) is fixed and not changed after treatment exposure.
- PARTIAL (a) supports only "more structurally valid replacement proposals were observed on dev".

## Pre-registered knowledge consequences
- **PASS:** new CAP, dev-supported: the format contract increased structurally valid proposals and completion on dev.
- **PARTIAL (a):** new CAP, dev-supported for structurally valid proposals only; H-012 update that format validity was a proposal-level bottleneck but not a completion bottleneck on dev.
- **PARTIAL (b):** CON, dev-supported: an explicit type-specific replacement-format contract did not increase structurally valid replacement proposals in this dev experiment.
- **PARTIAL (c):** registry note and H-012 observation; no CAP.
- **FAIL (MI):** implementation defect; not interpreted as a capability or format finding.
- **FAIL (S or regression):** CON recording the failure; not promoted.
- **INCONCLUSIVE:** registry only.

## Descriptive only (never gates)
- **Prominent:** insufficient-evidence tasks with an executed mutation (control 1), and their proposals' terminals.
- Per-call VALID rate; FORMAT_INVALID reason distribution; SELECTOR_FAILURE counts; solvable tasks with no proposal.
- Funnel per solvable task, recorded by trace classification in the analysis with fixed categories (correct / incomplete / wrong_target / cosmetic / not_applicable): proposed → format-valid → accepted by existing guards → executed on a gold file → semantically correct → hidden-test pass.
- Existing-guard invariant count; pass-set identities; prompt tokens; rounds; escalations; drift vs control trajectory comparison.

## Scorer plan
- `benchmark/scoring/qwen_formatcontract_v1.py`, written after this gate is frozen.
- It imports the frozen `benchmark/scoring/qwen_selectorkind_v1.py` metrics after verifying sha256 `135a71f9a866b09e6503007bf0e1be14d2d8d6c74d069f1a611dd4afd2ddac1d`.
- It does not import the EXP-20 replay (it reads truncated arguments).
- It implements the normative definition unchanged, plus V, MI1–MI3, S, F, C and the classes above.
- Before any treatment run it is run against the same synthetic cases and mutation-tested; its dry check uses only the frozen control rows and must reproduce the control constants.

## Out of scope
- Semantic reasoning aids; retries; completion feedback; repair
- Constrained decoding for replacements; examples in the contract
- Abstention (Q-003); selector changes; heldout runs; Gemma; coordination
