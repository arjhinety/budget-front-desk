#!/usr/bin/env python3
"""
The comparison, done properly.

An aggregate "85% -> 98%" hides the only thing that matters: which scenarios
changed verdict. This prints the 2x2 discordance table and runs an exact
McNemar test on the discordant pairs, because with 27 scenarios the difference
between two arms lives entirely inside those pairs.

Usage:  python evals/stats.py --a A0 --b A2
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"


def per_scenario(arm: str, trials: int = 3, setname: str = "scenarios") -> dict[str, bool]:
    """A scenario counts as passed only if it passed every trial."""
    recs = json.loads((EVALS / "results" / f"{arm}.json").read_text(encoding="utf-8"))["records"]
    seen: dict[str, list[bool]] = {}
    for r in recs:
        if "thread" not in r:
            continue
        seen.setdefault(r["id"], []).append(True)
    # verdicts come from grade.py's own logic; import it rather than re-implement
    import subprocess
    out = subprocess.run(
        ["python", str(EVALS / "grade.py"), "--arm", arm, "--json", "--set", setname],
        capture_output=True, text=True, cwd=str(ROOT),
    ).stdout
    start = out.find("[")
    rows, _ = json.JSONDecoder().raw_decode(out[start:]) if start >= 0 else ([], 0)
    agg: dict[str, list[bool]] = {}
    for r in rows:
        agg.setdefault(r["id"], []).append(r["pass"])
    return {k: (all(v) and len(v) >= trials) for k, v in agg.items()}


def binom_two_sided(b: int, c: int) -> float:
    """Exact McNemar: two-sided binomial test on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def common(arms: list[str], lane: str | None, setname: str = "scenarios") -> None:
    """Pass rate over only the scenarios every listed arm actually ran."""
    scen = {x["id"]: x for x in json.loads((EVALS / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
    per = {a: per_scenario(a, setname=setname) for a in arms}
    shared = set.intersection(*[set(v) for v in per.values()])
    if lane:
        shared = {i for i in shared if scen.get(i, {}).get("lane") == lane}
    print(f"common scenarios across {', '.join(arms)}"
          + (f" in lane '{lane}'" if lane else "") + f": {len(shared)}")
    print(f"  {', '.join(sorted(shared)) or '-'}")
    for a in arms:
        ok = sum(1 for i in shared if per[a][i])
        print(f"  {a}: {ok}/{len(shared)} strict pass^3")
    if len(arms) == 2:
        x, y = arms
        b = sum(1 for i in shared if not per[x][i] and per[y][i])
        c = sum(1 for i in shared if per[x][i] and not per[y][i])
        print(f"\n  discordant: b={b} (gained by {y}), c={c} (lost by {y})")
        print(f"  exact McNemar two-sided p = {binom_two_sided(b, c):.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="A0")
    ap.add_argument("--b", default="A2")
    ap.add_argument("--common", default="", help="comma-separated arms; report only shared scenarios")
    ap.add_argument("--lane", default="")
    ap.add_argument("--set", default="scenarios")
    ap.add_argument("--bootstrap", type=int, default=0, help="paired bootstrap resamples")
    args = ap.parse_args()

    if args.common:
        common(args.common.split(","), args.lane or None, args.set)
        return 0

    a, b = per_scenario(args.a, setname=args.set), per_scenario(args.b, setname=args.set)
    shared = sorted(set(a) & set(b))
    both_pass = [s for s in shared if a[s] and b[s]]
    both_fail = [s for s in shared if not a[s] and not b[s]]
    gained = [s for s in shared if not a[s] and b[s]]
    lost = [s for s in shared if a[s] and not b[s]]

    print(f"{args.a} vs {args.b} — {len(shared)} shared scenarios\n")
    print(f"{'':22}{args.b + ' pass':>12}{args.b + ' fail':>12}")
    print(f"{args.a + ' pass':>22}{len(both_pass):>12}{len(lost):>12}")
    print(f"{args.a + ' fail':>22}{len(gained):>12}{len(both_fail):>12}")

    print(f"\ngained ({len(gained)}): {', '.join(gained) or '-'}")
    print(f"lost   ({len(lost)}): {', '.join(lost) or '-'}")

    if args.bootstrap:
        import random
        diffs = []
        idx = list(shared)
        rng = random.Random(20261108)
        for _ in range(args.bootstrap):
            sample = [rng.choice(idx) for _ in idx]
            da = sum(1 for i in sample if a[i]) / len(sample)
            db = sum(1 for i in sample if b[i]) / len(sample)
            diffs.append(db - da)
        diffs.sort()
        lo = diffs[int(0.025 * len(diffs))]
        hi = diffs[int(0.975 * len(diffs)) - 1]
        obs = sum(1 for i in shared if b[i]) / len(shared) - sum(1 for i in shared if a[i]) / len(shared)
        print(f"\npaired bootstrap ({args.bootstrap} resamples over scenarios):")
        print(f"  observed difference {obs:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")
        print("  " + ("CI excludes zero" if lo > 0 or hi < 0 else "CI includes zero"))

    p = binom_two_sided(len(gained), len(lost))
    print(f"\ndiscordant pairs: {len(gained) + len(lost)}  (b={len(gained)}, c={len(lost)})")
    print(f"exact McNemar two-sided p = {p:.3f}")
    if p > 0.05:
        print("  -> the difference is not distinguishable from noise at n=27.")
        print("     Report it as 'consistent with an improvement', not as an improvement.")
    else:
        print("  -> significant at 0.05 on the discordant pairs alone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
