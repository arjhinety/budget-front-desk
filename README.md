# Budget Front Desk — an agent, its ledger, and what it gets wrong

An agent built for a real business, and the measurements of where it fails. The
published link is shared separately; what is here is the method and the evidence.

1. **The agent** — project `jojuduewx7ud` on Agentplace, GPT-6 Luna. The published link is
   shared separately, not in this repository.
2. **The evidence** — 822 recorded conversations, the graders, and the failures they found.

The facts it was built from are in a ledger of 24 fields, each carrying the page
and line it came from. The agent also read pages beyond that ledger, so the
ledger is a floor on what it knows, not a complete inventory. Every question the
site cannot answer is recorded as a gap rather than filled with a guess.

Business: **Budget Heating, Cooling & Plumbing** — justcallbudget.com, St. Peters,
Missouri. Heating, cooling and plumbing; family-owned since 2009; five named
counties; a booking page selling a twelve-row catalogue at published prices.

The company did not commission this and does not endorse it. It is a
demonstration built from their public pages, and a takedown request would be
honoured immediately. See `NOTICE.md`.

---

## Read these first

| file | what it is |
|---|---|
| `RIGOR.md` | how the agent was built and what it does **not** claim |
| `qa/test-plan.md` | scope, evidence standard, hypotheses, exit criteria |
| `build/brief.txt` | the brief that produced the agent, rendered from the ledger |
| `facts/sources.csv` | 24 facts, each with its source page and line number |
| `facts/parameters.csv` | every judgement call, with a written reason |
| `RESULTS.md` | the five arms, the McNemar test, the grader bugs, the platform findings |
| `FAILURES.md` | every failure observed, with the reply that caused it |
| `MODEL-COMPARISON.md` | Luna vs Terra on the same 39 conversations, and the decision |
| `platform/` | the three platform defaults, implemented and tested |
| `evals/blind/sheet.csv` | 30 transcripts to grade blind — fill one column, then score it |
| `STATUS.md` | open work and the commands to finish it |
| `NOTICE.md` | the business relationship, the scripted conversations, and takedown |
| `REFERENCES.md` | every paper cited, with what was taken from it |
| `datasets/manifest.json` | every set, its hash, its generator, and the contamination policy |
| `datasets/CLEANING-PROTOCOL.md` | how the sealed validation set is built and scored, once |
| `datasets/RULES.md` | the business rules in plain English, for a labeller |
| `build/pdf/report.pdf` | two-page summary, regenerated from the results by `build/make_report.py` |
| `PLATFORM-NOTE.md` | the three failures that should be fixed once, not per agent |
| `evals/METHOD.md` | the preregistration and the eight amendments made after the first run |

## The pipeline

```
scrape.py          11 pages -> raw/*.html + raw/*.txt + facts/provenance.json
build_facts.py     the text -> facts/business.json + sources.csv + parameters.csv
generate_brief.py  the ledger -> build/brief.txt -> build/builder_url.txt
drive.mjs          the brief -> the Agentplace Builder (persistent signed-in profile)
evals/             scenarios.json (33 hand-written), scenarios-big.json (55 generated),
                   graders.json, gen_scenarios.py, run.mjs, grade.py,
                   stats.py (McNemar + paired bootstrap), kappa.py, health.mjs
platform/          nextstep.py, clock.py, precedence.py, replay.py, tests
```

Rebuild from the source pages:

```
python scrape.py --root https://justcallbudget.com
python build_facts.py
python generate_brief.py
python evals/check_numbers.py build/brief.txt
python evals/stats.py --a A0 --b A2      # 2x2 discordance + exact McNemar
python evals/kappa.py --all --arm A2     # grader vs an independent judge
python evals/gen_scenarios.py            # regenerate the 55-scenario branch set
python evals/stats.py --a BIG-A0 --b BIG-A2 --set scenarios-big --bootstrap 10000
python evals/twotier.py --a BIG-A0 --b BIG-A2 --set scenarios-big
python evals/blind_export.py --n 30   # then fill the sheet and run blind_score.py
```

`build_facts.py` fails rather than warns. If a price changes on the site, or a
catalogue row is renamed, or the evidence turns out to be template placeholder
text, the build stops and names the field. A stale price on a booking agent is a
complaint with the customer's name on it.

## What is deliberately not here

`.profile/` and `raw/` are gitignored. The first holds a live signed-in browser
session and the second holds third-party page copies; neither belongs in a zip
that leaves this machine.

## Known limits

The agent is not connected to the business's calendar, payments or CRM — it routes
to their booking page, their phone number, or their $99 diagnostic. The facts are
a dated snapshot with a 30-day freshness rule, not a sync. The 33 hand-written
scenarios were written by the person who wrote the brief, which flatters the
agent; the 55-scenario set was generated from the business's decision branches
instead. `RIGOR.md` says which part of this is preregistered and which is not.
