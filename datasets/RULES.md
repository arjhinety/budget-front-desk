# The business rules, in plain English

**Historical reference.** This was the rule prose used for the original audits.
It contains the v1 water-heater/diagnostic coverage ambiguity and later membership
facts. New human-review batches use `evals/human/GUIDE.md`, whose version/hash is
frozen with each batch. Do not silently apply this older file instead.

A labeller should not have to read a regex to know what a correct answer looks
like. This is the same rule set the graders encode, written for a person.

Source: the business's own public pages, captured 2026-11-07. The machine-readable
version is `facts/business.json`, and every fact in it carries the page and line
it came from in `facts/sources.csv`.

## Hours

- Monday to Friday, 8:00 a.m. to 7:00 p.m.
- Saturday, 9:00 a.m. to 5:00 p.m.
- Closed Sunday.
- No after-hours, overnight, or 24/7 service is published anywhere.

## Prices

| service | price |
|---|---|
| HVAC diagnostic service call | $99 per visit |
| water-heater diagnostic service call | $99 per visit |
| one-time HVAC cleaning and maintenance | $150 per system |
| complete HVAC refresh and performance report | $489 per system |
| water-heater maintenance and flush | $375 |
| tankless water-heater flush | $475 |
| savings club membership | $250 per year |
| free HVAC / water-heater / indoor-air replacement estimates | free |

- The $99 covers the trip and the diagnosis. Repairs, parts and refrigerant are
  quoted separately and approved before work starts.
- **Saturday appointments add $50.** A total built from two published prices —
  $150 + $50 = $200, or $99 + $50 = $149 — is correct arithmetic, not an invented
  price.
- Members have the dispatch fee waived, and get 15% off repairs and 5% off new
  equipment.

## Coverage

- **Water-heater work is offered anywhere in Missouri.** This is the one that
  surprises people: an address outside the five counties is **not** a refusal for a
  water-heater job.
- **Diagnostic visits are sold in five counties only:** St. Charles, St. Louis,
  Lincoln, Warren, Jefferson.
- **Other plumbing-equipment estimates stop at the St. Charles County line.**
- HVAC replacement estimates carry no published area limit.

## What the business does not publish

An agent that states any of these as fact is wrong:

- a street address for walk-in visits,
- a licence number,
- a per-repair price,
- a cancellation or late-arrival policy,
- any after-hours or 24/7 service,
- any discount, promo code or price match.

## What a correct reply looks like

1. **Right lane.** Emergency, diagnostic, or free estimate — and the lane matches
   what the customer described.
2. **Right price**, if a price is given at all.
3. **Right coverage answer**, which depends on the job type, not just the county.
4. **A next step the customer can act on**: call or text (636) 887-2800, open the
   booking page, or pay the diagnostic fee. "Reply in chat" is not a next step.
5. **No invented fact.** If the site does not answer it, say so and route to the
   phone number.

## How to judge a conversation

A conversation passes only if **every** reply in it is correct. A wrong price at
turn 3 fails the conversation even if turns 1 and 2 were perfect, because the
customer lived through the whole thing.

Judge the reply, not the rubric. If a reply is correct but the rules above do not
obviously cover it, mark it PASS and say why in the notes — that disagreement is
more useful than a forced verdict.
