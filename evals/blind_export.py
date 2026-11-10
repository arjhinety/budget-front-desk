#!/usr/bin/env python3
"""Export a blind human-labelling batch.

Every verdict in this repository was produced by graders the author wrote, so a
reviewer needs a sheet that carries the conversation and nothing else: no arm,
no scenario id, no trial, no source file, no grader verdict. Those live in
``private/key.json`` beside the sheet and are joined back only at scoring time.

  python evals/blind_export.py \
      --input sealed@evals/results/SEALED-A0.json \
      --input sealed@evals/results/SEALED-A5.json --all \
      --out ../agentplace-private/labelling/2026-11-11-sealed \
      --guide evals/human/GUIDE.md

  python evals/blind_export.py --input evals/results/BIG-A0.json \
      --input evals/results/BIG-A2.json --n 30

A guide is required: it is copied into the batch and its hash frozen in the
private key, so labels cannot be collected without the rules they were given.
Output defaults to ``../agentplace-private/labelling/<date>-<arms>`` outside the
repository. An existing non-empty ``--out`` is refused; the historical
``evals/blind`` directory is refused always. Run with ``--help`` writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_common as rc  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Export neutral, shuffled, opaque rows for human labelling.",
        epilog="Identity, arm, scenario, trial and the grader verdict are written "
               "only to <out>/private/key.json.")
    ap.add_argument("--input", action="append", required=True, metavar="[KIND@]RESULTS.json",
                    help="results file; KIND is single, mt or sealed and may be omitted "
                         "when it can be inferred. Repeat for multiple files/arms.")
    ap.add_argument("--out", metavar="DIR",
                    help="output directory (default: private directory outside the repo)")
    ap.add_argument("--all", action="store_true", help="export every eligible row")
    ap.add_argument("--n", type=int, default=30, help="rows to sample when --all is absent")
    ap.add_argument("--seed", type=int, default=20261111, help="shuffle/sampling seed")
    ap.add_argument("--strata", default="pass,fail,edge",
                    help="strata for a development sample, in allocation order")
    ap.add_argument("--guide", metavar="PATH", required=True,
                    help="labelling guide; copied into the batch and its hash frozen in the key")
    ap.add_argument("--set", default=None,
                    help="scenario set for single-turn grading (default: inferred from the "
                         "records' split and id prefix; an override must cover every record)")
    ap.add_argument("--fresh", action="store_true",
                    help="acknowledge that --out must be a fresh path; a non-empty "
                         "directory is still refused")
    ap.add_argument("--json", action="store_true", help="print the run summary as JSON")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    specs = [rc.InputSpec.parse(v) for v in args.input]
    out = Path(args.out) if args.out else rc.private_default_out(
        [rc.arm_from_path(s.path) for s in specs], [])
    try:
        result = rc.export_batch(
            specs, out,
            n=args.n, take_all=args.all, seed=args.seed,
            guide=Path(args.guide),
            set_name=args.set,
            strata=[s.strip() for s in args.strata.split(",") if s.strip()],
        )
    except rc.ReviewError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False))
        return 0
    sel = result["selection"]
    print(f"{result['selected']} conversations -> {result['sheet']}")
    if sel.get("selection_bias"):
        print("  sample: stratified, not a population sample (details in the private manifest)")
    reasons: dict[str, int] = {}
    for item in result["exclusions"]:
        reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    if reasons:
        print("  excluded: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items())))
    if result["unresolved"]:
        print(f"  unresolved: {len(result['unresolved'])} (listed privately, not exported)")
    print(f"  guide: {result['guide']['sha256'][:12]}… {result['out']}/GUIDE.md")
    print(f"  private identity: {result['key']}")
    print(f"  manifest: {result['manifest']}")
    print("\nFill your_verdict with PASS, FAIL or UNSURE for every row; the optional")
    print("recognized column takes yes/no. Add reasons in notes; leave conversation and row_id unchanged.")
    print("\nThen score the returned sheet with:")
    print(f"  python evals/blind_score.py --sheet {result['sheet']} --key {result['key']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
