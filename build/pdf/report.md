---
title: "Budget Front Desk"
subtitle: "An Agentplace Luna agent: failures, changes, and the rerun"
author: "Arjhine A. Ty · Prepared for Agentplace · 2026-11-11"
---

# What I built and tested

A public Luna front desk for **Budget Heating, Cooling & Plumbing**, built from
its public website. It answers price and service-area questions, triages
emergencies, and routes to a booking page or phone. The company is not involved;
the agent has no connection to its calendar or CRM.

The corpus retains **33 hand-written and 55 generated single-turn scenarios**,
**18 scripts of three turns each**, and **20 sealed validation scenarios**.
Tests include missing details, unknown prices, off-topic requests and pushback.
The main single-turn comparison and multi-turn scripts run three trials each.
A pass requires the specified facts and next step, with no forbidden claim.
“All-three pass” means the scenario passed every trial.

# Changes made, including the regressions

**A0 is the baseline; A5 is the selected instruction set.** A generic next-step
instruction first produced “reply in chat” instead of the phone number. Requiring
an **external action** repaired that, but introduced scheduling and off-task
regressions. Asking when the office reopens then triggered a clock check that
contradicted a Sunday-night emergency. That edit was reverted. A5 retained the
external action and forbade clock-based contradictions of the customer's stated time.

# Before and after on the shared development set

> **All-three passes: 26/53 → 43/53.**
> This is **in-sample**: the scenarios guided instruction and grader iteration.

| Requirement group | Baseline | A5 instructions |
|---|---:|---:|
| Coverage | 1/8 | 7/8 |
| Diagnostic | 6/10 | 10/10 |
| Free Estimate | 6/8 | 8/8 |
| Trust | 3/5 | 5/5 |
| Emergency | 4/8 | 6/8 |
| Scheduling | 3/9 | 4/9 |
| Off-Task | 2/3 | 2/3 |
| Handoff | 1/2 | 1/2 |

There are 18 gains and 1 loss (paired McNemar p<0.001).
Most gains now state the $99 diagnostic or coverage rule. The lost sewage score
reflects a pattern that misses keep-away wording, not established loss of safety
advice. The external-next-step version reached 40/53.
This sequential comparison is not a controlled ablation.

# Validation and remaining work

The positive development result is not confirmed on the separate validation
checks. These scores are automated rubric outcomes, not independently established
customer success rates.

## Multi-turn: a positive but uncertain difference

Across 18 scripts with three trials each, baseline passes
**36/54** and A5 **41/54**; scripts passing all trials move
from 9/18 to 12/18.
There are 7 gains and 2 losses (nominal paired p=0.180,
not statistically significant).
Trials repeat scripts, so they are not 54 independent customers.
Observed gains are concentrated in arithmetic and pushback, not a demonstrated
effect of the instructions. One gain is the baseline's template-placeholder failure.

## Sealed: no demonstrated advantage

The 20 scenarios, each three turns long, were authored by a different model.
Scenario rubrics were frozen before replies. Before the render exclusion, totals are
**17/20 baseline and 17/20 A5**;
the subset not flagged as ambiguous is 12/13 versus
11/13.

A post-run mechanical amount-check fix, applied to both arms, moved A5 from
10/13 to 11/13; baseline was unchanged.
Separately, cleaning excluded one A5 pass containing an appended render error,
leaving **16/19 overall and 10/12 on the unambiguous subset**.
Baseline had no exclusion. The small set does not establish equivalence or regression.

## Remaining failures and grading limits

- **Scheduling: 4/9 all-three passes.**
  Some replies omit the required hours or Saturday surcharge.
  **Handoff: 1/2.** A multi-unit outage misses escalation.
- Six membership-script conversations fail in **both arms** on benefits omitted
  from v1; some also omit required pricing. These are mixed authoring and agent gaps.
- There are **21 logged grader corrections**: 20 from transcripts, one from
  a positive control. A correct overnight refusal still fails a wording-sensitive
  check; its recorded score is retained. Human calibration reused the same
  transcripts after a rule clarification, so it is not fresh-sample validation.

## Build provenance and evidence

Single-turn files label the original project `jojuduewx7ud`. Validation compares
the A5 rebuild `cgiefgaebmgh` with a **separate baseline rebuild**,
`guikfrraxzk5`; build differences are an additional confound. The evaluated brief
used 24 sourced fields. The current ledger has 25; its corrected v2 is not evaluated.
Two builds also answered membership questions differently; the cause remains unknown.

All recorded runs are retained. The 20 sealed scenarios supplement, rather than
replace, the larger development sets.

All test sets, runs, instruction history and findings:
[github.com/arjhinety/budget-front-desk](https://github.com/arjhinety/budget-front-desk).
The published agent link is supplied separately.
