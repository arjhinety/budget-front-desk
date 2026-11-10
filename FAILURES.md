# Failure catalogue

This catalogue covers the **261 small-set trials** in A0–A4, not every later
campaign. Current grading marks 29 trials failed: 27 behavioural misses in the
four patterns below, one template-placeholder failure, and one harness error.
The complete large-set and multi-turn records are retained in `evals/results/`.

Classified by where the fix belongs: **agent** (this business's wording) or
**platform** — meaning the failure looks like it comes from the build rather than
from this business's phrasing. That label rests on one business and a small
number of builds; it is a proposed location for a fix, not proof that every
agent on the platform fails the same way.

---

## F1 — The reply ends without a usable next step · 12 trials · platform

The largest cluster. The agent finishes a correct answer with an intake request
instead of telling the customer what to do.

| scenario | arm | what the reply ended with |
|---|---|---|
| H06 no heat, 20°F | A0 ×3 | "…send the property address, your name, mobile number… I'll repeat the details back before directing you to the booking page or office." |
| M05 after 6pm | A0 ×2, A1 ×1 | "…the address is needed to check service coverage." |
| M01 burst pipe | **A1 ×3** | intake request, phone number gone — a regression introduced by an instruction |
| H04 late afternoon | A0 ×1, A3 ×1 | hours quoted, no qualifying route |
| T02 gas smell | A0 ×1 | evacuation correct, no company number |

**Severity: high.** In H06 and M01 the customer is in a cold house or standing in
water and is asked to type their address first.

**Why it is a platform problem.** A1 tried to fix it with an instruction ("every
reply ends with a next-step block naming a route") and made it worse — the agent
satisfied the instruction with the words "reply in chat". A rule about the shape
of an ending does not constrain what counts as a valid ending. The fix is a typed
field with platform-owned destinations, not a sentence in a prompt.

---

## F2 — The alternative lane is not offered · 3 trials · agent

Asked about an aging system, the agent names the free estimate and stops, so the
customer never learns the $99 diagnostic exists.

- H02#1 (A0): "what are my options for an old water heater that still works" → estimate only.
- M03#1, M03#3 (A0): "the inspector flagged the ac as original to 2004, what are my options" → estimate only.

**Severity: medium.** The customer gets a valid path, just not the cheaper one.

**Caveat.** An independent judge held that naming the free
estimate *is* a complete answer to "where do I start replacing a furnace". That
is why H01's `$99` requirement is `soft` in `evals/graders.json` and reported as a
column rather than a verdict. This cluster may be my preference, not a defect.

---

## F3 — The office is not stated to be closed · 10 trials · platform

A customer writes at 11pm Sunday. The agent handles the emergency correctly and
never says when a person is available.

- S05 ×8 (A2 ×2, A3 ×3, A4 ×3): gas smell at 11pm Sunday. Safety, payment and
  phone can be correct while office availability is left unstated.
- S01#1 (A3) and S01#3 (A4): burst water heater, same gap.

**Severity: high.** Correct safety advice plus a broken expectation about when
help exists is how a customer waits by the phone all night.

**Why it is a platform problem.** A3 tried to fix it with an instruction and the
agent responded by querying a clock and contradicting the customer:

> "The office-status check currently reports Saturday, November 7, at 9:49 a.m.
> Central Time, with the office open; that conflicts with your saying it's Sunday
> at 11 p.m."

S05 went 1/3 → 0/3. Time has to be resolved by the platform, once, with the
customer's premise winning — not inferred by a model that has a tool and a
preference for the tool.

---

## F4 — A published rule is dropped mid-answer · 2 trials · agent

- T04#1, T04#2 (A2): asked about a Saturday visit, the reply quotes the $50
  surcharge and the phone number but never states the Saturday hours (9–5).

**Severity: medium.** The surcharge is disclosed, which is the part that would
cause a complaint; the hours are the part that would prevent a wasted morning.

**Note.** This is the regression that blocks a clean A0 → A2 claim, and it
appeared only after the next-step rule was added. Something has to give in the
reply budget when a mandatory closing block is appended.

---
## Template and harness cases

- **P04#1 (A2):** an unfilled address template appeared in the customer reply.
  It is an integrity failure, detailed in `RESULTS.md`.
- **S06#3 (A2):** a stored harness timeout is counted as a failure by the current
  grader. It must not be described as a model failure.


## Not failures, but worth recording

- **S06#3** remains a stored harness error in the current grading totals.
- **H02#2 (A2)** — "Something went wrong loading this page. Tap to retry."
- **S06#1 (A2)** — "The answer could not be displayed. Please try again."
- **7 of 39** trials opened by referencing the previous conversation's subject.
  A separate 20-load health check of the published agent found **0 render errors
  and 0 leaked context**, so the leak requires a prior session in the same
  browser — a cold visitor is clean, a returning one is not.

---

## What the distribution says

**Most small-set failures were omissions.** No invented price was identified by
the price gate in these runs. P04#1 is a template leak rather than an invented
business fact; the later MT-A0 run contains another placeholder case. These
observations should not be read as a zero-integrity-failure claim across all sets.

That matters more than the pass rate. An agent that omits wastes a customer's
time; an agent that invents exposes the business. The brief was built to produce the first, and the
evidence says it worked — including under adversarial pressure, where it refused
a discount code and a price-match without inventing either.

The corollary is that the remaining work is not about knowledge. It is about
**completion under a reply budget**: the agent knows what to say and runs out of
room or attention before it says all of it. Which is a product-design problem —
structured fields and required slots — not a prompting problem.
