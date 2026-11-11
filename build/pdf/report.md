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

Separate validation checks do not confirm the development gain.

## Multi-turn and sealed

Multi-turn (18 scripts, three trials each): baseline **36/54**,
A5 **41/54**; 7 gains and 2 losses
(p=0.180, not significant). Sealed (20
scenarios, different author, graders frozen before replies): **17/20
baseline, 17/20 A5**; after cleaning one render artefact,
**16/19 A5 overall**. No demonstrated advantage or regression.


## Grader audit

Two blinded model reviewers (Gemini and Claude) labelled all 99 conversations
without seeing the arm or machine verdict. In 19 rows both said PASS where the
grader said FAIL; in zero shared rows did both say FAIL where the grader said
PASS. The grader is **over-strict in both arms at a similar rate**, so reported
pass rates are conservative. Two verified false passes were also found. Details
in `docs/MODEL-REVIEW.md`.

## Remaining failures

- **Scheduling: 4/9 all-three passes.**
  Some replies omit the required hours or Saturday surcharge.
  **Handoff: 1/2.** A multi-unit outage misses escalation.
- Six membership-script conversations fail in **both arms** on benefits omitted
  from v1; some also omit required pricing.
- There are **21 logged grader corrections** plus the model audit above.

## Build provenance and evidence
Single-turn files label the original project `jojuduewx7ud`; the linked rebuild
`cgiefgaebmgh` was measured directly in multi-turn and sealed runs against a
separate baseline rebuild. The evaluated brief used 24 fields; the current ledger
has 25, but v2 is not evaluated. All test sets and runs are in the repository.
The published agent link is supplied separately.
