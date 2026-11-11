# Budget Front Desk

A public Luna agent for **Budget Heating, Cooling & Plumbing** (St. Peters, MO),
built from their website, tested with realistic and adversarial conversations,
improved, and retested. The company is not involved; see `NOTICE.md`.

The published agent link is shared separately. This repository holds the test
sets, transcripts, instruction changes, graders, failures, and everything needed
to check the numbers.

## Before and after

| | A0 baseline | A5 tuned |
|---|---:|---:|
| single-turn, all three trials pass | 26/53 | **43/53** |
| multi-turn, 54 conversations | 36/54 (67%) | **41/54 (76%)** |
| sealed set, 20 independent scenarios | 17/20 | 17/20 |

The single-turn gain is in-sample (p < 0.001 on the shared 53 scenarios). The
multi-turn gain is positive but not statistically settled (p = 0.18). The sealed
set, written by a different model with graders frozen before any reply existed,
shows no measurable difference. The grader is over-strict in both versions at a
similar rate, so the reported pass rates are conservative.

## What changed and what it fixed

Five instruction arms were tried; two regressed and were reverted.

**A1: "End every reply with a next step."** The agent chose "reply in chat" and
dropped the phone number from a burst-pipe emergency. Worse.

**A2: "The next step must be an external action."** Fixed A1. Coverage and
diagnostic scenarios jumped from 1/8 to 6/8 and 6/10 to 10/10. But scheduling
and off-task replies got worse: the agent stopped stating hours when asked about
a specific day.

**A3: "Say when the office is closed."** The agent queried a clock tool and
contradicted a customer reporting a Sunday-night gas smell. Reverted.

**A5: A2's external-action rule, plus after-hours handling that uses the
customer's stated time and forbids clock checks.** Recovered the scheduling and
off-task losses without losing the coverage gain. This is the shipped arm.

| Requirement group | A0 | A5 |
|---|---:|---:|
| Coverage | 1/8 | **7/8** |
| Diagnostic | 6/10 | **10/10** |
| Free estimate | 6/8 | **8/8** |
| Trust | 3/5 | **5/5** |
| Emergency | 4/8 | **6/8** |
| Scheduling | 3/9 | **4/9** |
| Off-task | 2/3 | **2/3** |
| Handoff | 1/2 | 1/2 |

## Limits

- The single-turn comparison is in-sample: A5 and its graders were iterated on
  the same 53 scenarios. The sealed set exists to check for that, and it found
  no advantage.
- The linked agent is a rebuild (`cgiefgaebmgh`); its direct measurements are
  the multi-turn and sealed runs. Single-turn files label the original project.
- Two blinded model reviewers (Gemini and Claude, neither the grader author)
  independently found the grader rejects correct replies at a 12–46% rate, but
  rarely lets wrong replies through. The bias is similar in both arms, so the
  before/after direction holds even though the absolute rates are too low.
- The platform does not expose skill/knowledge file contents, so a fully verified
  effective-configuration snapshot was not possible.
- Scheduling (4/9) and handoff (1/2) remain weak.

## What is here

| file | what it is |
|---|---|
| `RESULTS.md` | every arm, the paired tests, the grader corrections, the platform findings |
| `FAILURES.md` | the four failure patterns and which arm they appear in |
| `RIGOR.md` | how the agent was built and what it does **not** claim |
| `FINDINGS-FOR-AGENTPLACE.md` | findings for the platform team |
| `build/pdf/report.pdf` | two-page summary |
| `build/brief.txt` | the brief that produced the agent |
| `build/captured/` | current published instructions for both arms |
| `facts/sources.csv` | every ledger field with its source page and line |
| `evals/results/` | all recorded conversations |
| `evals/scenarios*.json` | 33 hand-written + 55 generated + 18 multi-turn + 20 sealed scenarios |
| `evals/human/GUIDE.md` | the frozen review guide |
| `docs/MODEL-REVIEW.md` | the two-model grader audit |
| `docs/PRE-RUN-AUDIT.md` | provenance discontinuity and grader flags |
| `platform/` | three proposed structural fixes, implemented and tested |
| `NOTICE.md` | the business relationship and takedown |

## The pipeline

```
scrape.py          11 pages -> raw/*.html + raw/*.txt + facts/provenance.json
build_facts.py     the text -> facts/business.json + sources.csv + parameters.csv
generate_brief.py  the ledger -> build/brief.txt -> build/builder_url.txt
drive.mjs          the brief -> the Agentplace Builder
evals/run.mjs      scenarios -> the published agent -> evals/results/*.json
evals/grade.py     results + graders -> pass/fail per trial
evals/stats.py     paired McNemar + bootstrap
platform/          nextstep.py, clock.py, precedence.py + 16 tests
```

`build_facts.py` fails if a price moves or the evidence is placeholder text.

## Open questions

These are documented rather than hidden; they do not block the submission.

1. The grader's false-fail rate is high. Two independent model families confirm
   it. The recorded scores stay; the model audit is a separate layer.
2. The ledger says no street address is published; the site publishes one. The
   agent states the real address. This is a known ledger error, not corrected
   mid-application because the v1 hash chain must stay intact.
3. Two builds from the same brief answer membership questions differently. The
   cause is unknown; `docs/FINDING-club-knowledge.md` has the evidence.
4. A fully verified rerun would need the platform to expose skill contents. The
   offline tooling for it is built; the data gate stays blocked.
