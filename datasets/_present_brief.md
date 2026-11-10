# What should I do now to present this properly?

## The package as it stands

A job application to Agentplace for an AI Engineer role (contract, remote, from $5,500/mo). The task given was:
build an agent for a real home-services business, test it with at least 20 realistic conversations including
adversarial ones, show a before/after improvement with attributable deltas, and write it up.

**Published:** a live agent on Agentplace's own platform, built from a 3,107-character brief. Five instruction
arms. The best arm is the one still published.

**Repository:** `github.com/arjhinety/budget-front-desk`, branch master, 8 commits, public. Contains:
- `README.md`, `RESULTS.md` (the full evaluation), `RIGOR.md` (method), `FAILURES.md` (what broke),
  `MODEL-COMPARISON.md`, `PLATFORM-NOTE.md`, `REFERENCES.md`, `NOTICE.md`, `LICENSE`, `STATUS.md`
- `FINDINGS-FOR-AGENTPLACE.md` — 4 sections, the sendable note
- `FINDING-club-knowledge.md` — the build-inconsistency write-up
- `facts/sources.csv` — a 25-field ledger, every field with page and line provenance
- `evals/` — 55 single-turn scenarios, 18 three-turn scripts, 20 sealed scenarios, graders, results
- `build/pdf/report.pdf` — 2 pages

**Numbers:**
- Single-turn: A0 71.1% of trials, A5 87.9%; strict pass-cubed 26/53 to 43/53; McNemar p < 0.001 on the
  pass-cubed metric; A0 vs A5 is 324 conversations. In-sample: A5 was tuned on these scenarios.
- Multi-turn: 54 conversations, 41 pass (76%), 12 of 18 scripts clean on every trial. 6 of the 13 failures
  are my brief's fault, not the agent's.
- Sealed, out-of-sample: 20 scenarios by a different model, graders frozen before replies existed. A0 17/20,
  A5 17/20, agree on 18 of 20, one discordant scored scenario, McNemar p = 1.000. On the 13 unflagged
  scenarios A0 is 12/13 and A5 11/13. Not confirmed out of sample.
- 20 grader corrections, every one found by reading transcripts. Two arms were tried and reverted.
- A person graded 30 transcripts blind: 21/30 agreement (kappa 0.328) before a rule was stated, 29/30
  (kappa 0.911) after.

**Email:** 150 words to nikita@agentplace.io, in a private folder, not in the repo. The agent link goes in
the email, not the repository.

## What is already decided

- The agent link stays out of the repo.
- The real business name stays; `NOTICE.md` covers unaffiliated and takedown.
- Reports state findings, never "the listing asks for X".
- Every finding gets two outside opinions before it is written up.

## What I want from you

Answer exactly these, numbered, terse, no preamble. Be concrete — name files and actions, not principles.

1. What is the single weakest thing in this package right now, and what specifically fixes it?
2. The repository has eleven top-level markdown files. Is that too many, and if so which merge or go?
3. What should the PDF be, given the repo already contains everything? Two pages of what?
4. The email is 150 words. What must it contain, and what must it not?
5. Is there anything in the package that a careful reader would conclude is dishonest or padded, even though
   every individual number is true?
6. What is the one thing I should do in the next hour, and what should I deliberately not do?
