---
title: "Budget Front Desk"
subtitle: "An agent built from public business pages, measured before and after"
date: 2026-11-10
---

# The deliverable

A live Luna front desk for Budget Heating, Cooling & Plumbing, built from a
**24-field v1 brief** with page-and-line provenance. The current ledger has 25
fields after adding the omitted membership benefits; v2 has not been evaluated.
The agent triages requests, uses the catalogue, collects intake and routes to a
booking page or phone. All large test sets and recorded runs are retained.

# Before and after

| | A0 baseline | A5 instructions |
|---|---:|---:|
| single-turn pass@1, respective 53/55 scenarios | 113/159 (71.1%) | 145/165 (87.9%) |
| strict pass³, shared 53 scenarios | 26/53 | **43/53** |
| single-turn integrity-gate failures | 0/53 | 0/55 |
| multi-turn, 54 conversations | 36/54 (67%) | **41/54 (76%)** |
| multi-turn scripts passing all trials | 9/18 | **12/18** |

The paired strict-pass result favours A5 on the development set (b=18, c=1,
p<0.001). Pass@1 uses different denominators and is descriptive. The original
single-turn metadata names project `jojuduewx7ud`; the linked A5 rebuild,
`cgiefgaebmgh`, has its own multi-turn and sealed measurements. The multi-turn baseline
now exists: A0 is 36/54 and A5 is 41/54. A5 gains 7 conversations and loses 2;
McNemar p=0.180. The measured direction is positive, but the multi-turn delta is not
statistically settled. These are three trials of 18 scripts, not 54 independent
customers; one gain is A0's unfilled-placeholder integrity failure, so the clean
behavioural signal is narrower than 7 versus 2.

# What changed

A1's generic route instruction permitted "reply in chat". A2 required an external
destination. A3's hours instruction prompted a clock-based contradiction; A5
kept the customer's stated time and forbade clock checks. The arm history retains
the regressions as well as the selected changes.

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

- The single-turn comparison is in-sample. There are **21 logged corrections**:
  20 from transcript inspection and one from a positive control. Corrections 20
  and 21 repaired amount checks that rejected valid arithmetic, including
  $99 + $150 + $50 = $299. No frozen scenario rubric was changed.
- Six failing A5 conversations include savings-club expectations absent from the
  brief; some also miss a required diagnostic price. The overnight example in
  MT-P02 declines service but fails a wording-sensitive regex. Scores are unchanged.
- One build showed website-accurate savings-club benefits that were absent from the
  brief while another build declined. The cause is unknown; the repository reports it
  as an open platform question, not as a proven defect.
- A human calibration reached κ=0.911 only after the rule was fitted to the same
  30 transcripts; it is not fresh-sample agreement.

The complete evidence is in `RESULTS.md`, `RIGOR.md`, `FAILURES.md` and
`FINDINGS-FOR-AGENTPLACE.md`. The live agent link is supplied separately.
