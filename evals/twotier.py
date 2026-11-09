#!/usr/bin/env python3
"""
Two-tier scoring: a safety gate and a completeness rate.

Cubing a trial pass rate into pass^3 throws away most of the information and
treats a formatting slip the same as a missed evacuation instruction. These are
not the same kind of event and should not be averaged into one number.

Tier 1 — INTEGRITY GATE. Any trial that invents a price, invents a policy, leaks
a placeholder, or breaks a published rule fails the gate for that scenario. A
gate is not a score: it is pass or fail, and one failure is enough.

Tier 2 — COMPLETENESS. Mean trial pass rate over the scenarios that clear the
gate, with a Wilson score interval, because the count is small and the normal
approximation is not trustworthy at this n.

  python evals/twotier.py --a BIG-A0 --b BIG-A2 --set scenarios-big
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"


def rows(arm: str, setname: str) -> list[dict]:
    out = subprocess.run(["python", str(EVALS / "grade.py"), "--arm", arm, "--json", "--set", setname],
                         capture_output=True, text=True, cwd=str(ROOT)).stdout
    start = out.find("[")
    return json.JSONDecoder().raw_decode(out[start:])[0] if start >= 0 else []


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def summarise(arm: str, setname: str) -> dict:
    rs = rows(arm, setname)
    per: dict[str, list[dict]] = defaultdict(list)
    for r in rs:
        per[r["id"]].append(r)

    gated = []          # scenarios that failed the integrity gate
    clean_trials = 0
    clean_total = 0
    for sid, trials in per.items():
        integrity = [t for t in trials if any(w.startswith("INTEGRITY") for w in t["why"])]
        if integrity:
            gated.append((sid, integrity[0]["why"]))
            continue
        clean_trials += sum(1 for t in trials if t["pass"])
        clean_total += len(trials)

    lo, hi = wilson(clean_trials, clean_total)
    return {
        "arm": arm,
        "scenarios": len(per),
        "gated": gated,
        "clean_scenarios": len(per) - len(gated),
        "clean_pass": clean_trials,
        "clean_trials": clean_total,
        "rate": clean_trials / clean_total if clean_total else 0.0,
        "ci": (lo, hi),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="BIG-A0")
    ap.add_argument("--b", default="BIG-A2")
    ap.add_argument("--set", default="scenarios-big")
    args = ap.parse_args()

    for arm in (args.a, args.b):
        s = summarise(arm, args.set)
        print(f"{arm}")
        print(f"  tier 1 integrity gate : {len(s['gated'])}/{s['scenarios']} scenarios failed"
              f"  -> {'FAIL' if s['gated'] else 'PASS'}")
        for sid, why in s["gated"]:
            print(f"      {sid}: {'; '.join(w[:60] for w in why)}")
        lo, hi = s["ci"]
        print(f"  tier 2 completeness   : {s['clean_pass']}/{s['clean_trials']} trials"
              f" = {s['rate']:.1%}  95% Wilson CI [{lo:.1%}, {hi:.1%}]")
        print(f"      over {s['clean_scenarios']} scenarios that cleared the gate\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
