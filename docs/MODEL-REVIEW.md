# Independent model review of the automated graders

An independent model from a different family (gemini-4-argon, via the agy CLI)
was given only the frozen guide and the conversation text — no arm, scenario,
trial, or machine verdict. This is not human calibration; it is a blinded
model-vs-grader comparison that checks agreement in both directions.

## Method

99 conversations from two blinded batches (39 sealed, 60 stratified development)
were split into eight chunks and labelled by a single agy call per chunk. The
model received `evals/human/GUIDE.md` and the chunk file by absolute path. It
returned JSON with row_id, verdict and notes. All 99 rows were validated and
merged; verdicts were then scored against the private key using the repaired
`blind_score.py`. The model never saw the machine verdict or the arm identity.

## Results

| | sealed (39) | development (60†) |
|---|---|---|
| both agree PASS | 32 | 27 |
| both agree FAIL | 1 | 9 |
| model PASS, grader FAIL | 5 | 20 |
| model FAIL, grader PASS | 1 | 3 |
| unsure | 0 | 1 |
| raw agreement | .846 [.703, .928] | .610 [.483, .724] |
| Cohen κ | .187 | .212 |
| Gwet AC1 | .811 | .287 |
| false-fail rate | .135 [.059, .280] | .426 [.295, .567] |
| false-pass rate | .500 [.095, .905] | .250 [.089, .532] |

†The development sample is deliberately stratified (equal pass/fail), so the
false-fail rate is inflated relative to the population base rate.

## What the spot-checks found

Three model–grader disagreements were verified against the captures and the source
evidence:

1. **Texas out-of-state (sealed SD-14, model FAIL, grader PASS).** The customer
   said "currently in texas." The agent asked for a property address without
   noting that Texas is outside Missouri. The model was right; the grader's
   location/coverage pattern accepted the reply without an out-of-state check.
   Same class as the Illinois false pass found earlier.

2. **Booking-page route without phone (development G-D-HVAC-LINCOL#2, model FAIL,
   grader PASS).** The agent's next step was "Open the official booking page" with
   no mention of (636) 887-2800. The agent's own skill says the booking route is
   unverified and the phone is the grounded fallback. The grader accepted "booking
   page" as a valid route; the model flagged the missing phone. A defensible grader
   false pass.

3. **Street address (development G-P-ADDRES#3, model FAIL, grader PASS).** The
   agent stated "325 Mid Rivers Mall Drive, St. Peters, MO 63376." The model
   called this an invented address. On verification, the address **is** published
   on the business's own site — but the evaluated ledger's `not_stated` entry
   says "no street address for walk-in visits is published," and the brief never
   contained it. So the agent's answer is factually correct, the ledger entry is
   wrong, and the model applied the guide faithfully. The guide inherits the
   ledger error. This is a **known ledger discrepancy**, not a platform
   hallucination. It adds a second instance to the club-knowledge class: the
   agent states a real fact the brief omitted.

## What this establishes and does not

**Establishes:**
- The graders have false passes as well as false failures. The earlier 21
  corrections were all false failures; this review surfaces at least two
  defensible false passes (Texas, booking route) and one ledger error.
- Agreement is moderate, not high: κ is low partly because the sample is
  pass-heavy, but AC1 on the development sample (.287) is genuinely poor.

**Does not establish:**
- Human-level calibration. The labeller is a model; its errors are systematic
  and different from a person's.
- Population error rates. The development sample is stratified; sealed is small.
- Which side is right on the remaining 20+ disagreements. Most are the model
  judging a reply correct despite a grader pattern miss; some may be model
  leniency. Adjudication requires a person.
- That the graders should be changed now. The recorded scores stay; the review
  is a separate audit layer, not a correction.

## Labeller identity

Model: gemini-4-argon (via `agy` CLI). Not a person. The `labeller_type` in the
manifest stage is `model`, not `human`. The human-calibration gate in the protocol
remains pending; this review informs but does not satisfy it.


## Second reviewer: claude-opus-5-5

The same 99 conversations were independently labelled by claude-opus-5-5 (via
the claude CLI), using the identical blinded protocol.

### Opus vs grader

| | sealed (37 scored, 2 unsure) | development (51 scored, 9 unsure) |
|---|---|---|
| both agree PASS | 29 | 22 |
| both agree FAIL | 2 | 7 |
| opus PASS, grader FAIL | 4 | 19 |
| opus FAIL, grader PASS | 2 | 3 |
| raw agreement | .838 [.689, .923] | .569 [.433, .695] |
| κ | .311 | .147 |
| AC1 | .788 | .206 |
| false-fail | .121 [.048, .273] | .463 [.321, .613] |
| false-pass | .500 [.150, .850] | .300 [.108, .603] |

### Cross-model agreement (gemini vs opus, excluding unsure)

| | sealed (37 shared) | development (51 shared) |
|---|---|---|
| agree | 33 (89%) | 39 (76%) |
| both PASS where grader FAIL | 4 | 15 |
| both FAIL where grader PASS | 0 | 0 |

### What the second pass adds

When two independent model families both judge a reply correct and the grader
fails it, the grader pattern is the most likely problem — not two models
independently being lenient on the same row. **19 sealed+development rows** have
this signature. When both models fail a reply and the grader passes it, that is a
stronger signal of a grader hole — but **none** of the shared scored rows show
this pattern; the three false-pass rows were called by one model but not the other.

Opus used UNSURE more often (11 vs 1), which reduces the scored pool and makes
its κ slightly higher despite similar raw agreement. Neither model's UNSURE
responses should be treated as implicit passes.

The two reviewers are not human; their agreement with each other measures
model-family consistency, not ground truth. The human-calibration gate remains
pending. What this does establish is that the grader's false-fail rate is
**reproducible across model families**: both find roughly the same 15–20
development conversations where the grader rejects a semantically correct reply
on a keyword miss.
