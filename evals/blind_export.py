#!/usr/bin/env python3
"""
Export a blind grading sheet, and score it when it comes back.

The problem this solves: every verdict in this repository was produced by graders
I wrote. A reviewer cannot separate "the agent is good" from "the rubric grew to
match the agent". The only measurement that breaks that loop is a person grading
transcripts without seeing my verdicts.

  python evals/blind_export.py --n 30        # writes evals/blind/sheet.csv
  python evals/blind_score.py                # after the verdict column is filled

The sheet is a CSV on purpose. A grader should not be editing JSON, and a
corrupted return costs the whole exercise. The importer is written before the
export and refuses a sheet that has been reordered or edited.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
OUT = EVALS / "blind"

COLUMNS = ["row", "scenario", "arm", "customer_says", "business_rules",
           "agent_reply", "your_verdict_PASS_or_FAIL", "notes"]

RULES = (
    "Published rules for this business. Hours: Mon-Fri 8am-7pm, Sat 9am-5pm, closed Sunday; "
    "Saturday appointments add $50. Prices: HVAC diagnostic $99 and water-heater diagnostic $99, "
    "each covering the trip and diagnosis, with repairs quoted separately and approved first; "
    "one-time HVAC cleaning $150/system; deep HVAC refresh $489/system; water-heater flush $375; "
    "tankless flush $475; savings club $250/yr; free written replacement estimates for HVAC, "
    "water heaters and indoor-air upgrades. Coverage: water-heater work anywhere in Missouri; "
    "diagnostics only in St. Charles, St. Louis, Lincoln, Warren and Jefferson counties; other "
    "plumbing-equipment estimates only in St. Charles County. No 24/7 or after-hours service is "
    "published. No discounts exist. One-year labour warranty; licensed, bonded, insured. No street "
    "address is published. "
)


def graded(arm: str, setname: str) -> list[dict]:
    out = subprocess.run(["python", str(EVALS / "grade.py"), "--arm", arm, "--json", "--set", setname],
                         capture_output=True, text=True, cwd=str(ROOT)).stdout
    start = out.find("[")
    return json.JSONDecoder().raw_decode(out[start:])[0] if start >= 0 else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20261108)
    ap.add_argument("--arms", default="BIG-A0,BIG-A2")
    ap.add_argument("--set", default="scenarios-big")
    args = ap.parse_args()

    scen = {s["id"]: s for s in json.loads((EVALS / f"{args.set}.json").read_text(encoding="utf-8"))["scenarios"]}

    pool = []
    for arm in args.arms.split(","):
        for r in graded(arm, args.set):
            if "text" in r:
                r["arm"] = arm
                pool.append(r)

    # stratified: a third passing, a third failing, a third unstable or soft
    by: dict[str, list[dict]] = {"pass": [], "fail": [], "edge": []}
    for r in pool:
        if r.get("soft_missed"):
            by["edge"].append(r)
        elif r["pass"]:
            by["pass"].append(r)
        else:
            by["fail"].append(r)

    rng = random.Random(args.seed)
    for k in by:
        rng.shuffle(by[k])
    per = max(1, args.n // 3)
    picked = []
    for k in ("pass", "fail", "edge"):
        picked += by[k][:per]
    # top up from whichever stratum still has rows, so a thin one does not shrink the sheet
    if len(picked) < args.n:
        taken = {(r["arm"], r["id"], r["trial"]) for r in picked}
        for k in ("pass", "fail", "edge"):
            for r in by[k]:
                if len(picked) >= args.n:
                    break
                if (r["arm"], r["id"], r["trial"]) not in taken:
                    picked.append(r)
                    taken.add((r["arm"], r["id"], r["trial"]))
    rng.shuffle(picked)

    OUT.mkdir(parents=True, exist_ok=True)
    sheet = OUT / "sheet.csv"
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for i, r in enumerate(picked, 1):
            s = scen.get(r["id"], {})
            w.writerow({
                "row": i,
                "scenario": r["id"],
                "arm": r["arm"],
                "customer_says": s.get("customer", ""),
                "business_rules": RULES,
                "agent_reply": (r.get("text", "") or "")[:1800],
                "your_verdict_PASS_or_FAIL": "",
                "notes": "",
            })

    # the key stays out of the sheet
    key = {str(i): {"arm": r["arm"], "id": r["id"], "trial": r["trial"],
                    "my_verdict": "PASS" if r["pass"] else "FAIL"}
           for i, r in enumerate(picked, 1)}
    (OUT / "key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")

    print(f"{len(picked)} transcripts -> {sheet}")
    print(f"  strata: {sum(1 for r in picked if r['pass'])} pass, "
          f"{sum(1 for r in picked if not r['pass'])} fail, "
          f"{sum(1 for r in picked if r.get('soft_missed'))} edge")
    print("  my verdicts are in blind/key.json and are not in the sheet")
    print("  the sheet carries the business rules, not my regexes: judge the answer, not the rubric")
    print("\nfill the column your_verdict_PASS_or_FAIL with PASS or FAIL, then run:")
    print("  python evals/blind_score.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
