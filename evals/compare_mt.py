#!/usr/bin/env python3
"""
Compare two multi-turn arms, per family and per script.

  python evals/compare_mt.py --a MT-A0 --b MT-A5

Reports conversations passed, strict pass^3, the per-family split, and the
discordant pairs with an exact McNemar test. Only scripts both arms have run are
compared, so a partial run gives a partial comparison rather than a misleading one.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def graded(arm: str) -> dict[str, dict]:
    out = subprocess.run([sys.executable, str(ROOT / "evals" / "grade_mt.py"),
                          "--arm", arm, "--json"],
                         capture_output=True, text=True, cwd=ROOT)
    if out.returncode != 0:
        raise SystemExit(f"grading {arm} failed:\n{out.stderr[-600:]}")
    return {f"{r['id']}#{r['trial']}": r for r in json.loads(out.stdout)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="MT-A0")
    ap.add_argument("--b", default="MT-A5")
    args = ap.parse_args()

    a, b = graded(args.a), graded(args.b)
    shared = sorted(set(a) & set(b))
    if not shared:
        raise SystemExit(f"no shared conversations between {args.a} and {args.b}")

    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))

    print(f"{args.a} vs {args.b} — {len(shared)} shared conversations")
    if only_a or only_b:
        print(f"  not compared: {args.a} has {len(only_a)} more, {args.b} has {len(only_b)} more")

    pa = sum(a[k]["pass"] for k in shared)
    pb = sum(b[k]["pass"] for k in shared)
    print(f"  {args.a}: {pa}/{len(shared)} ({pa/len(shared):.0%})")
    print(f"  {args.b}: {pb}/{len(shared)} ({pb/len(shared):.0%})")

    fam = defaultdict(lambda: [0, 0, 0])
    for k in shared:
        f = a[k].get("family", "?")
        fam[f][0] += 1
        fam[f][1] += bool(a[k]["pass"])
        fam[f][2] += bool(b[k]["pass"])
    print(f"\n  {'family':16} {args.a:>8} {args.b:>8}")
    for f, (n, x, y) in sorted(fam.items()):
        print(f"  {f:16} {x:>4}/{n:<3} {y:>4}/{n:<3}")

    gained = [k for k in shared if b[k]["pass"] and not a[k]["pass"]]
    lost = [k for k in shared if a[k]["pass"] and not b[k]["pass"]]
    n = len(gained) + len(lost)
    p = 1.0
    if n:
        p = min(1.0, 2 * sum(comb(n, i) for i in range(0, min(len(gained), len(lost)) + 1)) / 2 ** n)
    print(f"\n  gained by {args.b}: {len(gained)}  {gained if gained else ''}")
    print(f"  lost   by {args.b}: {len(lost)}  {lost if lost else ''}")
    print(f"  exact McNemar: b={len(gained)} c={len(lost)} p={p:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
