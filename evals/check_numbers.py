#!/usr/bin/env python3
"""
Every dollar figure an agent says has to exist in the ledger.

This reads a transcript (or the brief itself) and flags any $N that is not one
of the values in facts/business.json. It exists because the cheapest way for an
agent to be wrong is to sound confident about a price nobody published.

Usage:
  python evals/check_numbers.py build/brief.txt
  python evals/check_numbers.py evals/transcripts/*.txt
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "facts"

# A $50 Saturday surcharge is a real published number but lives outside the
# catalogue, so it is added here from the scalar facts rather than the services.
EXTRA_ALLOWED_NOTE = "saturday_surcharge_usd"


def allowed_values() -> tuple[set[int], dict[int, str]]:
    b = json.loads((FACTS / "business.json").read_text(encoding="utf-8"))
    allowed, why = set(), {}
    for s in b["services"]:
        if s["price_usd"]:
            allowed.add(s["price_usd"])
            why[s["price_usd"]] = f"{s['name']} ({s['price_unit']})"
    surcharge = b.get("saturday_surcharge_usd")
    if isinstance(surcharge, int):
        allowed.add(surcharge)
        why[surcharge] = f"Saturday surcharge ({EXTRA_ALLOWED_NOTE})"
    return allowed, why


def derived_for(text: str, base: set[int]) -> set[int]:
    """Sums of prices that actually appear in this document.

    A total is arithmetic only if its parts are named beside it. Allowing every
    pairwise sum of the whole catalogue would let almost any number through.
    """
    present = {int(m.group(1).replace(",", "")) for m in AMOUNT.finditer(text)
               if int(m.group(1).replace(",", "")) in base}
    return {a + c for a in present for c in present}


AMOUNT = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)")


def check(path: Path, allowed: set[int]) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    allowed = allowed | derived_for(text, allowed)
    problems = []
    for m in AMOUNT.finditer(text):
        raw = m.group(1).replace(",", "")
        value = float(raw)
        if value != int(value) or int(value) not in allowed:
            start = max(0, m.start() - 60)
            problems.append(f"{path.name}: ${raw} — …{text[start:m.end() + 40].strip()}…")
    return problems


def main(argv: list[str]) -> int:
    extra = set()
    args = list(argv[1:])
    if "--extra" in args:
        i = args.index("--extra")
        extra = {int(v) for v in args[i + 1].split(",")}
        del args[i:i + 2]
    paths = [Path(a) for a in args]
    if not paths:
        print(__doc__)
        return 2
    allowed, why = allowed_values()
    allowed |= extra
    print(f"ledger allows: {', '.join(f'${v}' for v in sorted(allowed))}")
    total = 0
    for path in paths:
        if not path.exists():
            print(f"missing: {path}")
            total += 1
            continue
        problems = check(path, allowed)
        total += len(problems)
        for p in problems:
            print("  FAIL", p)
    if total:
        print(f"\n{total} figure(s) that no page supports")
        return 1
    print("\n0 unsupported figures — every quote traces to the ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
