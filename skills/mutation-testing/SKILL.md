---
id: mutation-testing
version: 1
---

# Skill: mutation-testing

## purpose
Show that the tests protecting a guard, validator or state machine actually fail when the mechanism is broken, instead of assuming protection because the normal tests pass.

## applies_when
- a new guard, refusal, latch, counter, reset or validator rule was implemented
- tests for such a mechanism pass on the first run
- a scorer's classification or bookkeeping logic must be shown to discriminate

## does_not_apply_when
- the change is documentation or configuration with no executable behavior
- the mechanism is a frozen artifact that must not be imported in mutated form for scoring (mutate only in a scratch process)

## required_inputs
- the mechanism source file and the exact anchors of the logic to break
- the test file(s) that claim to protect it
- the scratchpad directory for mutation scripts

## preconditions
- the normal tests pass unmodified
- the working tree state of the mechanism file is known (mutations must not touch the file on disk)

## procedure
1. List meaningful mutations for the mechanism: never trigger (no-op guard), trigger always, skip escalation, wrong release/transition condition, counter not reset, reset per round instead of per task, missing task-start reset, re-arm while already armed, dropped extra-statement or attribute checks.
2. Write a scratchpad script that reads the mechanism source, asserts each anchor occurs exactly once, applies the replacement in memory, registers the mutated module in `sys.modules` under its real name, and runs the protecting tests with pytest (unique `--basetemp` per mutation).
3. Run each mutation separately and record `N failed, M passed`.
4. For each surviving mutation, decide whether it is equivalent (no observable behavior change; explain why) or a test gap.
5. For a test gap, add the smallest test that distinguishes the mutation, then rerun that mutation and confirm it is caught.
6. For an equivalent mutation, prove the protected property another way (for example, remove both redundant resets and confirm a test fails).
7. Confirm the mechanism file on disk is unchanged (`git diff` shows only intended edits) and the normal tests still pass.
8. Record mutation results in the experiment log implementation section.

## invariants
- A mechanism is not considered protected merely because its normal tests pass.
- Mutations happen in memory or in a scratch copy; the tracked source is never left mutated.
- Every surviving mutation is classified as equivalent (with a reason) or fixed by a new test.

## acceptance_criteria
- Every meaningful mutation causes at least one test failure, or is recorded as equivalent with a demonstration.
- Test gaps found were closed and re-verified.
- Normal tests pass afterwards and the mechanism source matches the intended implementation.

## evidence_to_record
- mutation names with fail/pass counts
- equivalent mutations and the reasoning or combined mutation that proves the property
- tests added because of mutation findings

## failure_modes
- anchor text matches zero or several places: the script must assert exactly one match
- mutated module not actually loaded (tests import a cached original): confirm with a mutation that must fail everything (never-trigger)
- treating a surviving mutation as fine without analysis (EXP-20 unparse normalization was a real gap; EXP-21 release-only counter reset was equivalent)

## related_CAP_CON_METH_records
- METH-001
- CAP-008
- CAP-009
