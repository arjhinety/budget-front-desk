# Finding: the agent knows more than its brief, and two builds know different amounts

**Status: observed, cause unknown.** Reported as an observation with its evidence,
not as a diagnosis.

## The observation

Two agents were built on Agentplace from **the same brief** — the same 3,107
characters, generated from the same 25-field ledger. The brief lists the savings
club as a price line and nothing else:

> `Budget Savings Club Membership $250 per year`

It contains no description of what the membership includes. Neither does the
ledger: `facts/business.json` has a `savings_club` service with a price and no
benefits field.

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

1. Add a `benefits` field to the savings club in the ledger, sourced from
   `raw/book-online.txt:212`.
2. Regenerate the brief and re-run the scripts that ask about membership.
3. Add a check to `build_facts.py`: every fact an evaluation expects must exist in
   the ledger, or the build fails. A scenario that asserts a fact the brief does
   not contain is a broken test, not a hard one.
