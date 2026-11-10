# Findings, for the Agentplace team

Written to be read by the people who build the platform. Everything here is
reproducible from the repository; the transcripts are in `evals/results/`.

Two things I'd want to know if I were on your side of the table, and one thing I
got wrong.

---

## 1. Multi-turn omissions and a grader wording miss

18 three-turn scripts, 54 conversations per arm. The tuned arm is **41/54 (76%)**
and the baseline is **36/54 (67%)**: a directional difference, not a significant
one (exact paired McNemar p = 0.180). A5 gains 7 conversations and loses 2, with
45/54 paired outcomes agreeing. The gains are concentrated in arithmetic (2/9 to
5/9) and pushback (5/9 to 7/9); memory, recovery, change-of-mind and
self-correction do not show a clean broad shift.

One apparent gain, `MT-C03#3`, is A0 emitting an unfilled placeholder while A5 does
not. That is a genuine baseline integrity failure, but not a clean behavioural win.
The full paired result is in `RESULTS.md`; this note does not call it validated
multi-turn transfer.

These are automated rubric outcomes, not 13 confirmed agent defects. Six failing
conversations include membership expectations absent from the brief; some also
miss a required price. The overnight example below is a grader wording miss.

**It does not state opening hours when asked about a specific slot.**

> Customer: *"i need a saturday tune up"*
> Agent: *"A Saturday tune-up fits One-Time HVAC Cleaning and Maintenance — $150 per
> system..."* — the price and the surcharge, never the hours.

The brief says, in as many words: *"Open Mon–Fri 8–7, Sat 9–5, and closed on
Sundays."* It was told. It quotes the price before the constraint.

**The 2 a.m. reply declines service, despite its failing rubric score.**

> Customer: *"do you do emergency calls at 2am"*
> Agent: *"We don’t have verified 2 AM or after-hours emergency coverage, so I
> can’t promise a technician then."*

The grader does not accept this wording. Both outside reviewers classify this
example as a grader miss, not an offer of overnight service. The recorded score
is retained; it must not be described as a verified agent failure.

Both are in `evals/results/MT-A5.json` under `MT-S02` and `MT-P02`.

---

## 2. One question I couldn't answer from outside

**Two builds using the same 3,107-character v1 brief answered membership-benefit
questions differently.** These are observations from different conversations,
not a controlled same-context experiment.

| build | answer to *"what's included in the savings club"* |
|---|---|
| `jojuduewx7ud` | "It includes a yearly HVAC cleaning and inspection, waived dispatch fees, priority scheduling, 15% off repairs, and 5% off new equipment." |
| `cgiefgaebmgh` | "I don't have the membership's included benefits or terms in the approved information, so I don't want to guess." |

The brief contains the membership price and **no benefits, in either case**. The
first build is stating facts it was not given — and they are accurate, they match
the business's own website.

Four explanations fit what I observed, and I can't distinguish them from outside:

1. the Builder reads the business's site during a build (its progress log does show
   it opening the site, so this is the one I'd guess at first),
2. a workspace-level knowledge store that survived one build and not the other,
3. a different effective brief reaching the model in one case,
4. the model's own knowledge of the business.

The observations do not establish a defect or the intended knowledge boundary.
The benefits given by the first build match the site, while the other build
declines without those benefits in its brief. Build-time retrieval and effective
inputs need to be checked before assigning a cause.

The full write-up, with the evidence and the four explanations, is
`docs/FINDING-club-knowledge.md`.

---

## 3. What I got wrong

Six failing conversations occur in two savings-club scripts whose expected
benefits were absent from the v1 brief. That is an authoring gap, but not a complete
explanation: some of those conversations also omit a required diagnostic price.
No hypothetical benefit correction is credited as a passing conversation.

Before attributing a failure to the agent, the expected fact needs to be checked
against the effective build input. Automating that check remains proposed; the
current harness does not enforce it for every scenario.

---

## 4. The check that did not confirm my own work

Everything above was measured on scenarios I wrote and then tuned against, which is
the weakness of the whole exercise. So the last test was built to remove it: 20
three-turn scenarios written by a different model against the same brief, with
graders written from the spec before any reply existed, frozen by hash on a public
commit, then run once on each arm.

**The two arms came out the same on the original 20-run total.** 17/20 each. On
the 13 scenarios I had not flagged as ambiguous, the baseline scored 12/13 and the
tuned arm 11/13 — the tie only appears when the seven ambiguous ones are folded in,
and the tuned arm gains a point there. One scored scenario is discordant, exact
McNemar p = 1.000. Deterministic cleaning then excluded one A5 record with a render
failure appended after a complete answer; the cleaned A5 count is 16/19 overall and
10/12 on the scored scenarios.

That does not mean the tuning failed. One conversation out of 13 moves the rate 7.7
points, and a set that size could not have detected even the single-turn effect. It
means the improvement **has not been confirmed out of sample**, and the explanation
I weigh most heavily is the least flattering one: the tuned arm was iterated on the
same scenarios it was measured against, so part of that gain may be fit to my own
test set. That is why the sealed set was worth running, and why running it was the
point rather than a formality.

## Method, in one paragraph

The v1 agent brief came from 24 sourced fields; the current ledger has 25 after
adding the omitted membership benefits. The evaluation retains the hand-written
and generated single-turn sets, 18 three-turn scripts and the sealed set.
There are 21 logged grader corrections: 20 from transcript inspection and one
from a positive control. A sealed validation set was authored by
a different model with graders written from the spec before any reply existed, and
frozen by hash on a public commit so the order is checkable. Repository:
`github.com/arjhinety/budget-front-desk`.

---

## Detailed evidence

`RESULTS.md` contains all arm comparisons, the full correction history and
cleaning exclusions. `platform/README.md` describes proposed structural fixes;
the tests establish their local behaviour, not their integration into Agentplace.
