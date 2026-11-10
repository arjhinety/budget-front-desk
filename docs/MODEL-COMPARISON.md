# Model comparison — quality, latency, cost

Everything before this page ran on one model. Two agents, **the same brief, the
same 13 scenarios, three trials each** — 39 conversations per model, 78 total.
Same graders, same price check.

| | **GPT-6 Luna** (free) | **GPT-6.1 Terra** (paid) |
|---|---|---|
| strict pass³ | **12/13** | **12/13** |
| pass@1 | 37/39 (95%) | 37/39 (95%) |
| main split | 18/18 | 17/18 |
| held-out split | 19/21 | 20/21 |
| latency p50 | 9.3 s | **8.7 s** |
| latency p95 | 13.3 s | **11.0 s** |
| mean reply | 1061 chars | 959 chars |
| integrity failures | 0 | 0 |

Published agents: Luna project `jojuduewx7ud` · Terra project `6rbktdzfgtmj`

## The decision: keep Luna for the front desk

Quality is a tie at the top line, so the decision turns on **which failure each
model produces**, not on the count.

- **Luna's miss** — H03#3, "how does scheduling work": the reply never states the
  weekday hours. The customer still gets a route; they just do not know the
  office closes at 7.
- **Terra's miss** — M03#3, an aging AC and "what are my options": the reply names
  **neither** the free estimate nor the $99 diagnostic. The customer gets no path
  at all.

The aggregate is 37/39 for each model, so each has two failing trials.
**Terra's displayed median is roughly 6.5% faster (8.7 s versus 9.3 s) and its
mean reply is about 10% shorter. A causal connection is untested.**
Paying more for a model that is quicker at omitting the answer is a bad trade for
a front desk whose whole job is routing.

**Recommendation:** Luna as the default for triage-and-route agents. Revisit if
p95 latency becomes a product constraint — at 13.3 s the p95 tail is the number a
customer actually feels, and Terra's 11.0 s is a real improvement. The right test
for that is not this one; it is a latency SLO against real traffic.

## Cost: measured where it exists, and labelled where it does not

Per-conversation usage is **not exposed in the workspace UI**, so I am not going
to publish a cost-per-conversation figure I cannot read. What is observable:

- The builder shows a credit balance that moves during a build. The Terra build
  moved it by roughly **86 credits** while the badge was visible.
- The model picker labels Luna **Free**, and says it uses a free allowance first.
- The earlier Luna work consumed enough of that allowance that the badge had
  already fallen from 1,647 to 1,380 before the Terra build started, so the two
  are **not cleanly separable** from what I can see.

The cost column is: **Luna free within allowance, Terra paid, per-turn
usage unmeasured.** A proper version of this experiment instruments the API and
records tokens per conversation; that is a half-day of work against the platform,
not against this test set.

## What would change the decision

1. **Terra's terseness is the hypothesis, not the finding.** If a prompt change
   made Terra produce Luna-length replies, would it keep the latency advantage
   and recover M03#3? That is a two-arm experiment and it is the one I would run
   next.
2. **p95 is the number that matters at scale.** 11.0 s vs 13.3 s on 39 samples is
   a hint, not a distribution. A latency SLO needs hundreds.
3. **The failure modes are not equally likely in production.** M03-type questions
   ("what are my options for an old system") are common sales traffic; H03-type
   scheduling questions are common too. Weighting by real traffic could flip the
   recommendation, and I do not have real traffic.
