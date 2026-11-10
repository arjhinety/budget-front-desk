#!/usr/bin/env python3
"""
Grade a multi-turn arm.

A conversation passes only if every turn-tagged check passes on its own turn and
every all-replies check passes on every reply. The customer experiences the whole
conversation, so a wrong price at turn 3 fails the conversation even if turns 1
and 2 were perfect.

  python evals/grade_mt.py --arm MT-A5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
sys.path.insert(0, str(EVALS))

from grade import agent_text, allowed_money, derived_money  # noqa: E402

AMOUNT = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)")


def load(name: str):
    return json.loads((EVALS / name).read_text(encoding="utf-8"))


def grade_record(rec: dict, checks: dict, globals_: list[dict], money: set[int], derived: set[int]) -> dict:
    replies = rec.get("replies", [])
    fails = []          # (turn, reason)
    for i, reply in enumerate(replies, 1):
        txt = reply
        # turn-tagged checks
        for pat in checks.get(str(i), {}).get("must", []):
            if not re.search(pat, txt, re.I):
                fails.append((i, f"MUST missing /{pat[:50]}/"))
        for pat in checks.get(str(i), {}).get("must_not", []):
            m = re.search(pat, txt, re.I)
            if m:
                before = txt[max(0, m.start() - 60):m.start()].lower().rsplit(".", 1)[-1]
                if not re.search(r"\b(can.t|cannot|don.t|do not|doesn.t|won.t|not|never|no|unable)\b", before):
                    fails.append((i, f"INTEGRITY forbidden /{pat[:40]}/"))
        # all-replies checks
        for rule in globals_:
            m = re.search(rule["pattern"], txt, re.I)
            if not m:
                continue
            before = txt[max(0, m.start() - 60):m.start()].lower().rsplit(".", 1)[-1]
            if re.search(r"\b(can.t|cannot|don.t|do not|doesn.t|won.t|not|never|no|unable)\b", before):
                continue
            fails.append((i, f"INTEGRITY {rule['id']}"))
        # price integrity on every reply, allowing sums of two published prices
        for m in AMOUNT.finditer(txt):
            raw = m.group(1).replace(",", "")
            tail = txt[m.end():m.end() + 1]
            if tail in ("\n", "") and any(str(a).startswith(raw) and str(a) != raw for a in money):
                continue
            v = int(float(raw))
            if v not in money and v not in derived and not any(v == a + b for a in money for b in money):
                fails.append((i, f"INTEGRITY UNSOURCED_PRICE ${raw}"))
    return {"id": rec["id"], "family": rec.get("family"), "trial": rec["trial"],
            "pass": not fails, "fails": fails, "first_fail_turn": fails[0][0] if fails else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="MT-A5")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load("scenarios-mt.json")["scripts"]
    graders = load("graders-mt.json")
    money = allowed_money()
    derived = derived_money(money)

    recs = load(f"results/{args.arm}.json")["records"]
    rows = []
    for r in recs:
        if "error" in r:
            rows.append({"id": r["id"], "trial": r["trial"], "pass": False,
                         "fails": [("?", "HARNESS: " + r["error"])], "first_fail_turn": None})
            continue
        rows.append(grade_record(r, graders["scripts"].get(r["id"], {}),
                                 graders["global_must_not"], money, derived))

    if args.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return 0

    per: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        per[r["id"]].append(r["pass"])
    k = max((len(v) for v in per.values()), default=0)
    passed = sum(1 for r in rows if r["pass"])
    strict = sum(1 for v in per.values() if all(v) and len(v) == k)

    print(f"arm {args.arm}: {passed}/{len(rows)} conversations pass ({passed/len(rows):.0%})" if rows else "no records")
    print(f"strict pass^{k}: {strict}/{len(per)} scripts passed on every trial")

    by_family: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by_family[r.get("family") or "?"].append(r["pass"])
    print("\nby family:")
    for fam in sorted(by_family):
        v = by_family[fam]
        print(f"  {fam:16} {sum(v)}/{len(v)}")

    turns: dict[int, int] = defaultdict(int)
    for r in rows:
        if r["first_fail_turn"]:
            turns[r["first_fail_turn"]] += 1
    if turns:
        print("\nfirst failure by turn:", dict(sorted(turns.items())))

    fails = [r for r in rows if not r["pass"]]
    if fails:
        print(f"\nfailures ({len(fails)}):")
        for r in fails[:12]:
            print(f"  {r['id']}#{r['trial']}: " + "; ".join(f"t{t}:{why[:52]}" for t, why in r["fails"][:3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
