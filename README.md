# Budget Front Desk — an agent, its ledger, and what it gets wrong

An agent built for a real business, and the measurements of where it fails. The
published link is shared separately; what is here is the method and the evidence.

1. **The agent** — project `cgiefgaebmgh` on Agentplace, GPT-6 Luna. The published link is
   shared separately, not in this repository.
2. **The evidence** — all 33 hand-written and 55 generated single-turn scenarios,
   their instruction-arm runs, 108 multi-turn conversations across both arms,
   and 40 sealed-set conversations. The 20-scenario sealed set supplements,
   rather than replaces, the larger development sets.

The published v1 brief used 24 sourced fields; the current ledger has 25 after
adding omitted membership benefits. Single-turn A5 metadata names the original
project; the linked A5 rebuild has its own multi-turn and sealed measurements.
This provenance difference is disclosed in `RESULTS.md`.

Business: **Budget Heating, Cooling & Plumbing** — justcallbudget.com, St. Peters,
Missouri. Heating, cooling and plumbing; family-owned since 2009; five named
counties; a booking page selling a twelve-row catalogue at published prices.

The company did not commission this and does not endorse it. It is a
demonstration built from their public pages, and a takedown request would be
honoured immediately. See `NOTICE.md`.

---

## Open work

Preparation is offline; no new collection is authorised. See
`docs/PRE-RUN-AUDIT.md` and `evals/next_run/PROTOCOL.md`.

1. **Measurement:** historical scores remain unchanged. Arm-blind human review
   must check false passes as well as false failures.
2. **Provenance:** recovered A5 input files are historical read-backs, not proof
   of the current effective publication. New captures need bound configurations.
3. **Agent behaviour:** scheduling and handoff still need review; their machine
   scores are 4/9 and 1/2 all-three passes, not a complete adjudicated defect count.
4. **Fresh evaluation:** case authoring, prospective graders/control receipts and
   explicit collection approval follow calibration. The used sealed set is not
   reused for tuning.

## Read these first

| file | what it is |
|---|---|
| `RIGOR.md` | how the agent was built and what it does **not** claim |
| `qa/test-plan.md` | scope, evidence standard, hypotheses, exit criteria |
| `build/brief.txt` | the brief that produced the agent, rendered from the ledger |
| `facts/sources.csv` | 25 current ledger fields, each with its source page and line number; the published v1 brief used 24 |
| `facts/parameters.csv` | every judgement call, with a written reason |
| `RESULTS.md` | the six arms, the McNemar test, the grader bugs, the platform findings |
| `FAILURES.md` | small-set failure patterns; later runs remain in `evals/results/` |
| `docs/MODEL-COMPARISON.md` | Luna vs Terra on the same 39 conversations, and the decision |
| `platform/` | the three platform defaults, implemented and tested |
| `evals/blind/sheet.csv` | historical 30-row calibration; arm identity was visible |
| `NOTICE.md` | the business relationship, the scripted conversations, and takedown |
| `docs/REFERENCES.md` | every paper cited, with what was taken from it |
| `FINDINGS-FOR-AGENTPLACE.md` | the findings worth sending, and the one thing I got wrong |
| `docs/FINDING-club-knowledge.md` | two builds from one brief know different amounts, with the evidence |
| `datasets/manifest.json` | every set, its hash, its generator, and the contamination policy |
| `datasets/CLEANING-PROTOCOL.md` | how the sealed validation set is built and scored, once |
| `evals/human/GUIDE.md` | frozen meaning-based guide for the new retrospective human audit |
| `build/pdf/report.pdf` | two-page summary, regenerated from the results by `build/make_report.py` |
| `platform/README.md` | the three failures that should be fixed once, not per agent |
| `evals/METHOD.md` | the original preregistration and forward-recorded amendments |
| `docs/PRE-RUN-AUDIT.md` | provenance discontinuity and grader flags, without replacing old scores |
| `evals/next_run/PROTOCOL.md` | offline preparation, release blockers and prospective analysis |
| `build/recovered/cgiefgaebmgh/` | historical A5 request and file read-backs, with limitations |

## The pipeline

```
scrape.py          11 pages -> raw/*.html + raw/*.txt + facts/provenance.json
build_facts.py     the text -> facts/business.json + sources.csv + parameters.csv
generate_brief.py  current ledger -> build/brief-v2.txt -> build/builder_url.txt
drive.mjs          the brief -> the Agentplace Builder (persistent signed-in profile)
evals/             scenarios.json (33 hand-written), scenarios-big.json (55 generated),
                   graders.json, gen_scenarios.py, run.mjs, grade.py,
                   stats.py (McNemar + paired bootstrap), kappa.py, health.mjs
platform/          nextstep.py, clock.py, precedence.py, replay.py, tests
```

`build/brief.txt` and `build/builder_url-v1.txt` preserve the evaluated v1 input.
The v2 brief includes the omitted benefits and is not the published/evaluated arm.

Rebuild from the source pages:

```
python scrape.py --root https://justcallbudget.com
python build_facts.py
python generate_brief.py
python evals/check_numbers.py build/brief-v2.txt
python evals/stats.py --a A0 --b A2      # 2x2 discordance + exact McNemar
python evals/kappa.py --all --arm A2     # grader vs an independent judge
python evals/gen_scenarios.py            # regenerate the 55-scenario branch set
python evals/stats.py --a BIG-A0 --b BIG-A2 --set scenarios-big --bootstrap 10000
python evals/twotier.py --a BIG-A0 --b BIG-A2 --set scenarios-big
python evals/blind_export.py --input evals/results/BIG-A0.json \
  --input evals/results/A5.json --n 60 --guide evals/human/GUIDE.md \
  --out ../agentplace-private/labelling/new-batch
```

Human exports are local processing of existing captures, not new agent runs.
Do not regenerate historical scenarios or start capture during this preparation.
Future capture uses a separate manifest and fails closed when required evidence
or explicit collection approval is missing.

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
