---
title: "Budget Front Desk"
subtitle: "An agent built from public business pages, measured before and after"
date: 2026-11-10
---

# The deliverable

A live AI front desk for Budget Heating, Cooling & Plumbing, built from a **25-field
ledger** with page-and-line provenance. It triages emergency, diagnostic and estimate
requests, uses the published catalogue, collects dispatcher intake, and routes to the
booking page or phone. The repository contains the ledger, transcripts, graders,
failures and reproducible scripts.

# Before and after

| | A0 baseline | A5 shipped |
|---|---:|---:|
| single-turn pass@1 | 113/159 (71.1%) | 145/165 (87.9%) |
| strict pass³, shared 53 scenarios | 26/53 | **43/53** |
| integrity-gate scenarios | 0/53 | 0/55 |
| multi-turn, 54 conversations | 36/54 (67%) | **41/54 (76%)** |
| multi-turn scripts passing all trials | 9/18 | **12/18** |

The tuned arm is better on the scenarios it was iterated against: 71.1% to 87.9%,
with the paired strict-pass comparison b=18, c=1, p<0.001. The multi-turn baseline
now exists: A0 is 36/54 and A5 is 41/54. A5 gains 7 conversations and loses 2;
McNemar p=0.180. The measured direction is positive, but the multi-turn delta is not
statistically settled. These are three trials of 18 scripts, not 54 independent
customers; one gain is A0's unfilled-placeholder integrity failure, so the clean
behavioural signal is narrower than 7 versus 2.

# What changed

The largest multi-turn gains are **arithmetic (2/9 to 5/9)** and **pushback (5/9 to
7/9)**. Memory stays 9/9 in both arms; recovery stays 9/9; change-of-mind stays 3/9.
One A0 failure emitted an unfilled template placeholder; A5 passed that conversation.

# The check I could not tune against

Twenty three-turn scenarios were authored by a different model, with graders frozen
before replies existed. On the original run A0 and A5 both scored **17/20**, agreeing
on 18/20; on the 13 unambiguous scenarios A0 scored 12/13 and A5 11/13. One A5 reply
was then excluded by deterministic cleaning because a render failure was appended to
a complete answer; excluding it leaves A5 at 16/19 overall and 10/12 on the scored
scenarios. The result does not confirm the single-turn gain out of sample, and the
set is too small to call it a regression.

# Limits and failures

- The single-turn comparison is in-sample: A5 and its graders were iterated against
  the same scenarios. Twenty grader corrections were made, all after transcript
  inspection; correction 21 fixed a positive-control bug allowing correct three-term
  totals such as $99 + $150 + $50 = $299.
- Six multi-turn failures were authoring gaps: the brief omitted savings-club
  benefits. The remaining failures are agent misses on hours, overnight constraints,
  and some arithmetic/change-of-mind turns.
- One build showed website-accurate savings-club benefits that were absent from the
  brief while another build declined. The cause is unknown; the repository reports it
  as an open platform question, not as a proven defect.
- A human calibration reached κ=0.911 only after the rule was fitted to the same
  30 transcripts; it is not fresh-sample agreement.

The complete evidence is in `RESULTS.md`, `RIGOR.md`, `FAILURES.md` and
`FINDINGS-FOR-AGENTPLACE.md`. The live agent link is supplied separately.
