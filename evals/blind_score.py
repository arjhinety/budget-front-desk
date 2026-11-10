#!/usr/bin/env python3
"""Score a returned blind sheet against the graders, joined through the private key.

The sheet is validated before anything is scored. A blank verdict, an unknown or
duplicated row id, a missing row, an altered conversation cell, a renamed column
or an edited guide is a refusal, not a default. Rows may be returned in any
order: the join is by ``row_id``, so a shuffled sheet cannot mispair a verdict,
and a sheet that has lost its ids is rejected rather than aligned by position.

  python evals/blind_score.py --sheet <out>/sheet.csv --key <out>/private/key.json \
                             --guide <out>/GUIDE.md

The historical ``evals/blind`` sheet can still be scored, but only explicitly and
only as a NON-arm-blind reproduction:

  python evals/blind_score.py --legacy-dir evals/blind
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
        description="Score human PASS/FAIL/UNSURE labels against the grader verdicts "
                    "held in the private key.")
    ap.add_argument("--sheet", metavar="CSV", help="returned sheet")
    ap.add_argument("--key", metavar="JSON", help="private key written at export")
    ap.add_argument("--guide", metavar="PATH",
                    help="guide the labeller used; its hash must match the key")
    ap.add_argument("--out", metavar="PATH", help="score JSON destination")
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out")
    ap.add_argument("--json", action="store_true", help="print the score object")
    ap.add_argument("--legacy-dir", metavar="DIR",
                    help="score the historical evals/blind sheet (NOT arm-blind; "
                         "that sheet exposes scenario and arm)")
    return ap


def _write(path: Path, obj: dict, force: bool) -> None:
    if path.exists() and not force:
        raise rc.ReviewError(f"{path} exists; pass --force to replace it")
    rc.write_json_atomic(path, obj)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.legacy_dir:
            if args.sheet or args.key:
                raise rc.ReviewError("--legacy-dir cannot be combined with --sheet/--key")
            result = rc.score_legacy_blind(Path(args.legacy_dir))
            default_out = None
        else:
            if not args.sheet or not args.key:
                raise rc.ReviewError("--sheet and --key are both required "
                                     "(or use --legacy-dir)")
            result = rc.score_sheet(Path(args.sheet), Path(args.key),
                                    guide=Path(args.guide) if args.guide else None)
            default_out = Path(args.key).parent / "score.json"
    except rc.ReviewError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False))
    else:
        print(rc.format_report(result))
        if result.get("returned_out_of_order"):
            print("  note: rows came back out of export order; joined by row_id")

    dest = Path(args.out) if args.out else default_out
    if dest is not None:
        try:
            _write(dest, result, args.force)
        except rc.ReviewError as exc:
            print(f"not written: {exc}", file=sys.stderr)
            return 2
        if not args.json:
            print(f"\n-> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
