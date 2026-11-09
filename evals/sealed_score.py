#!/usr/bin/env python3
"""
Score the sealed validation set, once.

Reads labelled conversations and the graders' verdicts, and reports the numbers
that decide whether the graders generalize. Written before the set exists, so the
statistics are fixed in advance rather than chosen after seeing them.

  python evals/sealed_score.py --labels datasets/sealed/labels.csv \
                               --results evals/results/SEALED-A5.json

Reports raw agreement, Cohen's kappa, Gwet's AC1, the false-fail rate and failure
recall. The false-fail rate is the one to lead with: every one of the nineteen
grader corrections in this repository was a false fail.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"


def cohen(a: list[str], b: list[str]) -> tuple[float, float]:
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(1 for x in a if x == "PASS") / n
    pb = sum(1 for x in b if x == "PASS") / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return po, (1.0 if pe == 1 else (po - pe) / (1 - pe))


def gwet_ac1(a: list[str], b: list[str]) -> float:
    """Agreement that survives a skewed pass rate, which kappa does not."""
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    p_pass = ((a.count("PASS") + b.count("PASS")) / (2 * n))
    pe = p_pass ** 2 + (1 - p_pass) ** 2
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="datasets/sealed/labels.csv")
    ap.add_argument("--results", default="evals/results/SEALED-A5.json")
    ap.add_argument("--set", default="scenarios-big")
    args = ap.parse_args()

    labels_path = ROOT / args.labels
    if not labels_path.exists():
        print(f"no labels at {labels_path} — nothing to score")
        return 2

    labels = {r["row"]: r["verdict"].strip().upper() for r in csv.DictReader(labels_path.open(encoding="utf-8"))}
    blank = [k for k, v in labels.items() if v not in ("PASS", "FAIL")]
    if blank:
        print(f"{len(blank)} unlabelled rows — a blank is not a no; fill every row first")
        return 2

    out = subprocess.run(["python", str(EVALS / "grade.py"), "--arm", "SEALED-A5",
                          "--json", "--set", args.set],
                         capture_output=True, text=True, cwd=str(ROOT)).stdout
    start = out.find("[")
    if start < 0:
        print("could not grade the sealed results"); return 1
    rows = json.JSONDecoder().raw_decode(out[start:])[0]

    human, machine = [], []
    for r in rows:
        key = f"{r['id']}#{r['trial']}"
        if key not in labels:
            continue
        human.append(labels[key])
        machine.append("PASS" if r["pass"] else "FAIL")

    if not human:
        print("no overlap between labels and graded rows"); return 1

    po, k = cohen(human, machine)
    ac1 = gwet_ac1(human, machine)

    human_pass = [m for h, m in zip(human, machine) if h == "PASS"]
    human_fail = [m for h, m in zip(human, machine) if h == "FAIL"]
    false_fail = sum(1 for m in human_pass if m == "FAIL") / len(human_pass) if human_pass else float("nan")
    recall = sum(1 for m in human_fail if m == "FAIL") / len(human_fail) if human_fail else float("nan")

    print(f"n = {len(human)}")
    print(f"  raw agreement      {po:.3f}")
    print(f"  Cohen's kappa      {k:.3f}")
    print(f"  Gwet's AC1         {ac1:.3f}")
    print(f"  false-fail rate    {false_fail:.3f}   ({len(human_pass)} human-PASS replies)")
    print(f"  failure recall     {recall:.3f}   ({len(human_fail)} human-FAIL replies)")

    dis = [(r["id"], r["trial"], h, m) for r, h, m in zip(rows, human, machine) if h != m]
    if dis:
        print(f"\ndisagreements ({len(dis)}) — for the independent evaluator to adjudicate:")
        for sid, trial, h, m in dis[:20]:
            print(f"  {sid}#{trial}  labeller={h} grader={m}")
        (ROOT / "datasets" / "sealed").mkdir(parents=True, exist_ok=True)
        (ROOT / "datasets" / "sealed" / "disagreements.json").write_text(
            json.dumps([{"id": a, "trial": b, "labeller": c, "grader": d} for a, b, c, d in dis],
                       indent=1) + "\n", encoding="utf-8")
        print("  -> datasets/sealed/disagreements.json")

    if human_fail and recall < 0.90:
        print("\n  recall below 0.90: the graders are letting failures through")
    if human_pass and false_fail > 0.10:
        print("\n  false-fail above 0.10: the graders are failing correct answers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
