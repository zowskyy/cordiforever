---
id: ci-offload
version: 1
---

# Skill: ci-offload

## purpose
Decide which deterministic work runs on GitHub CI instead of the laptop, and keep CI a verifier of research artifacts rather than an experiment runner.

## applies_when
- adding or changing a check, validator or test that should run on every push
- deciding whether to run a broad suite locally or leave it to CI
- a CI failure needs diagnosis

## does_not_apply_when
- running model inference or experiment arms (always local unless equivalence is separately validated and pre-registered)
- executing a single-use frozen scorer (never in CI)

## required_inputs
- `.github/workflows/ci.yml` (jobs integrity → quality + tests → project-validation → artifact-checks)
- the check command and whether it is deterministic, read-only and dependency-free
- `scripts/ci_pytest_gate.py` known environment failures, if tests are involved

## preconditions
- the check does not call a model, download models, or write experiment evidence
- the check produces the same result on Linux as on the local Windows machine, or its environment difference is documented

## procedure
1. Classify the work: model inference or scorer execution stays local; deterministic tests, validators and frozen-artifact checks go to CI.
2. Run only narrow local checks before pushing: the tests touching the change, the changed validator, `python scripts/validate_research_state.py`, `python scripts/verify_frozen_artifacts.py`.
3. Add a new CI step to the existing job whose scope matches (validators in project-validation; evidence checks in artifact-checks); do not create a new workflow for a single command.
4. Keep CI read-only for evidence: no manifest writes, no result writes, no scorer execution; checks report into `ci-reports/`.
5. Record provenance for commands whose results are cited (`scripts/ci_provenance.py`).
6. Commit, push, and follow the CI run to completion (`gh run list`, `gh run view`).
7. On a CI failure, diagnose the root cause from the logs; fix real defects; document genuine environment differences in the pytest gate only with evidence; never change code merely to make CI green.
8. Report the CI run id and result in the completion report.

## invariants
- CI verifies research artifacts; it does not become an uncontrolled experiment runner.
- Local model inference remains local unless equivalence is separately validated.
- Single-use scorers do not run automatically in CI.
- Evidence is never cached, regenerated or mutated by CI.
- The full test suite runs on GitHub, not by default on the laptop.

## acceptance_criteria
- The new check runs in the intended existing CI job and passes on the pushed commit.
- No CI step executes inference, scorers or evidence writes.
- The narrow local checks passed before the push.

## evidence_to_record
- the CI step added and its job
- local narrow check results
- CI run id, commit SHA and result

## failure_modes
- a check that needs a dependency not installed in its job (project-validation installs nothing): keep validators dependency-free or install explicitly
- Windows-only test failures misread as regressions: consult the documented known environment failures
- CRLF/LF rewriting breaking hash checks: `.gitattributes` `* -text` must stay

## related_CAP_CON_METH_records
- METH-009
- METH-010
