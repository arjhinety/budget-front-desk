# How this was built, and what it does not claim

One business, one agent, built from that business's own public pages. The 24
fields the brief was rendered from each carry a page and a line, and every gap
the site leaves is written down instead of filled by a confident sentence. The
agent itself read more pages than the ledger covers, so the ledger bounds what
was checked, not what the agent knows.

Target: **Budget Heating, Cooling & Plumbing** — justcallbudget.com, St. Peters,
Missouri. A real service-area business with a real booking page, a real price
menu, and enough inconsistency between its own pages to be worth checking.

---

## The chain

```
scrape.py          fetch 11 pages  ->  raw/*.html + raw/*.txt + facts/provenance.json
build_facts.py     parse the text  ->  facts/business.json + facts/sources.csv + facts/parameters.csv
generate_brief.py  render the ledger -> build/brief.txt + build/builder_url.txt
evals/*            test the agent   ->  evals/scenarios.json + evals/check_numbers.py
```

Each step reads only what the step before it wrote. Nothing is typed into the
brief that is not first in the ledger, and the ledger cannot hold a field that
the build script did not find a literal string for.

Rebuild from nothing:

```
python scrape.py --root https://justcallbudget.com
python build_facts.py
python generate_brief.py
python evals/check_numbers.py build/brief.txt
```

---

## Four rules the build applies

The first two stop the build. The last two are recorded in the ledger and are
not enforced by code, which is a difference worth keeping straight.

**1. No number without a receipt.** `build_facts.py` will only write a field if
its evidence string is present in a captured page. If the price of the one-time
HVAC cleaning changes, or the row is renamed, the build *stops* and names the
field. It does not quietly ship the old number. A stale price on a booking agent
is a complaint with the customer's name on it.

**2. Placeholders are rejected, not ignored.** The build refuses evidence that
matches a template-site pattern: `mysite.com`, `123-456-7890`, `500 Terry
Francine Street`, `Location 1`, `lorem ipsum`. The first business considered for
this build had three bookable services with prices, and a contact block on every
service page reading `500 Terry Francine Street, 6th Floor, San Francisco, CA
94158 / 123-456-7890 / info@mysite.com`. That is unedited site-template content,
still published. An agent built from it would have given that address to
homeowners whose business is not in California. The guard exists because it was
one field away from happening.

**3. Contradictions are resolved in writing, not silently picked.** Two are
recorded in `facts/business.json`:

- The $99 appears twice under different names — "HVAC Diagnostic Service Call"
  in the catalogue, "dispatch fee" in the FAQ. Both describe one charge for the
  visit that includes travel and diagnosis. Resolution: quote $99 once per
  visit; never stack a second dispatch charge on top.
- **Coverage is not uniform.** Water-heater estimates are offered "anywhere in
  Missouri" and tankless flushing "statewide", while other plumbing-equipment
  estimates stop at the St. Charles County line, and diagnostic visits are sold
  inside the five named counties. A single blanket service-area test would be
  wrong for two of the twelve catalogue rows. Resolution: test the address
  against the *job type*, not against one map.

**4. Gaps stay gaps.** Six things the agent must not invent, carried
explicitly in the ledger: no street address for walk-ins, no per-repair prices,
no licence number, no cancellation policy, no after-hours or 24/7 claim, no
separate travel charge. The brief instructs the agent to say it doesn't know and
route to (636) 887-2800. The failure mode being defended against is the plausible
sentence, not the missing one.

---

## The test set

`evals/scenarios.json` holds 33 scenarios in five splits, deliberately shaped
like a tuning/pilot/main-sample split rather than one list:

| split | what it is | what a failure means |
|---|---|---|
| tuning (8) | written from the same reading of the site that produced the brief | the brief is wrong — fix the agent |
| pilot (6) | same business, different wording | the agent memorised the brief's phrasing |
| main (7) | requests a St. Charles dispatcher actually takes | this is the verdict |

Every scenario carries two lists: `must`, all of which have to appear, and
`must_not`, any one of which fails the scenario even when the `must` items are
all present. "Correctly quoted the $99 and then invented a furnace price" is a
failure, not a partial pass.

The scenarios are not random. Six of the twenty-one target the places where this
specific site is thin: uniform coverage, walk-in address, 24/7, warranty scope,
licence number, and warranty-company dispatch. Those are the questions the site
cannot answer, so they are the questions an agent will be tempted to answer
anyway.

`evals/check_numbers.py` is the mechanical half of the scoring: it reads a
transcript and fails any `$N` that is not one of the seven published figures
($99, $50, $150, $250, $375, $475, $489).

---

## What this does not claim

- **The site changed on some other day.** Every ledger fact is stamped with
  `captured_at` and a sha256 of the response body. The ledger is valid for the
  window it was captured, and `facts/parameters.csv` sets a 30-day freshness rule.
  This is a dated snapshot, not a sync.
- **The agent is not connected to the real booking system.** It drives the
  customer to the published booking page, the phone, or the diagnostic fee. No
  calendar, no payments, no CRM. Wiring those up is the next step, not a claim
  made here.
- **Twenty-one scenarios are not a benchmark.** They are the questions this
  reviewer thought of after reading eleven pages. They will overstate accuracy
  on wording that resembles the brief, which is why the phrasing of
  the pilot and main splits was written *after* the brief, and why the
  `must_not` lists carry more weight than the `must` lists.
- **Nothing here is a statement about the business.** Every number belongs to
  Budget Heating, Cooling & Plumbing as published on its own pages on the
  capture date. The customer examples are invented.

---

## Why it looks like this

The shape of this build is borrowed from a dataset I compiled for a course in
intelligent agents: a food-rescue simulation with thirty fictional pantries on
real Cubao streets, built by a single seeded script, with a provenance file
carrying a sha256 and a licence for every source, a field-level table saying
which source supplies which column, and a parameter table where every assumed
number is labelled `assumption` with a written reason — including the one that
had to be corrected mid-project because multiplying a food-insecurity share into
demand double-counted households that were already food-insecure.

Two habits came out of that work and into this one.

The first is that a number without a status is a liability. In the dataset, no
parameter existed without a status column. Here, no fact exists without a source
page and a line number.

The second is that a result which survives a hostile read is worth more than a
flattering one. That project's README ends by proving, from its own template
overlap counts, that its parser accuracy cannot be generalized to unseen
phrasings — 96% of its test messages reuse a phrasing seen during tuning. The
same discipline applies here: this agent is measured against questions written
by the person who wrote its brief, so the accuracy figure is bounded by the
phrasing of the test set.
