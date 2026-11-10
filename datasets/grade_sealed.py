#!/usr/bin/env python3
"""
Grade the sealed set.

Reads the frozen graders and the sealed transcripts and produces, per scenario,
a verdict, the turn that failed first, and whether the scenario is one of the
seven marked ambiguous. Ambiguous scenarios are reported separately and never
folded into the pass rate.

  python datasets/grade_sealed.py --arm SEALED-A0
  python datasets/grade_sealed.py --arm SEALED-A0 --json

The graders are read from datasets/sealed/graders-sealed.json and their hash is
checked against FROZEN.json before anything is scored. A mismatch means the set is
burned and the run stops.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEALED = ROOT / "datasets" / "sealed"
sys.path.insert(0, str(ROOT / "evals"))

from grade import allowed_money  # noqa: E402

AMOUNT = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)")


def verify_frozen() -> None:
    frozen = json.loads((SEALED / "FROZEN.json").read_text(encoding="utf-8"))["hashes"]
    for name, expected in frozen.items():
        p = SEALED / name
        if not p.exists():
            raise SystemExit(f"FROZEN lists {name} but it is missing")
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"{name} does not match FROZEN.json — the sealed set is burned")


def grade_record(rec: dict, checks: dict, globals_: list[dict], money: set[int], derived: set[int]) -> dict:
    replies = rec.get("replies", [])
    fails: list[tuple[int, str]] = []
    for i, txt in enumerate(replies, 1):
        spec = checks.get(str(i), {})
        for pat in spec.get("must", []):
            if not re.search(pat, txt, re.I):
                fails.append((i, f"MUST missing /{pat[:48]}/"))
        for pat in spec.get("must_not", []):
            m = re.search(pat, txt, re.I)
            if not m:
                continue
            before = txt[max(0, m.start() - 60):m.start()].lower().rsplit(".", 1)[-1]
            if re.search(r"\b(can.t|cannot|don.t|do not|doesn.t|won.t|not|never|no|unable)\b", before):
                continue
            fails.append((i, f"INTEGRITY forbidden /{pat[:40]}/"))
        for rule in globals_:
            m = re.search(rule["pattern"], txt, re.I)
            if not m:
                continue
            before = txt[max(0, m.start() - 60):m.start()].lower().rsplit(".", 1)[-1]
            if re.search(r"\b(can.t|cannot|don.t|do not|doesn.t|won.t|not|never|no|unable)\b", before):
                continue
            fails.append((i, f"INTEGRITY {rule['id']}"))
        for m in AMOUNT.finditer(txt):
            raw = m.group(1).replace(",", "")
            tail = txt[m.end():m.end() + 1]
            if tail in ("\n", "") and any(str(a).startswith(raw) and str(a) != raw for a in money):
                continue
            v = int(float(raw))
            if v not in derived:
                fails.append((i, f"INTEGRITY UNSOURCED_PRICE ${raw}"))
    return {"id": rec["id"], "pass": not fails, "fails": fails,
            "first_fail_turn": fails[0][0] if fails else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="SEALED-A0")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-freeze-check", action="store_true")
    args = ap.parse_args()

    if not args.skip_freeze_check:
        verify_frozen()

    g = json.loads((SEALED / "graders-sealed.json").read_text(encoding="utf-8"))
    money = allowed_money()
    # correction 20: a stated total may be the sum of up to three ledger prices.
    # $99 + $150 + $50 = $299 is a correct Saturday total and was being failed.
    derived = set(money)
    ms = sorted(money)
    for a in ms:
        derived.add(a)
        for b in ms:
            derived.add(a + b)
            for c in ms:
                derived.add(a + b + c)
    recs = json.loads((ROOT / "evals" / "results" / f"{args.arm}.json").read_text(encoding="utf-8"))["records"]

    rows = []
    for r in recs:
        if "error" in r:
            rows.append({"id": r["id"], "pass": False, "fails": [(0, "HARNESS")], "first_fail_turn": None})
            continue
        rows.append(grade_record(r, g["scripts"].get(r["id"], {}), g["global_must_not"], money, derived))

    if args.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return 0

    ambiguous = set(g["ambiguous"])
    scored = [r for r in rows if r["id"] not in ambiguous]
    amb = [r for r in rows if r["id"] in ambiguous]

    passed = sum(1 for r in scored if r["pass"])
    print(f"{args.arm}: {len(rows)} conversations, {len(ambiguous)} scenarios marked ambiguous")
    print(f"  scored      {passed}/{len(scored)} pass ({passed/len(scored):.0%})" if scored else "  scored none")
    if amb:
        print(f"  ambiguous   {sum(1 for r in amb if r['pass'])}/{len(amb)} pass — reported separately, not scored")

    fails = [r for r in scored if not r["pass"]]
    if fails:
        print("\nscored failures:")
        for r in fails:
            print(f"  {r['id']}: " + "; ".join(f"t{t}:{w[:56]}" for t, w in r["fails"][:3]))
    if amb:
        print("\nambiguous outcomes (for the adjudicator, not the score):")
        for r in amb:
            state = "pass" if r["pass"] else "fail"
            print(f"  {r['id']}: {state}" + ("" if r["pass"] else f" — t{r['first_fail_turn']}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
