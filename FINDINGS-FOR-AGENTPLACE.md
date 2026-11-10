# Findings, for the Agentplace team

Written to be read by the people who build the platform. Everything here is
reproducible from the repository; the transcripts are in `evals/results/`.

Two things I'd want to know if I were on your side of the table, and one thing I
got wrong.

---

## 1. Two multi-turn failures that are the agent's, not mine

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

The failures split cleanly: **6 come from my brief** (below), and **7 are the tuned
agent's**. Two of those seven are worth your attention because they're the same shape.

**It does not state opening hours when asked about a specific slot.**

> Customer: *"i need a saturday tune up"*
> Agent: *"A Saturday tune-up fits One-Time HVAC Cleaning and Maintenance — $150 per
> system..."* — the price and the surcharge, never the hours.

The brief says, in as many words: *"Open Mon–Fri 8–7, Sat 9–5, and closed on
Sundays."* It was told. It quotes the price before the constraint.

**It does not say there is no 24/7 service when asked about a 2am emergency.**

> Customer: *"do you do emergency calls at 2am"*
> Agent: answers about emergency service without stating that none exists overnight.

The brief says *"Never promise 24/7 or same-night service."* Same pattern: the
prohibition is in the brief, and the reply doesn't carry it.

Both are in `evals/results/MT-A5.json` under `MT-S02` and `MT-P02`.

---

## 2. One question I couldn't answer from outside

**Two builds from the same 3,107-character brief, asked the same question, behaved
differently.**

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

I'm not reporting this as a defect, because I don't know that it is one. If the
Builder is meant to ingest the site, then the first build is working as designed
and the second is not — and if it isn't meant to, the first build is answering from
somewhere the owner never supplied. **Either way it's a question worth an answer
from inside, and I'd rather ask it than assert it.**

The full write-up, with the evidence and the four explanations, is
`docs/FINDING-club-knowledge.md`.

---

## 3. What I got wrong

The six failures I'm not blaming on the agent: two scripts ask what the savings
club includes, and **my brief never contained the benefits**. The agent declined to
answer, correctly, and my test marked it down for not knowing something it was
never told.

I found that by reading the reply rather than trusting the score. The rule it
produced is now in the harness: before any failure is blamed on the model, each
expected fact has to be checked against the ledger to confirm the agent was
actually given it. A scenario that asserts a fact the brief does not contain is a
broken test, not a hard one.

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

Every fact the agent was built from is in a 25-field ledger, each field carrying
the page and line it came from, and the build fails if a price moves or the
evidence turns out to be template placeholder text. The evaluation is 55
single-turn scenarios and 18 three-turn scripts, graded by rules that were
themselves audited — twenty of them were wrong and were corrected, every one a
case where a rule failed a correct answer. A sealed validation set was authored by
a different model with graders written from the spec before any reply existed, and
frozen by hash on a public commit so the order is checkable. Repository:
`github.com/arjhinety/budget-front-desk`.

---

## What is not in here

The instruction-arm comparison (A0 at 71.1% of trials, A5 at 87.9%, two arms
reverted), the twenty grader corrections, and the sealed-set results are in the
repository and not in this note. They measure my work rather than your platform,
and this note is about your platform.
