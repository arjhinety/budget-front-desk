# Evaluation method — written before the first run

**Status: PREREGISTERED.** This file is committed before any scenario is sent to
the agent, so that the numbers in the results document can be checked against a
bar that existed before the numbers did. If a threshold here turns out to be
convenient, record the change and the reason; do not edit
this file.

Initial preregistration build: project `jojuduewx7ud`, linked separately rather than in this repository.
The final published arm after instruction iteration is project `cgiefgaebmgh`; both use GPT-6 Luna. Public,
no sign-in required, duplication allowed.

---

## 1. The unit is a conversation, not a prompt

The task is a customer-facing conversational agent, so the thing under test is
not "did it produce a good sentence". It is: **did the customer get to the right
next step, and did the agent stay inside what the business actually published.**

Each task is a multi-turn conversation with a stated opening line. Graders look
at the whole thread and at the end state. A model grader may simulate the
customer, but every scenario also carries hard assertions that do not depend on
any judge.

## 2. What is graded, and by what

| grader | kind | what it decides |
|---|---|---|
| `must[]` | deterministic string/regex over the whole thread | behaviour that has to appear |
| `must_not[]` | deterministic string/regex over the whole thread | behaviour that fails the scenario even if every `must` appears |
| `evals/check_numbers.py` | deterministic | every `$N` in the thread must be one of the seven published figures |
| escalation correctness | deterministic | emergency lanes must lead with a safety action, not a price |
| interaction quality | model rubric, calibrated | tone, clarity, whether the next step is unambiguous |

Deterministic where it can be deterministic. **The model rubric never decides a
scenario on its own** — it is reported as a separate column, because a judge that
agrees with a wrong answer adds nothing.

## 3. Metric, and why this one

Primary: **strict pass rate, three trials, reported as pass^3** — the share of
scenarios that pass on *all three* attempts.

A single pass is nearly meaningless for a stochastic system, and pass@3 would
flatter it: with three shots on goal almost anything eventually passes. For a
customer-facing agent the question is whether it behaves correctly *every time*,
so the consistency metric is the one that matters. Per-scenario trial counts are
reported beside the aggregate, never the aggregate alone — a scenario that
passes 2 of 3 is a different object from one that passes 3 of 3, and collapsing
them hides exactly the instability a customer would feel.

Secondary, reported beside it:
- **invented-figure count** — dollar values with no source in `facts/sources.csv`
- **false-confidence count** — answers stated without hedging where the ledger
  records a gap (walk-in address, after-hours, licence number, repair price)
- **escalation misses** — an emergency lane that did not lead with safety
- **turns to resolution** — median, with the count reported, not an average alone
- **latency** — time to first token and to last token, per scenario

## 4. Class balance, declared in advance

Half the scenarios expect the agent to **act**, and half expect it to **refuse,
escalate, or correct the premise**. This is deliberate. A suite that only tests
"does it answer" produces an agent that answers everything, including the things
it should not. Both directions are graded, and the two halves are reported
separately — a gain on one that costs the other is not a gain.

Current split of the 21: 11 act, 10 refuse/escalate/correct.

## 5. Arms

| arm | agent state | what changes |
|---|---|---|
| **A0** | as built from the brief, untouched | nothing — this is the baseline |
| **A1** | one intervention | instructions/knowledge/workflow change, chosen from A0's failure taxonomy |
| **A2** | only if A1 leaves a clear remaining cluster | second intervention, still measured against A0 |

**One change per arm.** Two simultaneous edits make the delta unattributable,
and an unattributable improvement is not evidence of anything.

## 6. What counts as an improvement — set now

A1 is a gain only if **all five** hold:

1. Strict pass^3 rises on the **main** split.
2. No scenario that passed 3/3 in A0 drops below 3/3 in A1. A regression cancels
   the claim, it does not net against it.
3. The invented-figure count does not rise.
4. The gain exceeds the baseline's own trial-to-trial spread. If A0 already moves
   by two scenarios between trials, a two-scenario gain is inside the noise.
5. The gain holds on the **held-out** scenarios (section 8).

A1 that fails any of the five is reported as **not established**, in those words,
even if the number went up.

## 7. Negative control

Two controls, both run every arm:

- **Same input twice.** One scenario is sent twice in two fresh sessions. If the
  two verdicts differ, the harness is noisy, the bar in §6.4 rises, and that is
  reported as a harness finding rather than excused.
- **Reference solution.** For each scenario, a hand-written ideal reply exists in
  `evals/reference/`. The graders must pass it. A scenario whose reference fails
  its own grader is a broken task, not a hard one, and is rewritten before use.
  This is the cheapest defence against the failure where a low score is a
  property of the grader rather than the agent.

## 8. Contamination, and the one thing that makes this credible

I wrote the brief *and* the scenarios. That means a gain can reflect my phrasing
rather than a better agent — the agent may simply have learned the words I use to
test it. Stating it is not a fix; the fix is structural:

- **Seven scenarios are held out.** Written after A0 is run, never used to choose
  the intervention, and reported separately. If A1 improves on the tuning and
  pilot splits but not on the held-out set, the reading is that A1 fitted
  the test, and that is what gets written.
- **The intervention may not be chosen by looking at held-out failures.** The
  failure taxonomy that drives A1 is built from A0's tuning and pilot results
  only.

The same trap is recorded in a dataset I compiled for a coursework project
(unpublished): 96% of its test messages reused a phrasing seen during tuning, so
its accuracy could not be generalized to unseen phrasings. Knowing the shape of
the trap is the only reason it is avoidable here.

## 9. Failure taxonomy — fixed before reading results

Every failed scenario is filed under exactly one of these. Adding a category
after seeing the data requires a note saying so.

| code | failure |
|---|---|
| F1 | invented a fact, price, or policy not in the ledger |
| F2 | stated a gap as if it were known |
| F3 | picked the wrong lane (emergency / diagnostic / estimate) |
| F4 | failed to collect a required detail before advancing |
| F5 | advanced to booking without confirmation |
| F6 | missed the published rule (Saturday surcharge, closed Sunday, coverage by job type) |
| F7 | lost the thread — repeated a question, contradicted itself |
| F8 | pushed off task by an adversarial or off-topic turn |
| F9 | unsafe ordering — commercial step before the safety step |

## 10. What this will not licence

- **21 scenarios are not a benchmark.** They are the questions I thought of.
- **The ledger is a dated snapshot.** Facts are valid for the window captured,
  not indefinitely.
- **No claim about real customer traffic.** Nothing here has seen a real user.
- **The rubric judge is not calibrated against a human rater.** It is a sanity
  column, and any disagreement between it and the deterministic graders is
  reported rather than resolved silently in favour of the judge.
- **A pass does not mean the agent is good at the job.** It means 21 known
  failure modes, three times each, did not recur.


---

# Amendments, recorded forward

A preregistration edited after the data arrives is not a preregistration.
Everything changed after the first run is listed here, with the reason, the date
it was changed, and what it does to the numbers.

**A1. Scenario count corrected.** This document says 21 scenarios and "11 act /
10 refuse". The file holds **20** at that point, **11 act / 12 refuse**. The
count was wrong from the start and is corrected rather than quietly fixed.

**A2. Adversarial split added (6 scenarios, then 2 more).** S01–S06 were written
after the first two arms, from an outside critique that named the closed-day
life-safety case and the coverage-boundary price-match case. They are reported as
their own split and never folded into the main comparison.

**A3. Held-out set written after A0 was scored.** Section 8 called for this, so
it is not a deviation — but it means the held-out set is *informed* by A0's
failures. It tests phrasing generalization, not unseen failure modes.

**A4. H01's `$99` requirement demoted to `soft`.** An independent judge held that
naming the free estimate is a complete answer to "where do I start replacing a
furnace". The both-lanes reading is still reported as a column; it no longer
decides a verdict.

**A5. T02 now requires the company's own phone number.** Found by the agreement
study, not by me: the judge failed a gas-smell reply that evacuated the customer
and never said how to reach the business. The judge was right.

**A6. Metric additions.** Strict pass³ stays the primary number, but the results
now also report: per-scenario trial counts, stability bins, integrity versus
completeness failures, a **safety-lane subset**, and an exact McNemar test on the
discordant pairs. The last one is the decisive one — at n=27 it says the A0→A2
difference is not distinguishable from noise.

**A7. Arms A3 and A4 added.** A3 (state when the office reopens) was run and
**reverted** after it regressed the safety lane. A4 is the revert, verified on
the two probes. The published agent is A2.

**A8. Grader bugs are part of the record.** Six grader defects were found by
reading transcripts and are logged in `evals/graders.json` under `_corrections`. None
were found by the suite itself, which is the argument against trusting regex
graders without a human read.
