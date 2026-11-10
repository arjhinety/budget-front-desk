# Pre-run measurement audit

The historical scores reproduce, but they are not a clean causal estimate. This note records what must be repaired before collecting more replies. No old result, scenario, frozen input or grader rule is replaced by this audit.

## Two A5 capture blocks, identities unverified

`python evals/audit_history.py` reproduces the split in `evals/results/A5.json` at its largest inter-record gap:

| measured property | earlier block | later block |
|---|---:|---:|
| records | 94 | 71 |
| first timestamp, UTC | 2026-11-08 07:14:31 | 2026-11-08 14:16:11 |
| last timestamp, UTC | 2026-11-08 07:35:04 | 2026-11-08 15:24:46 |
| whole-line `Next step` heading | 91/94 | 0/71 |
| median captured thread characters | 1240 | 801 |

The heading measurement is explicitly `/^Next step\s*$/im`; substring counts give different numbers. Length includes captured UI text. The formatting discontinuity is observable. Different builds are one explanation, not an established identity assignment. All 165 records lack a per-record target, configuration hash and harness revision. The file-level project label cannot resolve that gap.

A read-only Builder inspection recovered the historical A5 request and its post-edit instruction/skill file read-backs. They are saved under `build/recovered/cgiefgaebmgh/` with capture limitations. They do not retrospectively identify the target of each old trial or verify the currently published effective configuration.

A separate read-only inspection of the configuration API found the currently
published prompt for `cgiefgaebmgh` (publication revision
`1794124548292-0123885d-...`). Its text equals the recovered instruction after
trailing-newline normalisation. The published prompt for the baseline
`guikfrraxzk5` was captured the same way. Both receipts are private.

The configuration API does **not** expose skill/knowledge file contents; the
public bundle contains none, and empty `roles`/`state.mounts` does not prove
absence. A verified effective-configuration snapshot therefore cannot be
produced, and the generated snapshot is deliberately recorded as invalid with
two blockers: current-effective-configuration verification missing, and the
knowledge artifact absent. No agent was messaged and nothing was published.

## Grader mistakes can go in both directions

- `G-X-SEWAGE-THISMO` requires water/contact/touch wording and fails keep-away wording about the sewage-affected area. The earlier report's assertion that the lost scenario necessarily lost safety advice was too strong. The recorded failure remains; human review judges the safety meaning.
- `G-D-ILLINOIS` accepts location/coverage vocabulary without necessarily requiring a correct boundary decision. A reply can therefore pass the pattern while leaving eligibility unresolved. A semantic audit must inspect passes as well as failures; no automatic new verdict is inferred here.
- The known overnight refusal miss is another example of wording failing a correct meaning.

The new review guide accepts meaning-preserving safety/refusal wording and distinguishes a clearly outside-area request from ambiguous water-heater diagnostic coverage. All original machine verdicts remain the comparison baseline. Any adjudication is a separate result.

## Human-review tooling repairs

The old sealed scorer invoked the single-turn grader on multi-turn captures and did not use its selected results file. The old blind sheet exposed agent-arm identities. The repaired tools choose the correct grader, verify the selected capture, use private identity keys and export neutral rows. They also validate both error directions, proper agreement denominators, and binary Gwet AC1. Legacy sheets remain retained and explicitly not arm-blind.

Human review is still pending. Prepared sheets do not constitute labels, and the author's previous exposure is recorded rather than called independent blinding. The old 30-row calibration is not upgraded by these repairs.

## Release boundary

The next-run protocol is `evals/next_run/PROTOCOL.md`. Current public configuration equivalence, human calibration, independently authored fresh cases and prospective grader controls are release dependencies. Recovered inputs, a candidate instruction diff and a dry schedule are not evidence that those dependencies are complete. No new conversations or published-agent edits were made for this preparation.
