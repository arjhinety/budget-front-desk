#!/usr/bin/env python3
"""Score the sealed (or multi-turn) conversation set against human labels.

This is the one-shot measurement, so the labels are validated before any
statistic is printed. A label for a record that is not in the selected results,
a label for a record the cleaning protocol excluded, a duplicate label, a blank
verdict or an unknown verdict stops the run. Nothing here rewrites the historical
result files, the frozen sealed inputs or ``datasets/sealed/exclusions.json``.

  python evals/sealed_score.py --labels datasets/sealed/labels.csv \
                              --results evals/results/SEALED-A5.json

The selected ``--results`` file must be the capture the grader actually reads;
another copy is accepted only when its bytes are identical. The proper grader is
chosen from the file's schema (``datasets/grade_sealed.py`` for sealed,
``evals/grade_mt.py`` for multi-turn), never hardcoded to SEALED-A5.

A returned sheet from ``evals/blind_export.py`` is scored with ``--sheet`` and
``--key`` instead, and the identity stays in the private key.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_common as rc  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Compare human labels with grader verdicts on a conversation set.")
    ap.add_argument("--labels", default="datasets/sealed/labels.csv",
                    help="label CSV with columns row,verdict[,notes]; row is '<id>#<trial>'")
    ap.add_argument("--results", default="evals/results/SEALED-A5.json",
                    help="results file to grade (arm taken from the file stem)")
    ap.add_argument("--sheet", help="returned sheet from blind_export.py (instead of --labels)")
    ap.add_argument("--key", help="private key for --sheet")
    ap.add_argument("--guide", help="guide hash to verify with --sheet")
    ap.add_argument("--out", metavar="PATH", help="write the score JSON here")
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out")
    ap.add_argument("--allow-partial", action="store_true",
                    help="score the labelled subset instead of refusing incomplete labels")
    ap.add_argument("--json", action="store_true", help="print the score object")
    return ap


def _parse_row_key(raw: str, known: dict[str, set[int]]) -> tuple[str, int] | None:
    text = (raw or "").strip()
    if not text:
        return None
    if "#" in text:
        sid, _, trial = text.rpartition("#")
        sid = sid.strip()
        try:
            return sid, int(trial.strip())
        except ValueError:
            return None
    trials = known.get(text)
    if trials and len(trials) == 1:
        return text, next(iter(trials))
    return None


def _read_labels(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip() for h in (reader.fieldnames or [])]
        if "row" not in header or "verdict" not in header:
            raise rc.LabelSheetError(
                f"{path} needs columns 'row' and 'verdict' (header was {header!r})")
        rows = []
        for row in reader:
            rows.append({k.strip(): (v or "") for k, v in row.items() if k is not None})
        return rows


def _score_labels(labels_path: Path, results_path: Path, *,
                  allow_partial: bool,
                  grader_read_dir: Path | None = None,
                  grader=None) -> dict:
    real_graders = grader is None
    if grader_read_dir is not None and real_graders:
        raise rc.InputError(
            "grade_sealed.py and grade_mt.py read evals/results/<arm>.json; an "
            "alternate grader_read_dir is only valid with an injected grader")
    runner = grader or rc.run_grader
    if not labels_path.exists():
        raise rc.InputError(f"no labels at {labels_path} — the set has not been labelled yet")
    arm = rc.arm_from_path(results_path)
    data = rc._load_results(results_path)
    records = data["records"]
    kind = rc.infer_kind(arm, records)
    if kind == "single":
        raise rc.InputError(
            f"{results_path} is a single-turn capture; score it with blind_export.py "
            "and blind_score.py instead")
    verified = rc.verify_results_input(results_path, arm, grader_read_dir)
    graded = runner(kind, arm)
    bound = rc.bind_graded(records, graded)

    known: dict[str, set[int]] = {}
    for rec in records:
        known.setdefault(str(rec.get("id")), set()).add(int(rec.get("trial", 1)))

    excluded: dict[tuple[str, int], str] = {}
    for rec in records:
        reason = rc.classify_record(rec)
        if reason:
            excluded[(str(rec.get("id")), int(rec.get("trial", 1)))] = reason[0]

    seen: dict[tuple[str, int], str] = {}
    pairs: list[tuple[str, str, dict]] = []
    unsure = 0
    unsure_detail: list[dict] = []
    errors: list[str] = []
    for row in _read_labels(labels_path):
        raw_key = row.get("row", "")
        key = _parse_row_key(raw_key, known)
        if key is None:
            errors.append(f"{raw_key!r}: row is not '<id>#<trial>' and does not name a "
                          "unique record in the selected results")
            continue
        if key[0] not in known:
            errors.append(f"{raw_key!r}: id is not in {results_path}")
            continue
        if key not in bound:
            errors.append(f"{raw_key!r}: no such scenario/trial in {results_path}")
            continue
        if key in seen:
            errors.append(f"{raw_key!r}: labelled twice")
            continue
        if key in excluded:
            errors.append(f"{raw_key!r}: record was excluded by the cleaning protocol "
                          f"({excluded[key]}); excluding it from scoring is required")
            continue
        verdict = (row.get("verdict") or "").strip().upper()
        if verdict == "":
            errors.append(f"{raw_key!r}: blank verdict")
            continue
        if verdict not in rc.VERDICTS:
            errors.append(f"{raw_key!r}: verdict {row.get('verdict')!r} is not PASS, FAIL or UNSURE")
            continue
        seen[key] = verdict
        detail = {"row": raw_key, "arm": arm, "id": key[0], "trial": key[1],
                  "grader_verdict": "PASS" if bound[key]["pass"] else "FAIL",
                  "human_verdict": verdict, "notes": row.get("notes", "")}
        if verdict == "UNSURE":
            unsure += 1
            unsure_detail.append(detail)
            continue
        pairs.append((verdict, detail["grader_verdict"], detail))

    eligible = {k for k in bound if k not in excluded}
    missing = sorted(eligible - set(seen))
    if missing and not allow_partial:
        shown = ", ".join(f"{a}#{b}" for a, b in missing[:8])
        errors.append(f"{len(missing)} eligible record(s) unlabelled ({shown}); "
                      "fill every row or pass --allow-partial")
    if errors:
        raise rc.LabelSheetError("labels rejected:\n  " + "\n  ".join(errors[:20]))

    return rc.summarize(
        pairs=pairs, unsure=unsure, unsure_detail=unsure_detail,
        recognized={"labelled": len(seen), "eligible": len(eligible)},
        exclusions=[{"identity": {"id": k[0], "trial": k[1]}, "reason": v, "detail": ""}
                    for k, v in sorted(excluded.items())],
        unresolved=[],
        selection={"mode": "all-eligible", "selection_bias": None},
        extra={
            "arm": arm,
            "labels_complete": not missing,
            "grader_kind": kind,
            "results_file": str(verified),
            "results_sha256": rc.sha256_file(verified),
            "labels_file": str(labels_path),
            "partial_labels": bool(missing),
            "coverage": (len(seen) / len(eligible)) if eligible else None,
        })


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.sheet:
            if not args.key:
                raise rc.ReviewError("--sheet needs --key")
            result = rc.score_sheet(Path(args.sheet), Path(args.key),
                                    guide=Path(args.guide) if args.guide else None)
        else:
            result = _score_labels(
                Path(args.labels), Path(args.results), allow_partial=args.allow_partial)
    except rc.ReviewError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False))
    else:
        print(rc.format_report(result))
        if result.get("arm"):
            print(f"  arm {result['arm']}  ({result['grader_kind']} grader, "
                  f"{result['results_file']})")

    if args.out:
        dest = Path(args.out)
        if dest.exists() and not args.force:
            print(f"not written: {dest} exists; pass --force to replace it", file=sys.stderr)
            return 2
        rc.write_json_atomic(dest, result)
        if not args.json:
            print(f"\n-> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
