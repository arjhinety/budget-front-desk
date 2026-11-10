#!/usr/bin/env python3
"""Build the two-page application summary from the recorded results."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import date
from math import comb
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
    amb = set(json.loads((ROOT / "datasets/sealed/graders-sealed.json").read_text(encoding="utf-8"))["ambiguous"])
    excluded = set()
    exclusions = ROOT / "datasets/sealed/exclusions.json"
    if exclusions.exists():
        for x in json.loads(exclusions.read_text(encoding="utf-8"))["excluded"]:
            if x["record"].startswith(arm.replace("SEALED-", "") + "/"):
                excluded.add(x["record"].split("/", 1)[1].split("#", 1)[0])
    kept = [r for r in rows if r["id"] not in excluded]
    clean = [r for r in kept if r["id"] not in amb]
    return {"all": (sum(r["pass"] for r in rows), len(rows)),
            "kept": (sum(r["pass"] for r in kept), len(kept)),
            "clean": (sum(r["pass"] for r in clean), len(clean)),
            "unambiguous_all": (sum(r["pass"] for r in rows if r["id"] not in amb),
                                sum(r["id"] not in amb for r in rows)),
            "excluded": sorted(excluded)}


def paired_strict(arms: list[str]) -> dict:
    """Use exactly the same scenarios for strict comparisons and lane tables."""
    per_arm = {}
    for arm in arms:
        grouped = defaultdict(list)
        for row in graded(arm):
            grouped[row["id"]].append(row["pass"])
        per_arm[arm] = {sid: len(v) == 3 and all(v) for sid, v in grouped.items()}
    shared = sorted(set.intersection(*(set(v) for v in per_arm.values())))
    if not shared:
        raise SystemExit("No shared single-turn scenarios")
    scenarios = json.loads((EVALS / f"{SET}.json").read_text(encoding="utf-8"))["scenarios"]
    lane_for = {s["id"]: s["lane"] for s in scenarios}
    lanes = defaultdict(lambda: {arm: 0 for arm in arms} | {"n": 0})
    for sid in shared:
        lane = lanes[lane_for[sid]]
        lane["n"] += 1
        for arm in arms:
            lane[arm] += per_arm[arm][sid]
    before, after = per_arm[arms[0]], per_arm[arms[-1]]
    gained = sum(not before[sid] and after[sid] for sid in shared)
    lost = sum(before[sid] and not after[sid] for sid in shared)
    return {"n": len(shared), "lanes": lanes, "gained": gained, "lost": lost,
            "totals": {arm: sum(per_arm[arm][sid] for sid in shared) for arm in arms},
            "p": exact_p(gained, lost)}


def exact_p(gained: int, lost: int) -> float:
    n = gained + lost
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(gained, lost) + 1)) / 2 ** n) if n else 1.0


def fraction(pair: tuple[int, int]) -> str:
    return f"{pair[0]}/{pair[1]}"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    mt0, mt5 = mt_summary("MT-A0"), mt_summary("MT-A5")
    sd0, sd5 = sealed_summary("SEALED-A0"), sealed_summary("SEALED-A5")
    paired = paired_strict(["BIG-A0", "BIG-A2", "A5"])
    lanes = paired["lanes"]
    lane_order = ["coverage", "diagnostic", "free estimate", "trust",
                  "emergency", "scheduling", "off-task", "handoff"]
    lane_table = "\n".join(
        f"| {lane.title()} | {lanes[lane]['BIG-A0']}/{lanes[lane]['n']} "
        f"| {lanes[lane]['A5']}/{lanes[lane]['n']} |" for lane in lane_order)
    mt_before = {(r["id"], r["trial"]): r["pass"] for r in mt_rows("MT-A0")}
    mt_after = {(r["id"], r["trial"]): r["pass"] for r in mt_rows("MT-A5")}
    if set(mt_before) != set(mt_after):
        raise SystemExit("Multi-turn arms are incomplete or do not match")
    mt_gained = sum(mt_after[k] and not mt_before[k] for k in mt_before)
    mt_lost = sum(mt_before[k] and not mt_after[k] for k in mt_before)
    corrections = json.loads((EVALS / "graders.json").read_text(encoding="utf-8"))["_corrections"]
    correction_count = len(corrections) + len(
        json.loads((EVALS / "graders-big.json").read_text(encoding="utf-8"))["_corrections"])
    sealed_fix = next(c for c in corrections if isinstance(c, dict) and c.get("n") == 20)
    effect = re.search(r"SEALED-A5 (\d+)/(\d+) -> (\d+)/(\d+)", sealed_fix["effect"])
    if not effect or tuple(map(int, effect.groups()[2:])) != sd5["unambiguous_all"]:
        raise SystemExit("Sealed correction history no longer matches the report")
    sealed_pre_fix = f"{effect[1]}/{effect[2]}"
    handwritten_n = len(json.loads((EVALS / "scenarios.json").read_text(encoding="utf-8"))["scenarios"])
    generated_n = len(json.loads((EVALS / f"{SET}.json").read_text(encoding="utf-8"))["scenarios"])
    paired_p = "<0.001" if paired["p"] < 0.001 else f"={paired['p']:.3f}"

    md = f"""---
title: "Budget Front Desk"
subtitle: "An Agentplace Luna agent: failures, changes, and the rerun"
author: "Arjhine A. Ty · Prepared for Agentplace · {date.today().isoformat()}"
---

# What I built and tested

A public Luna front desk for **Budget Heating, Cooling & Plumbing**, built from
its public website. It answers price and service-area questions, triages
emergencies, and routes to a booking page or phone. The company is not involved;
the agent has no connection to its calendar or CRM.

The corpus retains **{handwritten_n} hand-written and {generated_n} generated single-turn scenarios**,
**{mt0['scripts']} scripts of three turns each**, and **{sd0['all'][1]} sealed validation scenarios**.
Tests include missing details, unknown prices, off-topic requests and pushback.
The main single-turn comparison and multi-turn scripts run three trials each.
A pass requires the specified facts and next step, with no forbidden claim.
“All-three pass” means the scenario passed every trial.

# Changes made, including the regressions

**A0 is the baseline; A5 is the selected instruction set.** A generic next-step
instruction first produced “reply in chat” instead of the phone number. Requiring
an **external action** repaired that, but introduced scheduling and off-task
regressions. Asking when the office reopens then triggered a clock check that
contradicted a Sunday-night emergency. That edit was reverted. A5 retained the
external action and forbade clock-based contradictions of the customer's stated time.

# Before and after on the shared development set

> **All-three passes: {paired['totals']['BIG-A0']}/{paired['n']} → {paired['totals']['A5']}/{paired['n']}.**
> This is **in-sample**: the scenarios guided instruction and grader iteration.

| Requirement group | Baseline | A5 instructions |
|---|---:|---:|
{lane_table}

There are {paired['gained']} gains and {paired['lost']} loss (paired McNemar p{paired_p}).
Most gains now state the $99 diagnostic or coverage rule. One sewage reply loses
avoid-contact advice. The external-next-step version had reached
{paired['totals']['BIG-A2']}/{paired['n']}; A5 recovered scheduling and off-task losses.
This sequential comparison is not a controlled ablation.

# Validation and remaining work

The positive development result is not confirmed on the separate validation
checks. These scores are automated rubric outcomes, not independently established
customer success rates.

## Multi-turn: a positive but uncertain difference

Across {mt0['scripts']} scripts with three trials each, baseline passes
**{mt0['passed']}/{mt0['n']}** and A5 **{mt5['passed']}/{mt5['n']}**; scripts passing all trials move
from {mt0['strict']}/{mt0['scripts']} to {mt5['strict']}/{mt5['scripts']}.
There are {mt_gained} gains and {mt_lost} losses (nominal paired p={exact_p(mt_gained, mt_lost):.3f},
not statistically significant).
Trials repeat scripts, so they are not {mt0['n']} independent customers.
Observed gains are concentrated in arithmetic and pushback, not a demonstrated
effect of the instructions. One gain is the baseline's template-placeholder failure.

## Sealed: no demonstrated advantage

The {sd0['all'][1]} scenarios, each three turns long, were authored by a different model.
Scenario rubrics were frozen before replies. Before the render exclusion, totals are
**{fraction(sd0['all'])} baseline and {fraction(sd5['all'])} A5**;
the subset not flagged as ambiguous is {fraction(sd0['unambiguous_all'])} versus
{fraction(sd5['unambiguous_all'])}.

A post-run mechanical amount-check fix, applied to both arms, moved A5 from
{sealed_pre_fix} to {fraction(sd5['unambiguous_all'])}; baseline was unchanged.
Separately, cleaning excluded one A5 pass containing an appended render error,
leaving **{fraction(sd5['kept'])} overall and {fraction(sd5['clean'])} on the unambiguous subset**.
Baseline had no exclusion. The small set does not establish equivalence or regression.

## Remaining failures and grading limits

- **Scheduling: {lanes['scheduling']['A5']}/{lanes['scheduling']['n']} all-three passes.**
  Some replies omit the required hours or Saturday surcharge.
  **Handoff: {lanes['handoff']['A5']}/{lanes['handoff']['n']}.** A multi-unit outage misses escalation.
- Six membership-script conversations fail in **both arms** on benefits omitted
  from v1; some also omit required pricing. These are mixed authoring and agent gaps.
- There are **{correction_count} logged grader corrections**: 20 from transcripts, one from
  a positive control. A correct overnight refusal still fails a wording-sensitive
  check; its recorded score is retained. Human calibration reused the same
  transcripts after a rule clarification, so it is not fresh-sample validation.

## Build provenance and evidence

Single-turn files label the original project `jojuduewx7ud`. Validation compares
the A5 rebuild `cgiefgaebmgh` with a **separate baseline rebuild**,
`guikfrraxzk5`; build differences are an additional confound. The evaluated brief
used 24 sourced fields. The current ledger has 25; its corrected v2 is not evaluated.
Two builds also answered membership questions differently; the cause remains unknown.

All recorded runs are retained. The 20 sealed scenarios supplement, rather than
replace, the larger development sets.

All test sets, runs, instruction history and findings:
[github.com/arjhinety/budget-front-desk](https://github.com/arjhinety/budget-front-desk).
The published agent link is supplied separately.
"""
    (OUT / "report.md").write_text(md, encoding="utf-8")
    html = subprocess.run(["pandoc", str(OUT / "report.md"), "-o", str(OUT / "report.html"),
                           "--standalone", "--metadata", "pagetitle=Budget Front Desk"],
                          capture_output=True, text=True)
    if html.returncode:
        raise SystemExit(html.stderr[:1000])
    html_path = OUT / "report.html"
    document = html_path.read_text(encoding="utf-8")
    print_style = "<style>\n" + (ROOT / "build/report.css").read_text(encoding="utf-8") + "\n</style>"
    html_path.write_text(document.replace("</head>", print_style + "</head>"),
                         encoding="utf-8")
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    windows_chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if not chrome and windows_chrome.exists():
        chrome = str(windows_chrome)
    if not chrome:
        raise SystemExit("HTML generated; install Chrome/Chromium to produce the PDF.")
    with tempfile.TemporaryDirectory(prefix="agentplace-report-", ignore_cleanup_errors=True) as profile:
        candidate = Path(profile) / "report.pdf"
        subprocess.run([chrome, "--headless", "--disable-gpu",
                        f"--user-data-dir={profile}", "--no-pdf-header-footer",
                        f"--print-to-pdf={candidate}",
                        html_path.resolve().as_uri()],
                       capture_output=True, text=True, check=True, timeout=120)
        # Windows launchers may return before the renderer finishes writing.
        # Publish only a fresh, complete PDF, never the previous report.
        deadline = time.monotonic() + 60
        previous_size = -1
        stable = 0
        while time.monotonic() < deadline:
            if candidate.exists():
                data = candidate.read_bytes()
                stable = stable + 1 if len(data) == previous_size else 0
                previous_size = len(data)
                if data.startswith(b"%PDF") and b"%%EOF" in data[-1024:] and stable >= 2:
                    shutil.copyfile(candidate, OUT / "report.pdf")
                    break
            time.sleep(0.5)
        else:
            raise SystemExit("Chromium did not finish a fresh PDF; old report was not replaced.")
    print("report.md, report.html and report.pdf generated from recorded results")
    print(f"multi-turn: A0 {mt0['passed']}/{mt0['n']}; A5 {mt5['passed']}/{mt5['n']}")
    print(f"sealed exclusions: A0 {sd0['excluded']}; A5 {sd5['excluded']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
