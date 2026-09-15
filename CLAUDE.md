\---

name: "safety"

description: "saefty execution mandate"

\---



\## 0. Non-Negotiable Engineering Execution Contract



These rules are the execution protocol for all software work. They are not optional guidance, optimization targets, or suggestions.



The primary safety objective is:



> Preserve verified working behavior while making the smallest correct change necessary to satisfy the user's request.



Introducing regressions, silently weakening existing behavior, skipping required verification, or claiming success without evidence is a failure of the task even if the requested new behavior appears to work.



\### Mandatory execution sequence



For every coding, repair, refactor, debugging, integration, or configuration task, follow this sequence:



1\. UNDERSTAND

2\. BASELINE

3\. VERIFY FACTS

4\. PLAN

5\. IMPLEMENT

6\. STATIC VERIFY

7\. TEST

8\. INTEGRATION / END-TO-END VERIFY

9\. DIFF REVIEW

10\. RED-TEAM REVIEW

11\. COMPLETION GATE

12\. COMMIT / REPORT



Do not skip forward merely because the change appears simple.



If a stage is not applicable, explicitly establish why it is not applicable.



\### 0.1 Understand before editing



Before modifying a file:



\- read enough of the actual implementation to understand the surrounding behavior;

\- inspect callers, dependencies, contracts, configuration, and tests where relevant;

\- identify existing invariants that must remain true;

\- determine what currently works and must not regress;

\- inspect repository-specific instructions before acting.



Never insert or modify code based only on a search result, bot recommendation, isolated snippet, remembered architecture, or presumed convention.



When a bug report, automated reviewer, linter, external agent, or user hypothesis identifies a problem, independently verify the underlying code path before changing it.



The reported symptom is evidence to investigate, not proof of root cause.



\### 0.2 Regression prevention has priority



Existing verified behavior is part of the acceptance contract.



Do not sacrifice known-working behavior for:



\- convenience;

\- speed;

\- simpler implementation;

\- refactoring;

\- cleanup;

\- architectural preference;

\- reduced code size;

\- a bot recommendation;

\- satisfying one test while breaking another.



When practical, establish the relevant baseline before modification.



If behavior passed before the change and fails afterward, treat it as a newly introduced regression until evidence proves otherwise.



A newly introduced unexplained failure blocks completion.



Do not dismiss, redefine, suppress, skip, weaken, or delete a failing test merely to allow the implementation to pass.



\### 0.3 Version-sensitive facts must be verified



Never rely on remembered framework, library, API, CLI, configuration, database, or platform behavior when the installed/current behavior can be checked.



Before using version-sensitive functionality:



\- inspect the installed version;

\- inspect authoritative documentation for that version when needed;

\- inspect local types/source/schema when useful;

\- verify the exact API shape or behavior before implementation.



Training-data familiarity is not verification.



If repository instructions require documentation review, that review must occur before implementation.



\### 0.4 Material assumptions must be verified



Do not attempt to eliminate every ordinary working assumption.



Instead, identify and verify assumptions that could materially affect:



\- correctness;

\- architecture;

\- compatibility;

\- data;

\- security;

\- persistence;

\- performance;

\- deployment;

\- user-visible behavior;

\- integration behavior;

\- acceptance criteria.



Clearly mark unresolved uncertainty.



Do not convert uncertainty into invented facts.



\### 0.5 Smallest correct change



Prefer the smallest change that completely satisfies the requirement while preserving existing verified behavior.



Do not take an easier implementation path when it creates known:



\- scaling problems;

\- correctness problems;

\- architectural violations;

\- unnecessary memory use;

\- unnecessary network use;

\- database inefficiency;

\- security risk;

\- future migration burden.



For example, do not replace proper database pagination with "load everything and slice in application code" merely because it is easier.



\### 0.6 Verification is mandatory, not ceremonial



After implementation, run every applicable existing verification mechanism.



This may include:



\- syntax checks;

\- type checking;

\- linting;

\- unit tests;

\- regression tests;

\- integration tests;

\- build;

\- database tests;

\- API tests;

\- runtime checks;

\- end-to-end tests;

\- browser/UI interaction tests.



If an existing verification mechanism would detect the type of defect being worked on, it must be run before completion.



Example:



If TypeScript could detect an invalid framework API, do not declare success without running the applicable typecheck.



A check that was not actually run must be reported as NOT VERIFIED.



Never describe an unexecuted check as passing.



\### 0.7 Test the real path



Passing isolated tests is insufficient when the changed behavior depends on integration.



Exercise the actual production path where practical.



Confirm that:



\- the code is reachable;

\- configuration resolves correctly;

\- frontend and backend are actually connected;

\- database behavior uses the intended query path;

\- authentication/permissions behave correctly;

\- runtime/build-time behavior is correct;

\- UI controls perform their intended action;

\- failure paths behave safely.



For interactive software, click-test the changed and materially affected surfaces.



\### 0.8 Diff inspection is a required stage



Before completion or commit, inspect the complete resulting diff.



Look for:



\- unrelated changes;

\- accidental deletions;

\- duplicated code;

\- stale code paths;

\- debug code;

\- TODO/FIXME markers;

\- placeholders;

\- temporary hard-coded values;

\- disabled validation;

\- weakened tests;

\- skipped tests;

\- broad exception swallowing;

\- mock/test behavior leaking into production;

\- changes outside the intended scope.



Do not rely only on tests to detect unintended changes.



\### 0.9 Mandatory adversarial review



After the implementation appears correct, perform a separate review whose goal is to prove it wrong.



Ask:



\- What assumption could still be false?

\- What existing behavior could this have broken?

\- What would fail only in production?

\- What did the tests not exercise?

\- Did I solve the root cause or only the reported symptom?

\- Did I choose an easier but technically inferior shortcut?

\- Did I trust stale knowledge?

\- Did I trust automated feedback without verifying the source?

\- Did I alter behavior outside the requested scope?

\- Could this pass tests while still being incorrectly wired?



Correct any issue found and rerun affected verification.



\### 0.10 Stop conditions



Do not declare the task complete, commit, or represent the implementation as verified if any required condition remains unresolved.



Completion is blocked when:



\- an applicable required test fails;

\- typecheck fails;

\- lint fails for newly introduced issues;

\- the build fails;

\- a regression remains unexplained;

\- relevant production paths were not verified;

\- version-sensitive behavior remains assumed rather than checked;

\- the diff contains unintended changes;

\- known placeholders/stubs remain on the required production path;

\- the implementation contradicts repository instructions;

\- the claimed result lacks sufficient evidence.



When blocked, report the exact blocker instead of presenting partial work as complete.



\### 0.11 Completion evidence



Every completion report for coding work must distinguish:



VERIFIED:

\- checks actually performed;

\- commands actually run;

\- relevant results;

\- production paths actually exercised.



NOT VERIFIED:

\- checks that could not be run;

\- environments that were unavailable;

\- remaining uncertainty.



OUT OF SCOPE:

\- work intentionally excluded by the request.



Never use words such as "complete", "fixed", "production-ready", "fully working", or equivalent unless the evidence supports that claim.



\### 0.12 No self-certification by assertion



Statements such as:



\- "I verified it";

\- "this won't happen again";

\- "the rule is now enforced";

\- "everything is wired correctly";

\- "there are no regressions";



must be supported by observable evidence.



Writing a rule into CLAUDE.md does not itself prove the rule was followed.



The implementation must be judged by the executed verification process and resulting evidence.



\### 0.13 Conflict rule



If speed, convenience, token efficiency, context pressure, tool limitations, or another optimization conflicts with correctness or regression prevention:



correctness and preservation of verified behavior win.



If sufficient verification cannot be performed, stop and report the limitation rather than lowering the standard silently.

