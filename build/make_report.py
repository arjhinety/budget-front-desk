#!/usr/bin/env python3
"""Build the two-page application summary from the recorded results."""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
OUT = ROOT / "build" / "pdf"
SET = "scenarios-big"


def json_output(cmd: list[str]) -> object:
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if p.returncode:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{p.stderr[-800:]}")
    text = p.stdout.strip()
    return json.loads(text)


def graded(arm: str) -> list[dict]:
    return json_output([sys.executable, str(EVALS / "grade.py"), "--arm", arm,
                        "--json", "--set", SET])


def summarise(arm: str) -> dict:
    rows = graded(arm)
    per: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        per[r["id"]].append(r)
    return {
        "scenarios": len(per),
        "trials": len(rows),
        "passed": sum(r["pass"] for r in rows),
        "strict": sum(1 for v in per.values() if len(v) == 3 and all(x["pass"] for x in v)),
        "gate": sum(1 for v in per.values() if any(
            any(w.startswith("INTEGRITY") for w in x["why"]) for x in v)),
    }


def mt_rows(arm: str) -> list[dict]:
    return json_output([sys.executable, str(EVALS / "grade_mt.py"), "--arm", arm, "--json"])


def mt_summary(arm: str) -> dict:
    rows = mt_rows(arm)
    by_script: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by_script[r["id"]].append(r["pass"])
    return {"n": len(rows), "passed": sum(r["pass"] for r in rows),
            "scripts": len(by_script),
            "strict": sum(1 for x in by_script.values() if len(x) == 3 and all(x))}


def sealed_summary(arm: str) -> dict:
    rows = json_output([sys.executable, str(ROOT / "datasets" / "grade_sealed.py"),
                        "--arm", arm, "--json"])
    amb = set(json.loads((ROOT / "datasets/sealed/graders-sealed.json").read_text())["ambiguous"])
    excluded = set()
    exclusions = ROOT / "datasets/sealed/exclusions.json"
    if exclusions.exists():
        for x in json.loads(exclusions.read_text())["excluded"]:
            if x["record"].startswith(arm.replace("SEALED-", "") + "/"):
                excluded.add(x["record"].split("/", 1)[1].split("#", 1)[0])
    kept = [r for r in rows if r["id"] not in excluded]
    clean = [r for r in kept if r["id"] not in amb]
    return {"all": (sum(r["pass"] for r in rows), len(rows)),
            "kept": (sum(r["pass"] for r in kept), len(kept)),
            "clean": (sum(r["pass"] for r in clean), len(clean)),
            "excluded": sorted(excluded)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    a0, a2, a5 = (summarise(x) for x in ("BIG-A0", "BIG-A2", "A5"))
    mt0, mt5 = mt_summary("MT-A0"), mt_summary("MT-A5")
    sd0, sd5 = sealed_summary("SEALED-A0"), sealed_summary("SEALED-A5")

    md = f"""---
title: "Budget Front Desk"
subtitle: "An agent built from public business pages, measured before and after"
date: {date.today().isoformat()}
---

# The deliverable

A live AI front desk for Budget Heating, Cooling & Plumbing, built from a **25-field
ledger** with page-and-line provenance. It triages emergency, diagnostic and estimate
requests, uses the published catalogue, collects dispatcher intake, and routes to the
booking page or phone. The repository contains the ledger, transcripts, graders,
failures and reproducible scripts.

# Before and after

| | A0 baseline | A5 shipped |
|---|---:|---:|
| single-turn pass@1 | {a0['passed']}/{a0['trials']} ({a0['passed']/a0['trials']:.1%}) | {a5['passed']}/{a5['trials']} ({a5['passed']/a5['trials']:.1%}) |
| strict pass³, shared 53 scenarios | {a0['strict']}/53 | **43/53** |
| integrity-gate scenarios | {a0['gate']}/53 | {a5['gate']}/55 |
| multi-turn, 54 conversations | {mt0['passed']}/54 ({mt0['passed']/54:.0%}) | **{mt5['passed']}/54 ({mt5['passed']/54:.0%})** |
| multi-turn scripts passing all trials | {mt0['strict']}/18 | **{mt5['strict']}/18** |

The tuned arm is better on the scenarios it was iterated against: 71.1% to 87.9%,
with the paired strict-pass comparison b=18, c=1, p<0.001. The multi-turn baseline
now exists: A0 is 36/54 and A5 is 41/54. A5 gains 7 conversations and loses 2;
McNemar p=0.180. The measured direction is positive, but the multi-turn delta is not
statistically settled. These are three trials of 18 scripts, not 54 independent
customers; one gain is A0's unfilled-placeholder integrity failure, so the clean
behavioural signal is narrower than 7 versus 2.

# What changed

The largest multi-turn gains are **arithmetic (2/9 to 5/9)** and **pushback (5/9 to
7/9)**. Memory stays 9/9 in both arms; recovery stays 9/9; change-of-mind stays 3/9.
One A0 failure emitted an unfilled template placeholder; A5 passed that conversation.

# The check I could not tune against

Twenty three-turn scenarios were authored by a different model, with graders frozen
before replies existed. On the original run A0 and A5 both scored **17/20**, agreeing
on 18/20; on the 13 unambiguous scenarios A0 scored 12/13 and A5 11/13. One A5 reply
was then excluded by deterministic cleaning because a render failure was appended to
a complete answer; excluding it leaves A5 at 16/19 overall and 10/12 on the scored
scenarios. The result does not confirm the single-turn gain out of sample, and the
set is too small to call it a regression.

# Limits and failures

- The single-turn comparison is in-sample: A5 and its graders were iterated against
  the same scenarios. Twenty grader corrections were made, all after transcript
  inspection; correction 21 fixed a positive-control bug allowing correct three-term
  totals such as $99 + $150 + $50 = $299.
- Six multi-turn failures were authoring gaps: the brief omitted savings-club
  benefits. The remaining failures are agent misses on hours, overnight constraints,
  and some arithmetic/change-of-mind turns.
- One build showed website-accurate savings-club benefits that were absent from the
  brief while another build declined. The cause is unknown; the repository reports it
  as an open platform question, not as a proven defect.
- A human calibration reached κ=0.911 only after the rule was fitted to the same
  30 transcripts; it is not fresh-sample agreement.

The complete evidence is in `RESULTS.md`, `RIGOR.md`, `FAILURES.md` and
`FINDINGS-FOR-AGENTPLACE.md`. The live agent link is supplied separately.
"""
    (OUT / "report.md").write_text(md, encoding="utf-8")
    html = subprocess.run(["pandoc", str(OUT / "report.md"), "-o", str(OUT / "report.html"),
                           "--standalone", "--metadata", "pagetitle=Budget Front Desk"],
                          capture_output=True, text=True)
    if html.returncode:
        raise SystemExit(html.stderr[:1000])
    print(f"report.md and report.html written; MT A0 {mt0['passed']}/54, A5 {mt5['passed']}/54")
    print(f"sealed original A0 {sd0['all'][0]}/{sd0['all'][1]}, A5 {sd5['all'][0]}/{sd5['all'][1]}; excluded {sd5['excluded']}")
    print("print report.html to report.pdf with Chromium")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
