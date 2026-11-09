#!/usr/bin/env python3
"""
Score a returned blind sheet against my graders.

Refuses rather than guesses: an unfilled row, a blank verdict, a value that is
not PASS or FAIL, a reordered sheet, or a sheet whose rows do not match the key
all stop the run. A blank answer is not a no, and a silently reordered sheet
would pair verdicts with the wrong transcripts.

  python evals/blind_score.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent.parent / "evals"
OUT = EVALS / "blind"


def kappa(a: list[str], b: list[str]) -> tuple[float, float]:
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(1 for x in a if x == "PASS") / n
    pb = sum(1 for x in b if x == "PASS") / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return po, (1.0 if pe == 1 else (po - pe) / (1 - pe))


def main() -> int:
    sheet, keyfile = OUT / "sheet.csv", OUT / "key.json"
    if not sheet.exists() or not keyfile.exists():
        print("no sheet: run evals/blind_export.py first")
        return 2

    key = json.loads(keyfile.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))

    if len(rows) != len(key):
        print(f"sheet has {len(rows)} rows, key has {len(key)} — refusing")
        return 2

    mine, theirs, detail = [], [], []
    for r in rows:
        i = r["row"].strip()
        if i not in key:
            print(f"row {i} is not in the key — the sheet was reordered or edited; refusing")
            return 2
        v = (r["your_verdict_PASS_or_FAIL"] or "").strip().upper()
        if v not in ("PASS", "FAIL"):
            print(f"row {i} has verdict {v!r}. A blank is not a no. Fill every row, then re-run.")
            return 2
        mine.append(key[i]["my_verdict"])
        theirs.append(v)
        detail.append({"row": i, "arm": key[i]["arm"], "id": key[i]["id"],
                       "mine": key[i]["my_verdict"], "yours": v,
                       "notes": r.get("notes", "")})

    po, k = kappa(mine, theirs)
    agree = sum(1 for x, y in zip(mine, theirs) if x == y)
    print(f"n = {len(mine)}   agreement {agree}/{len(mine)} ({agree/len(mine):.0%})")
    print(f"Cohen's kappa = {k:.3f}")

    dis = [d for d in detail if d["mine"] != d["yours"]]
    print(f"\ndisagreements ({len(dis)}):")
    for d in dis:
        print(f"  row {d['row']:>2}  {d['arm']} {d['id']}  mine={d['mine']} yours={d['yours']}"
              + (f"  — {d['notes']}" if d["notes"] else ""))
    if not dis:
        print("  none")

    (OUT / "result.json").write_text(
        json.dumps({"n": len(mine), "agreement": agree / len(mine), "kappa": k, "detail": detail},
                   indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n-> {OUT / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
