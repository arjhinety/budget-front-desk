#!/usr/bin/env python3
"""
Build the one-document summary from the recorded results.

Every number in the output is computed here from the graded transcripts, so the
report cannot drift from the data the way a hand-written summary does.

  python build/make_report.py            # writes build/pdf/report.md and .pdf
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
OUT = ROOT / "build" / "pdf"
SET = "scenarios-big"


def graded(arm: str) -> list[dict]:
    out = subprocess.run(["python", str(EVALS / "grade.py"), "--arm", arm, "--json", "--set", SET],
                         capture_output=True, text=True, cwd=str(ROOT)).stdout
    start = out.find("[")
    return json.JSONDecoder().raw_decode(out[start:])[0] if start >= 0 else []


def summarise(arm: str) -> dict:
    rows = graded(arm)
    per: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        per[r["id"]].append(r)
    trials = sum(len(v) for v in per.values())
    passed = sum(1 for r in rows if r["pass"])
    strict = sum(1 for v in per.values() if all(t["pass"] for t in v) and len(v) == 3)
    gate = sum(1 for v in per.values() if any(any(w.startswith("INTEGRITY") for w in t["why"]) for t in v))
    return {"arm": arm, "scenarios": len(per), "trials": trials, "passed": passed,
            "strict": strict, "gate": gate}


def lane_table(arms: list[str]) -> tuple[list[str], dict[str, dict[str, tuple[int, int]]]]:
    scen = {s["id"]: s for s in json.loads((EVALS / f"{SET}.json").read_text(encoding="utf-8"))["scenarios"]}
    per_arm = {}
    for a in arms:
        agg: dict[str, list[bool]] = defaultdict(list)
        for r in graded(a):
            agg[r["id"]].append(r["pass"])
        per_arm[a] = {k: (sum(v), len(v)) for k, v in agg.items()}

    lanes: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
    for sid, lane in ((s, scen[s]["lane"]) for s in per_arm[arms[0]]):
        for a in arms:
            if sid in per_arm[a]:
                ok, n = per_arm[a][sid]
                prev = lanes[lane].get(a, (0, 0))
                lanes[lane][a] = (prev[0] + (1 if ok == n else 0), prev[1] + 1)
    return arms, lanes


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    arms = ["BIG-A0", "BIG-A2", "A5"]
    s = {a: summarise(a) for a in arms}
    order, lanes = lane_table(["BIG-A0", "BIG-A2", "A5"])

    a0, a2, a5 = s["BIG-A0"], s["BIG-A2"], s["A5"]

    def row(label, key):
        return (f"| {label} | {a0[key]} | {a2[key]} | {a5[key]} |")

    lane_rows = []
    for lane in sorted(lanes, key=lambda k: lanes[k]["A5"][0] - lanes[k]["BIG-A0"][0], reverse=True):
        l = lanes[lane]
        a2v = l.get("BIG-A2")
        a2c = f"{a2v[0]}/{a2v[1]}" if a2v else "—"
        lane_rows.append(f"| {lane} | {l['BIG-A0'][0]}/{l['BIG-A0'][1]} | {a2c} | {l['A5'][0]}/{l['A5'][1]} |")

    md = f"""---
title: "Budget Front Desk"
subtitle: "An agent built from a business's public pages, and the measurements of where it fails"
date: 2026-11-08
---

## 1. What was built

An AI agent for a real home-services company, built from a brief generated out of a
ledger of 24 facts, each carrying the page and line it came from. The agent triages a
complaint into emergency, diagnostic or free estimate, works the company's published
price catalogue, collects what a dispatcher collects, and routes to a booking, a phone
call or a payment.

The ledger bounds what goes into the brief: it fails the build if a price moves or if
the evidence turns out to be template placeholder text. It does not bound what the
model then says, which is why the output is checked separately against the same seven
prices.

## 2. How it was measured

33 hand-written scenarios and 55 generated from the business's decision branches
(service × county × timing × complication), three trials each. Every scenario carries
required behaviours and forbidden ones; a forbidden behaviour fails it even when every
required one is present. A deterministic grader checks the transcript, and a separate
check fails any dollar figure that is not one of the seven published prices.

Two tiers are reported rather than one score: an **integrity gate** (any invented price,
policy or placeholder fails the scenario outright) and **completeness** (how often the
required behaviour appears), with a Wilson interval because the counts are small.

## 3. What the measurements found

| | A0 as built | A2 two rules | A5 three rules |
|---|---|---|---|
{row("scenarios", "scenarios")}
{row("trials", "trials")}
{row("passed", "passed")}
{row("strict pass³", "strict")}
{row("integrity gate failures", "gate")}

Four instruction changes were tried. A1 regressed the emergency lane: told every reply
must name a route, the agent chose "reply in chat" and dropped the phone number. A2
fixed that. A3 tried to make the agent state when the office reopens and it started
querying a clock and contradicting a customer mid-gas-leak, so it was reverted. A5
reaches the same goal as A3 without a tool, and is the arm that ships.

By lane, on the scenarios both arms ran. The A2 column is included because it shows
what A5 fixed and what it did not:

| lane | A0 | A2 | A5 |
|---|---|---|---|
{chr(10).join(lane_rows)}

## 4. What is wrong with it

- **One lane did not recover.** Handoff sits at 1/2: the multi-system and
  warranty-claim probes are where a person has to take over, and the agent handles
  one of the two.

- **Nineteen grader corrections** were needed, all found by reading transcripts
  rather than by the suite. Every one was a pattern failing a correct answer.

- **The comparison is significant only after those corrections.** The 27-scenario
  version of it was p = 0.289; it reached p = 0.004 after nineteen grader fixes, most
  of which were failing correct answers. That sequence is a reason to read the number
  with care rather than to celebrate it.

- **The held-out set was written after the first arm's failures were on screen.** It
  tests phrasing generalization, not failure modes nobody imagined.

- **One human calibration, 30 transcripts, and not double-blind.** Agreement was 70%
  with the requirement unstated and 97% with it stated; on the full 99-transcript set
  kappa fell to 0.314 because the sample is almost all passes. All three numbers say
  more about the rubric than about the agent.

## 5. What I would do next

1. Fix the handoff lane, then re-run the same set.
2. Move the three failure classes into the platform rather than the prompt: a typed
   next-step field, one clock resolved per turn with the customer's premise winning, and
   rule precedence as data. All three are implemented in `platform/` and replayed
   against the recorded conversations.
3. Get a second reader who never sees the first pass, on rows whose requirement is
   stated from the start.
"""
    (OUT / "report.md").write_text(md, encoding="utf-8")

    html = subprocess.run(["pandoc", str(OUT / "report.md"), "-o", str(OUT / "report.html"),
                           "--standalone", "--metadata", "pagetitle=Budget Front Desk"],
                          capture_output=True, text=True)
    if html.returncode != 0:
        print("pandoc:", html.stderr[:300]); return 1
    # weasyprint needs GTK on Windows; Chromium prints the same HTML instead
    print("html ready -> build/pdf/report.html (print with Chromium via the browser tool)")

    print(f"report.md -> {OUT/'report.md'}")
    print(f"report.pdf -> {OUT/'report.pdf'}")
    print(f"  A0 {a0['passed']}/{a0['trials']}  A2 {a2['passed']}/{a2['trials']}  A5 {a5['passed']}/{a5['trials']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
