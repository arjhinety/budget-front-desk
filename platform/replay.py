#!/usr/bin/env python3
"""
Replay the recorded conversations through the platform middleware.

This is the part that turns PLATFORM-NOTE.md from an essay into a measurement:
if the typed next-step module had been in front of the agent, how many of the
failures that actually happened would it have caught, and how many good replies
would it have touched?

  python platform/replay.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "platform"))

import nextstep  # noqa: E402
import clock  # noqa: E402
import precedence  # noqa: E402

from grade import agent_text  # noqa: E402  (same stripping the graders use)

ARMS = ["A0", "A1", "A2", "A3"]


def graded(arm: str) -> list[dict]:
    out = subprocess.run(["python", str(ROOT / "evals" / "grade.py"), "--arm", arm, "--json"],
                         capture_output=True, text=True, cwd=str(ROOT)).stdout
    start = out.find("[")
    rows, _ = json.JSONDecoder().raw_decode(out[start:]) if start >= 0 else ([], 0)
    return rows


def main() -> int:
    b = nextstep.DEFAULT
    caught = missed = clean_flagged = clean_ok = 0
    examples: list[str] = []

    for arm in ARMS:
        for r in graded(arm):
            if "text" not in r:
                continue
            reply = r["text"]
            audit = nextstep.audit(reply, b)
            failed_for_route = any(
                ("636" in w) or ("phone" in w) or ("call" in w) or ("booking" in w) or ("confirm" in w)
                for w in r["why"]
            )
            if failed_for_route:
                if not audit["has_next_step"]:
                    caught += 1
                    if len(examples) < 6:
                        examples.append(f"  caught  {arm} {r['id']}#{r['trial']}: no typed next step")
                else:
                    missed += 1
                    if len(examples) < 12:
                        examples.append(f"  MISSED  {arm} {r['id']}#{r['trial']}: graded fail but module found {audit['kind']}")
            else:
                if not audit["has_next_step"]:
                    clean_flagged += 1
                else:
                    clean_ok += 1

    print("typed next-step module, replayed over every recorded trial")
    print(f"  failures about a missing route : {caught + missed}")
    print(f"    flagged by the module        : {caught}")
    print(f"    not flagged (would slip)     : {missed}")
    print(f"  trials that did not fail on a route: {clean_flagged + clean_ok}")
    print(f"    module would still repair    : {clean_flagged}  <- cost of the guard")
    print(f"    module leaves alone          : {clean_ok}")
    for e in examples:
        print(e)

    print("\nclock, replayed on the after-hours probes")
    for text, now in [
        ("my water heater burst at 11pm sunday night, i need someone now", datetime(2026, 11, 8, 23, 0)),
        ("its sunday 11pm and i smell gas by the furnace", datetime(2026, 11, 8, 23, 0)),
        ("ill be home after 6 on weekdays, can you still come", datetime(2026, 11, 9, 10, 0)),
        ("can i get someone out late afternoon", datetime(2026, 11, 9, 10, 0)),
    ]:
        f = clock.resolve(text, now)
        print(f"  {text[:48]:50} -> {clock.spoken(f)}")

    print("\nrules, replayed on the coverage probes")
    rules = precedence.default_rules()
    for facts in [
        {"job": "diagnostic", "county": "Franklin"},
        {"job": "diagnostic", "county": "St. Charles"},
        {"job": "water_heater_replacement", "county": "Franklin"},
        {"job": "plumbing_equipment_estimate", "county": "St. Louis"},
    ]:
        res = precedence.resolve(rules, facts)
        print(f"  {str(facts):58} -> allowed={res.allowed}  ({res.rule})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
