# Finding: the agent knows more than its brief, and two builds know different amounts

**Status: observed, cause unknown.** Reported as an observation with its evidence,
not as a diagnosis.

## The observation

Two agents were built on Agentplace from **the same v1 brief** — the same 3,107
characters, generated from the 24-field ledger snapshot used for that build. The
current ledger has since gained a benefits field; it was absent from the published
v1 brief. The brief lists the savings
club as a price line and nothing else:

> `Budget Savings Club Membership $250 per year`

It contains no description of what the membership includes. The v1 ledger used for
these builds likewise had no benefits field. The current `facts/business.json` now
contains that field as a documented post-run correction.

The business's website does publish the benefits:

> "Annual membership includes a yearly cleaning and inspection, waived dispatch
> fees, priority scheduling, 15% off repairs, and 5% off new equipment."
> — justcallbudget.com/book-online/, captured in `raw/book-online.txt:212`

Asked the same question — *"what's included in the savings club"* — the two builds
answer differently.

**Project `jojuduewx7ud`** (the first build, and the arms A0/A2/A3):

> "The Budget Savings Club Membership is $250 per year. It includes a yearly HVAC
> cleaning and inspection, waived dispatch fees, priority scheduling, 15% off
> repairs, and 5% off new equipment."

That is the website's wording, close to verbatim. It is **not in the brief**.
(`evals/results/A0.json`, scenario P02, three trials; also `A2.json`, `A3.json`.)

**Project `cgiefgaebmgh`** (a later rebuild from the same brief, and the arm A5):

> "Budget Savings Club Membership is $250 per year. I don't have the membership's
> included benefits or terms in the approved information, so I don't want to
> guess."

(`evals/results/MT-A5.json`, script MT-S03, three trials.)

## What this establishes

1. **The agent's knowledge is not bounded by the brief.** One build states facts
   that appear nowhere in the 3,107 characters it was given. The Builder reads the
   business's website during a build — its own progress log says "Opening browser"
   — so the most likely source is that crawl. That is a hypothesis, not a finding.
2. **Two builds from the same brief do not hold the same knowledge.** One answers
   the membership question from the site; the other declines. Whatever the source,
   it did not survive the rebuild identically.

## What this does not establish

- **Not a cause.** Whether the difference comes from the crawl, from a knowledge
  store the workspace keeps, from a different effective brief, or from the model's
  own priors is unknown. Nothing here distinguishes those.
- **Not a defect in either direction.** The build that answered is not obviously
  wrong — the facts are the business's own. The build that declined is not wrong
  either, given what it was told. The finding is the *inconsistency*, not a
  verdict on either answer.
- **Not an under-claiming problem.** An earlier draft of this note called the
  refusal a model failure. That was wrong: the brief never contained the benefits,
  so declining was correct. The correction is recorded in `RESULTS.md`.

## Why it matters for evaluation

The evaluation's reference answers were written from the business's website, but
the agent was briefed from a ledger that left some of it out. Before any failure
is blamed on the model, each expected fact should be checked against the ledger to
confirm the agent was actually given it. Otherwise the suite measures the brief
and calls the result model behaviour.

That is a rule the harness did not have, and it produced a wrong finding here
before it was caught by reading the reply.

## The fix, in order

1. **Done:** add `savings_club_benefits` to the current ledger with source
   `raw/book-online.txt:212`.
2. **Generated, not evaluated:** `build/brief-v2.txt` contains the benefits.
   No v2 outcome is substituted for the retained v1 runs.
3. **Still proposed:** check that every expected evaluation fact is present in
   the effective build input before attributing its absence to the agent.
