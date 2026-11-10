# Next experiment: preparation only

**Collection is blocked. No new agent evaluations or published-agent edits are authorised by this file.** All historical sets, captures and original scores remain in place. The 20-scenario sealed set supplements, rather than replaces, the 33 hand-written and 55 generated single-turn sets.

## Order of work

1. Repair the scorer and arm-blind export, with synthetic tests for correct passes, false passes, false failures, exclusions and joining.
2. Freeze `evals/human/GUIDE.md`, then export historical captures into a new private labelling directory. The human receives only `sheet.csv` and `GUIDE.md`, never `private/key.json` or the machine verdicts.
3. Label the 39 eligible sealed conversations and a stratified development audit. Record PASS, FAIL or UNSURE, recognition and reasons. Existing captures are familiar to the author; describe the result as retrospective rubric calibration, not independent validation.
4. Preserve human-vs-machine disagreements separately. Do not silently patch old scores or use the sealed replies to choose a new agent fix.
5. Obtain a current configuration capture for every intended arm, distinguish observed publication/revision from intended text, and settle policy ambiguity before freezing new cases.
6. Independently author and review fresh cases, bind expected facts to available inputs, validate prospective graders with both correct and incorrect controls, and freeze all artefact hashes before any new reply exists.
7. Start collection only after explicit user authorisation and a passing preflight. A prepared schedule is not permission to execute it.

## Historical configuration recovery

`build/recovered/cgiefgaebmgh/` contains a 38-line instruction file, a 76-line skill file and the A5 builder request recovered read-only from a saved build trace. `capture.json` records their hashes and limitations. These are historical UI read-backs, not proof of the current effective publication. Hidden system context, full source inventory, runtime model configuration and publication equivalence remain unverified.

Do not reconstruct the missing configuration by paraphrasing RESULTS and label it an export. A snapshot of intended inputs is useful but must remain labelled intended. Raw authenticated export receipts and actual target URLs stay private; public evidence may contain project IDs, hashes, capture scope and explicit unknowns.

## Candidate intervention

The candidate is **one scheduling-disclosure block**, not a combined scheduling/coverage/handoff fix. It asks for the relevant posted day hours and applicable Saturday addition before asking the customer to agree, preserves the customer's stated time, and makes no availability promise. The proposed text and diff are under `build/next-run/` and have not been sent to Builder.

This is a prospective completion requirement. It must not be silently used to judge historical clarifying-first replies as incorrect. Confirm that historical human review identifies a real, relevant gap before finalising this candidate. If another target is selected, record the decision before fresh-case replies exist and replace the candidate before the freeze, not during the run.

Coverage ambiguity and missing membership benefits are **not** part of this treatment. In particular, do not convert the v1 water-heater/diagnostic conflict into a firm rule merely because a reviewer prefers one interpretation. A v2 benefits change is a separate future experiment. Keep test-choice UI settings unchanged between the comparison conditions unless a separate, recorded baseline change is agreed before collection.

## Diagnostic pilot design

The proposed fresh corpus has 24 targeted scenarios with three trials each and 24 regression tripwires with one trial each. That is 96 conversations per arm per phase, 384 across the four cells, plus any explicitly budgeted capture/fingerprint checks. These counts define a diagnostic pilot, not a demonstrated power calculation or a promise to fit one quota window.

- **Before:** current published treatment build P and a nominally matching reference build R.
- **After:** P receives the one predeclared in-place edit; R remains unchanged.
- Freeze P's candidate edit before viewing the fresh baseline replies. Do not tune against this corpus after collection begins.
- Compare the two baseline builds as A/A evidence. Their disagreement includes model randomness and capture error, not just rebuild variability. One pair of builds cannot estimate platform-wide rebuild variance.
- Report treatment change, reference drift and their difference. The reference does not prove parallel trends or remove all confounds. An edit that triggers a rebuild must be disclosed.

Assign stable scenario and template-group IDs before freezing. Counterbalance arm order within scenario/trial pairs, retain invalid attempts with reasons, and resume missing counterparts rather than rerunning whichever arm did badly. A quota interruption does not make an incomplete pair a pass. Public results must identify the intended arm/configuration/phase; private per-record receipts retain the observed target URL and capture identity.

## Outcomes and analysis

Integrity and completeness are separate. Integrity concerns invented prices/policies, unsupported bookings/notifications, unsafe instructions and template leaks. Completeness concerns the declared requirements of the case. Human labels adjudicate semantic disagreements; automated patterns are not ground truth.

Analyse case-level trial fractions, not arbitrary A0 trial 1 versus A5 trial 1 pairs. Report strict-all-trials stability descriptively. Targeted cases and tripwires remain separate. Resample template groups for uncertainty intervals so county/wording variants do not masquerade as fully independent cases. The prospective analyser is `evals/analyze_pilot.py`; it consumes a canonical observation file, never starts collection, and reports missing or invalid cells.

No automatic success rule is based on p < 0.05. A small/null result is reportable. Attribute only the declared treatment bundle and measured configuration; do not claim that each instruction component caused a separate effect.

## Stop and release rules

- Missing guide, required configuration evidence, scenario/expected-fact mapping, prospective graders or control results blocks collection.
- Missing or changed hashes, wrong targets, mismatched phase/configuration on resume, or failed capture controls invalidate the affected stage. Keep the evidence and reason.
- Unexpected unsafe claims require stopping the affected collection for review, not discarding failures.
- Stop at the planned sample. Do not add repeats to obtain significance or change graders after seeing new outputs without declaring a separate post-hoc analysis.
- Human-labelling completion and current effective configuration verification remain explicit dependencies. Neither may be ticked off because files or scripts exist.

## What is already possible offline

Export and score existing captures, validate agreement calculations, preserve immutable evidence receipts, generate counterbalanced schedules, check snapshot hashes, and test readiness failures using synthetic fixtures. These activities are not live evaluations.
