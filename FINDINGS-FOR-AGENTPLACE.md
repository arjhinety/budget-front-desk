# Findings, for the Agentplace team

Written to be read by the people who build the platform. Everything here is
reproducible from the repository; the transcripts are in `evals/results/`.

Two things I'd want to know if I were on your side of the table, and one thing I
got wrong.

---

## 1. Two multi-turn failures that are the agent's, not mine

18 three-turn scripts, 54 conversations, 41 pass. The failures split cleanly:
**6 come from my brief** (below), and **7 are the agent's**. Two of those seven are
worth your attention because they're the same shape.

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
`FINDING-club-knowledge.md`.

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

## Method, in one paragraph

Every fact the agent was built from is in a 24-field ledger, each field carrying
the page and line it came from, and the build fails if a price moves or the
evidence turns out to be template placeholder text. The evaluation is 55
single-turn scenarios and 18 three-turn scripts, graded by rules that were
themselves audited — nineteen of them were wrong and were corrected, every one a
case where a rule failed a correct answer. A sealed validation set was authored by
a different model with graders written from the spec before any reply existed, and
frozen by hash on a public commit so the order is checkable. Repository:
`github.com/arjhinety/budget-front-desk`.

---

## What is not in here

The instruction-arm comparison (A0 at 71.1% of trials, A5 at 87.9%, two arms
reverted), the nineteen grader corrections, and the sealed-set results are in the
repository and not in this note. They measure my work rather than your platform,
and this note is about your platform.
