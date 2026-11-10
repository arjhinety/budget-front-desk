---
title: "Budget Front Desk"
subtitle: "An agent built from a business's public pages, and the measurements of where it fails"
date: 2026-11-08
---

## 1. What was built

An AI agent for a real home-services company, built from a brief generated out of a
ledger of 25 facts, each carrying the page and line it came from. The agent triages a
complaint into emergency, diagnostic or free estimate, works the company's published
price catalogue, collects what a dispatcher collects, and routes to a booking, a phone
call or a payment.

The ledger bounds what goes into the brief: it fails the build if a price moves or if
the evidence turns out to be template placeholder text. It does not bound what the
model then says, which is why the output is checked separately against the same seven
prices.

## 2. How it was measured

33 hand-written scenarios and 55 generated from the business's decision branches
(service × county × timing × complication), three trials each. Every scenario carries
required behaviours and forbidden ones; a forbidden behaviour fails it even when every
required one is present. A deterministic grader checks the transcript, and a separate
check fails any dollar figure that is not one of the seven published prices.

Two tiers are reported rather than one score: an **integrity gate** (any invented price,
policy or placeholder fails the scenario outright) and **completeness** (how often the
required behaviour appears), with a Wilson interval because the counts are small.

## 3. What the measurements found

| | A0 as built | A2 two rules | A5 three rules |
|---|---|---|---|
| scenarios | 53 | 53 | 55 |
| trials | 159 | 159 | 165 |
| passed | 113 | 135 | 145 |
| strict pass³ | 26 | 40 | 45 |
| integrity gate failures | 0 | 0 | 0 |

Four instruction changes were tried. A1 regressed the emergency lane: told every reply
must name a route, the agent chose "reply in chat" and dropped the phone number. A2
fixed that. A3 tried to make the agent state when the office reopens and it started
querying a clock and contradicting a customer mid-gas-leak, so it was reverted. A5
reaches the same goal as A3 without a tool, and is the arm that ships.

By lane, on the scenarios both arms ran. The A2 column is included because it shows
what A5 fixed and what it did not:

| lane | A0 | A2 | A5 |
|---|---|---|---|
| coverage | 1/8 | 6/8 | 7/8 |
| diagnostic | 6/10 | 10/10 | 10/10 |
| free estimate | 6/8 | 8/8 | 8/8 |
| emergency | 4/8 | 6/8 | 6/8 |
| trust | 3/5 | 5/5 | 5/5 |
| scheduling | 3/9 | 2/9 | 4/9 |
| off-task | 2/3 | 1/3 | 2/3 |
| handoff | 1/2 | 2/2 | 1/2 |

## 4. What is wrong with it

- **One lane did not recover.** Handoff sits at 1/2: the multi-system and
  warranty-claim probes are where a person has to take over, and the agent handles
  one of the two.

- **Twenty grader corrections** were needed, all found by reading transcripts
  rather than by the suite. Every one was a pattern failing a correct answer.

- **The comparison is significant only after those corrections.** The 27-scenario
  version of it was p = 0.289; it reached p = 0.004 after twenty grader fixes, most
  of which were failing correct answers. That sequence is a reason to read the number
  with care rather than to celebrate it.

- **The held-out set was written after the first arm's failures were on screen.** It
  tests phrasing generalization, not failure modes nobody imagined.

- **One human calibration, 30 transcripts, and not double-blind.** Agreement was 70%
  with the requirement unstated and 97% with it stated; on the full 99-transcript set
  kappa fell to 0.314 because the sample is almost all passes. All three numbers say
  more about the rubric than about the agent.

## 5. What I would do next

1. Fix the handoff lane, then re-run the same set.
2. Move the three failure classes into the platform rather than the prompt: a typed
   next-step field, one clock resolved per turn with the customer's premise winning, and
   rule precedence as data. All three are implemented in `platform/` and replayed
   against the recorded conversations.
3. Get a second reader who never sees the first pass, on rows whose requirement is
   stated from the start.
