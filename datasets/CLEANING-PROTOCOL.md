# Cleaning protocol for the sealed validation set

This protocol separates scenario authorship, deterministic cleaning and human
labelling. At collection time there were 19 logged corrections; the current
history has 21 (20 from transcripts and one positive control).

**Current state:** both arms have run, the deterministic exclusion pass has run,
and automated scores are reported. Human sealed-set labels and grader-agreement
statistics have not been collected. `labels.csv` below is a planned output,
not an existing result. The embedding contamination pass also remains separate
from the completed exclusion-only pass.

**Preparation update:** use `evals/human/GUIDE.md` and the repaired
`blind_export.py` / `blind_score.py` path for the pending retrospective audit.
The modern sheet uses opaque row IDs and PASS/FAIL/UNSURE; source identities
and machine verdicts remain in a separate private key. The old `evals/blind/`
sheet remains historical and is not arm-blind. No new collection is authorised.

**Do not read `evals/graders*.json`, `evals/grade.py` or `evals/grade_mt.py`
before finishing step 4.** If you do, the set is no longer sealed and the result
should be reported as unsealed.

## Every finding gets two outside reviews before it is written up

A rule this project arrived at the hard way. Each of the following was caught by an
outside model reading the work, not by the author:

- a grader that failed every correct reply because `ac` matches inside `HVAC`
- a rule that banned the word "Franklin" and so failed the correction that named it
- a protocol that still pointed at the old scenario set
- a claim that the agent under-claims, when the brief never contained the fact
- a request hash that did not match the file it claimed to hash

The procedure: state the finding, its evidence and what it does not establish; ask
two models from different families for an opinion; reconcile the two answers and
record where they disagreed. The reconciliation is the part that matters — the two
have never fully agreed, and the disagreement is usually where the framing was
wrong.

## Who does what, and why it is written down

| role | who | sees | does not see |
|---|---|---|---|
| A, grader author | the repository author | everything | — |
| B, cleaner | a model that did not write the graders | the transcripts, the business rules | the graders |
| C, independent evaluator | a third model, consulted in the open | the protocol, the statistics, the disagreements | nothing withheld |

The separation is only worth anything if it is stated in advance and the roles do
not slide. A wrote the instrument and cannot grade it. B removes artefacts and
measures contamination but does not decide pass or fail. C adjudicates and reports.

The weakness this does not fix: A also wrote the scenarios, so a sealed set of
*new replies on the same scenarios* tests wording generalization and not whether
the scenarios themselves are the right ones. That limitation is stated in
`RESULTS.md` and is not repaired by adding a role.

---

## What is being built, and a measurement that changed the plan

The original design was **new replies on the same 55 scenarios**. That design is
wrong, and the reason is measurable rather than theoretical.

Running the same scenario twice against the same agent gives replies with a
**median cosine similarity of 0.940**, and **23 of 55 pairs above 0.95** on
`BAAI/bge-small-en-v1.5`. The agent is templated: it says almost the same thing
every time. A sealed set built from fresh replies on the same scenarios would
therefore be about half near-duplicates of the corpus the graders were fitted to,
by construction, before a single label was collected.

So the sealed set must use **new customer messages**, not new replies to old ones.

### The design that survives, and its current state

1. **Someone other than the grader author writes 20 new scenarios.** Done:
   `mistral-large-4-0` via the Mistral API, 20 scenarios across the six families,
   request and response hashed in `datasets/sealed/scenarios-sealed.json`.
2. **The grader author writes graders for them from the spec alone**, before any
   reply exists. Done: `datasets/sealed/graders-sealed.json`, written from each scenario's stated
   `tests` line and the business rules, with no reply in existence yet.
3. **The artefacts are frozen.** `FROZEN.json` records the sha256 of the scenarios,
   the graders, the request and the raw response. If a grader changes after the
   first reply is recorded, the hash will not match and the set is burned.
4. Run, clean, label blind, score once. Not done.

**Seven scenarios are marked ambiguous** and are reported separately rather than
scored: SD-02, SD-06, SD-07, SD-10, SD-13, SD-14, SD-16. Each is a case where the
business publishes two rules that point different ways, or publishes nothing at
all. They are not defects in the scenarios; they are the places where the rule set
is genuinely underdetermined, and scoring them would manufacture a verdict.

The graders went through two revisions before any reply existed. Revision 1 was
reviewed by an outside model and had real defects — two graders contradicted
RULES.md, several banned a word rather than a claim, the arithmetic graders did
not require a total, and turn 1 was never graded. Revision 2 fixes them and is
what `FROZEN.json` records. **No reply to these scenarios existed at either
revision**, which is the property the freeze is protecting.

What this tests: whether a rule written from a specification, without sight of the
replies, agrees with a human reader on what those replies actually say. That is the
question the transcript-driven corrections left open.

What it does not test: whether the *existing* 55 scenarios' graders generalize.
They cannot be tested this way, because a per-scenario regex has nothing to attach
to in a scenario it was not written for. That limitation is stated rather than
worked around.

---

## Step 1 — collect

Run the **20 sealed scenarios** against the current agent, one trial each, on both
arms that exist:

| arm | project | trials | why |
|---|---|---|---|
| A0 | `guikfrraxzk5` | 1 | fails more, so it supplies the failures that matter |
| A5 | `cgiefgaebmgh` | 1 | the shipped arm |

That is **40 conversations**. One trial each: the point is whether a rule written
from a spec agrees with a reader, not run-to-run stability.

Write each arm to its own result file using the multi-turn runner:

```
bun evals/run_mt.mjs --arm SEALED-A5 --set datasets/sealed/scenarios-sealed.json --trials 1 --url <arm url>
```

The runner requires the injected `browser` session used for the recorded runs;
the command shows its arguments, not a standalone browser installation.

Run A0 and A5 into **separate files** (`SEALED-A0.json`, `SEALED-A5.json`) so the
arm is not visible in the record a labeller sees.

## Step 2 — clean before labelling

Exclude any record where:

- the transcript contains `cannot continue right now` (quota),
- the transcript contains `Something went wrong loading this page` or
  `The answer could not be displayed` (render failure),
- all captured replies are under 200 characters (the current script's short-reply
  rule; it does not discard a conversation solely because one valid reply is terse),
- `records` has an `error` key.

Record every exclusion with its reason in `datasets/sealed/exclusions.json`.
Excluded records are **not** agent failures and must not be scored as such.

## Step 3 — contamination check (this is the part that needs embeddings)

The question: is any sealed reply close enough to a reply the graders were tuned
on that it is effectively the same text?

1. Take the 165 A5 transcripts in `evals/results/A5.json` and the 159 in
   `evals/results/BIG-A2.json` as the **tuned-on** corpus. These are development
   replies used during instruction and grader iteration.
2. Embed every reply in both corpora with a sentence-embedding model. `BAAI/bge-m3`
   or `BAAI/bge-large-en-v1.5` are fine; use one model for both sides and record
   which.
3. For each sealed reply, compute cosine similarity to its nearest tuned-on
   neighbour. Report the distribution.
4. Flag pairs above **0.95** as near-duplicates. Do not delete them. Report:
   - how many sealed replies have a neighbour above 0.95,
   - which scenarios they belong to.
5. If more than **20%** of sealed replies have a neighbour above 0.95, the sealed
   set is not measuring generalization on new wording and that should be said
   before the labels are collected, not after.

Also check the reverse direction: for each tuning reply, is there a sealed reply
above 0.95 that was produced *before* the patch? Those are the cases the patch was
fitted to, and they should be reported by count.

## Step 4 — label

Label each conversation PASS, FAIL or UNSURE against the frozen
`evals/human/GUIDE.md`. It distinguishes missing knowledge and policy ambiguity
from an agent error. Do not silently substitute the older RULES.md.

- Shuffle the records. Do not show arm, trial, scenario id, or the grader's
  verdict.
- Two independent labellers if possible; one is acceptable if the second is a
  different model family from the first and is reported as a model, not a person.
- Where the two disagree, record the disagreement and do not resolve it by
  majority. A disagreement is a finding about the rubric.

Return the opaque `sheet.csv` generated in a fresh private batch. Its columns are
`row_id,conversation,your_verdict,recognized,notes`. Edit only the verdict,
recognition and notes; the private key/manifest must not be consulted during labelling.

## Step 5 — score, once

Only now read the graders.

Score the returned sheet against its verified private key and manifest:

```sh
python evals/blind_score.py --sheet <batch>/sheet.csv --key <batch>/private/key.json
```

Report, and report all of them:

| statistic | what it means | what would be bad |
|---|---|---|
| raw agreement | how often grader and labeller agree | below 0.80 |
| Cohen's κ | agreement corrected for chance | below 0.60 |
| **false-fail rate** | share of human-PASS replies the grader failed | above 10% — a recurring grader bug class |
| **failure recall** | share of human-FAIL replies the grader caught | below 0.90 — this is a grader letting a bad reply through |
| Gwet's AC1 | agreement that survives a skewed pass rate | report next to κ, never instead of it |

Report false-fail rate alongside failure recall so the audit covers both
over-strict grading and missed agent errors. The correction log alone does not
establish how often either occurs.

## Step 5b — the independent evaluator

C does not label and does not clean. C does three things, in this order, and each
one is recorded:

1. **Before the run:** read this protocol and say whether the separation is real.
   If C says it is not, the run does not start.
2. **After the cleaning, before the labels:** read B's exclusion list and
   contamination report and say whether the sealed set is still sealed. C sees the
   counts and the flagged pairs, not the labelled verdicts.
3. **After the scoring:** read the statistics and the disagreement list and write
   the adjudication — which disagreements are grader bugs, which are rubric
   ambiguity, and which are the labeller being wrong. C's adjudication goes in the
   report beside the numbers, not instead of them.

C's output is a short written adjudication with a verdict on each disagreement. It
is not a second opinion to average with the first; it is the record of who was
wrong and why.

## Step 6 — one shot

The sealed set is used once. Any change to `evals/graders*.json` after step 5
burns it, and the result must be reported as pre-change, with the change listed
after it.

---

## What this cannot show

- **It is not a human baseline.** If the labeller is a model, the result is
  "grader versus an independent model", not "grader accuracy".
- **110 conversations is small.** A false-fail rate of 0/30 has a 95% upper bound
  around 10%, which is not the same as "the graders never false-fail".
- **It tests wording, not coverage.** A grader can agree with a labeller on every
  reply in the set and still miss a failure mode neither of them thought of.
