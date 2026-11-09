# Test plan — Agentplace builder and a published agent

**Subject under test**
1. The Agentplace Builder, as a product: sign-in, the create flow from a prefilled business brief, website ingestion, conversation with the builder, preview, publish, access settings, workspace navigation.
2. The published agent built from it: Budget Heating, Cooling & Plumbing front desk (justcallbudget.com), Luna model, public access.

**Why these two.** They fail differently. The builder fails as software — state, navigation, validation, permissions. The agent fails as a system that talks to people — wrong facts, confident guesses, dead ends, incoherent recovery. A single pass that only loads pages misses everything in the second group.

**Out of scope, stated so it is not assumed**
- Payment capture and billing (no live card, and I will not put one in).
- Phone and messaging channels (separate setup, not reachable from the free plan).
- Integrations that require a third-party account I do not own.
- Load, soak and penetration testing. A test pass over a live tenant is the wrong place to start probing either.
- Anything on a customer's real data. All customer scenarios in the agent tests are invented personas.

---

## Evidence standard

Every report carries: environment, preconditions, numbered steps, expected, actual, severity, and a screenshot or recording. A report without a reproducible step sequence is a note, not a bug — notes go in an appendix, they don't get numbered.

Two rules borrowed from how I build datasets: **state the version you tested**, and **never round a "sometimes" into an "always."** If a defect appeared in 2 of 6 attempts, the report says 2 of 6 and includes the attempt that worked.

---

## Severity and priority are separate

| | meaning |
|---|---|
| **S1** | data loss, wrong money, a public agent saying something harmful or false about a real business, or the workspace becoming unusable |
| **S2** | a core flow is blocked or silently wrong, with a workaround that is not obvious |
| **S3** | the flow completes but misleads, or a control behaves differently from its label |
| **S4** | cosmetic, copy, consistency, or an accessibility issue that does not block |

Priority is not severity. An S4 in the sign-up copy that every new user reads outranks an S2 in a settings page nobody opens. The three marked "fix first" are chosen on that basis, with the reasoning written next to each.

---

## Areas and the specific hypotheses worth testing

Written before testing, so a finding either confirms or kills a hypothesis instead of being noticed in hindsight.

### A. Sign-in and session
- Whether the Google path and the email/password path land in the same place, including `redirectTo` being honoured.
- Whether a deep link into the builder (`?create_new=true&instruction=…`) survives an auth round-trip, or whether the brief is dropped by the redirect.
- Session expiry mid-build: what happens to an unsaved brief.

### B. Builder link and brief ingestion
- Whether a 3,100-character URL-encoded brief arrives intact — no truncation, no double-encoding, no silent character substitution on em dashes and curly quotes, which is where encoding usually breaks first.
- Whether `autosend=false` genuinely pre-fills without creating anything. A phantom project created by merely opening a link is an S2.
- Behaviour when the brief contains a URL: does the builder treat it as a business site, a source, or text?

### C. Website ingestion
- What the builder does with a site whose pages contradict each other — my test business publishes coverage that differs by job type, and three free estimates alongside a paid diagnostic.
- What it does with placeholder or template text on a client site. It should not ingest `info@mysite.com` as a business fact.
- What it does with a site it cannot read: silence, a guess, or an explicit statement.

### D. Conversation and preview
- Whether the builder asks before inventing. The prompt to test: give it a bare brief and see whether it invents a price or asks.
- Whether a correction in turn 5 persists, or whether turn 6 reverts it.
- Long-session behaviour: does the interface stay coherent after 20+ exchanges, and does an interrupted generation leave a half-applied state.

### E. Publish and access
- Whether Public / Restricted / Private are enforced server-side, not just hidden in the UI. Test: publish Public, then flip to Private, then request the URL while signed out.
- Whether "Require sign-in" and "Allow duplication" both take effect on the published URL, and whether the Remix URL respects duplication being off.
- Whether publishing again after an edit updates the same URL or forks a second one.
- Unpublish: whether the URL actually stops serving, and whether the draft survives.

### F. The published agent, as a customer
33 scripted conversations in `evals/scenarios.json`, split tuning / pilot / main / held-out / adversarial, plus 55 generated from the decision branches in `evals/scenarios-big.json`. Each carries required behaviours and forbidden ones; any forbidden behaviour fails the conversation even when every required one appears. Automated half: `evals/check_numbers.py` fails any dollar figure not traceable to the ledger.

### G. Cross-cutting
- Browser matrix: Chromium and one other engine, desktop and a narrow viewport.
- Console and network on every flow: errors, failed requests, requests that fire repeatedly.
- Accessibility basics on the builder: focus order, labels, keyboard-only creation path.

---

## Exit criteria

Not "no bugs found." Exit is: every area above exercised at least once, every S1/S2 with a reproduction, the three fix-first items named with a reason, and a written list of what was **not** covered — because full coverage of a product this size is not what this pass can claim.

## Artifacts

- `qa/bug-reports/` — numbered reports, one per defect, evidence attached
- `qa/notes.md` — observations that did not meet the bar for a report, kept rather than deleted
- `evals/scenarios.json` — the agent conversation set
- `evals/check_numbers.py` — the automated fact check
- `facts/sources.csv` — the ledger every agent answer is measured against
