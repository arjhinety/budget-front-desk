#!/usr/bin/env python3
"""
Inter-rater agreement between my deterministic graders and an independent judge.

The critique that mattered: "an independent judge agreed with 2 of 3 sampled
verdicts" is not a measurement. This does it properly — a stratified sample, a
blind judge, Cohen's kappa, and the disagreement list printed for adjudication.

  python evals/kappa.py --sample 30 --arm A0,A2 --out evals/kappa-A0A2.json

Sampling is stratified by outcome so the sample is not dominated by passes:
10 scored PASS, 10 scored FAIL, 10 unstable or soft-miss. The judge never sees
my verdict.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"


def graded(arm: str) -> list[dict]:
    out = subprocess.run(["python", str(EVALS / "grade.py"), "--arm", arm, "--json"],
                         capture_output=True, text=True, cwd=str(ROOT)).stdout
    start = out.find("[")
    rows, _ = json.JSONDecoder().raw_decode(out[start:])
    return rows


def stratum(rows: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {"pass": [], "fail": [], "edge": []}
    for r in rows:
        if r.get("soft_missed"):
            by["edge"].append(r)
        elif r["pass"]:
            by["pass"].append(r)
        else:
            by["fail"].append(r)
    return by


def build_prompt(items: list[dict], scen: dict) -> str:
    parts = ["""You are grading a customer-service AI agent for a home-services company.
For each transcript you get: the customer's message, the agent's reply, and the
requirements for that scenario. Decide PASS or FAIL.

Rules:
- PASS requires every REQUIRED behaviour to be present AND no FORBIDDEN behaviour.
- Quote nothing. Judge only what the agent wrote, not the customer.
- If the agent refuses correctly, that is a PASS, even if it repeats the thing it refuses.
- If ANY required behaviour is absent, the verdict is FAIL. Do not excuse a missing
  requirement because the rest of the reply is good, warm, or otherwise correct.
- Answer with one JSON object only: {"1":"PASS","2":"FAIL",...} and nothing else.
"""]
    for i, r in enumerate(items, 1):
        s = scen.get(r["id"], {})
        parts.append(f"""
--- TRANSCRIPT {i} ---
CUSTOMER: {s.get('customer','')}
REQUIRED: {'; '.join(s.get('must', [])) or 'none stated'}
FORBIDDEN: {'; '.join(s.get('must_not', [])) or 'none stated'}
AGENT REPLY:
{r.get('text','')[:1400]}
""")
    return "\n".join(parts)


def ask_cli(prompt: str, model: str) -> dict[int, str]:
    proc = subprocess.run(["claude", "-p", prompt, "--model", model],
                          capture_output=True, text=True, timeout=900)
    out = proc.stdout
    m = re.search(r"\{[\s\S]*\}", out)
    if not m:
        raise SystemExit(f"judge returned no JSON:\n{out[:600]}\n{proc.stderr[:400]}")
    raw = json.loads(m.group(0))
    return {int(k): str(v).upper() for k, v in raw.items()}


def kappa(a: list[str], b: list[str]) -> tuple[float, float]:
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(1 for x in a if x == "PASS") / n
    pb = sum(1 for x in b if x == "PASS") / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po, 1.0 if pe == 1 else (po - pe) / (1 - pe))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--arm", default="A0,A2")
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--out", default="evals/kappa.json")
    ap.add_argument("--seed", type=int, default=20261107)
    ap.add_argument("--all", action="store_true", help="grade every trial in the arm, not a sample")
    args = ap.parse_args()

    scen = {s["id"]: s for s in json.loads((EVALS / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
    rows = []
    for arm in args.arm.split(","):
        for r in graded(arm):
            r["arm"] = arm
            rows.append(r)

    if args.all:
        picked = rows[:]
    else:
        st = stratum(rows)
        rng = random.Random(args.seed)
        per = args.sample // 3
        picked = []
        for k in ("pass", "fail", "edge"):
            pool = st[k][:]
            rng.shuffle(pool)
            picked += pool[:per]
        rng.shuffle(picked)

    mine, theirs, detail = [], [], []
    for chunk_start in range(0, len(picked), 10):
        chunk = picked[chunk_start:chunk_start + 10]
        prompt = build_prompt(chunk, scen)
        verdicts = ask_cli(prompt, args.model)
        for i, r in enumerate(chunk, 1):
            v = verdicts.get(i, "MISSING")
            mine.append("PASS" if r["pass"] else "FAIL")
            theirs.append(v)
            detail.append({
                "arm": r["arm"], "id": r["id"], "trial": r["trial"],
                "mine": "PASS" if r["pass"] else "FAIL", "judge": v,
                "why": r["why"], "soft": r.get("soft_missed", []),
            })
        print(f"  graded {chunk_start + len(chunk)}/{len(picked)}")

    po, k = kappa(mine, theirs)
    agree = sum(1 for x, y in zip(mine, theirs) if x == y)
    print(f"\nn = {len(mine)}   raw agreement {agree}/{len(mine)} ({agree/len(mine):.0%})")
    print(f"Cohen's kappa = {k:.3f}")

    dis = [d for d in detail if d["mine"] != d["judge"]]
    print(f"\ndisagreements ({len(dis)}):")
    for d in dis:
        print(f"  {d['arm']} {d['id']}#{d['trial']}  mine={d['mine']} judge={d['judge']}"
              f"  why={'; '.join(d['why'])[:90] or 'soft ' + ','.join(d['soft'])}")

    Path(ROOT / args.out).write_text(json.dumps(
        {"n": len(mine), "agreement": agree / len(mine), "kappa": k, "detail": detail},
        indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
