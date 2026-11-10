#!/usr/bin/env python3
"""Build the two-page application summary from the recorded results."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
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

A live Luna front desk for Budget Heating, Cooling & Plumbing, built from a
**24-field v1 brief** with page-and-line provenance. The current ledger has 25
fields after adding the omitted membership benefits; v2 has not been evaluated.
The agent triages requests, uses the catalogue, collects intake and routes to a
booking page or phone. All large test sets and recorded runs are retained.

# Before and after

| | A0 baseline | A5 instructions |
|---|---:|---:|
| single-turn pass@1, respective 53/55 scenarios | {a0['passed']}/{a0['trials']} ({a0['passed']/a0['trials']:.1%}) | {a5['passed']}/{a5['trials']} ({a5['passed']/a5['trials']:.1%}) |
| strict pass³, shared 53 scenarios | {a0['strict']}/53 | **43/53** |
| single-turn integrity-gate failures | {a0['gate']}/53 | {a5['gate']}/55 |
| multi-turn, 54 conversations | {mt0['passed']}/54 ({mt0['passed']/54:.0%}) | **{mt5['passed']}/54 ({mt5['passed']/54:.0%})** |
| multi-turn scripts passing all trials | {mt0['strict']}/18 | **{mt5['strict']}/18** |

The paired strict-pass result favours A5 on the development set (b=18, c=1,
p<0.001). Pass@1 uses different denominators and is descriptive. The original
single-turn metadata names project `jojuduewx7ud`; the linked A5 rebuild,
`cgiefgaebmgh`, has its own multi-turn and sealed measurements. The multi-turn baseline
now exists: A0 is 36/54 and A5 is 41/54. A5 gains 7 conversations and loses 2;
McNemar p=0.180. The measured direction is positive, but the multi-turn delta is not
statistically settled. These are three trials of 18 scripts, not 54 independent
customers; one gain is A0's unfilled-placeholder integrity failure, so the clean
behavioural signal is narrower than 7 versus 2.

# What changed

A1's generic route instruction permitted \"reply in chat\". A2 required an external
destination. A3's hours instruction prompted a clock-based contradiction; A5
kept the customer's stated time and forbade clock checks. The arm history retains
the regressions as well as the selected changes.

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

- The single-turn comparison is in-sample. There are **21 logged corrections**:
  20 from transcript inspection and one from a positive control. Corrections 20
  and 21 repaired amount checks that rejected valid arithmetic, including
  $99 + $150 + $50 = $299. No frozen scenario rubric was changed.
- Six failing A5 conversations include savings-club expectations absent from the
  brief; some also miss a required diagnostic price. The overnight example in
  MT-P02 declines service but fails a wording-sensitive regex. Scores are unchanged.
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
    html_path = OUT / "report.html"
    document = html_path.read_text(encoding="utf-8")
    print_style = """<style>
@page { size: A4; margin: 14mm; }
@media print {
  body { max-width: none; margin: 0; padding: 0; font-size: 11pt; line-height: 1.4; }
  h1 { font-size: 14pt; margin-top: 14pt; margin-bottom: 6pt; }
  header h1 { font-size: 21pt; }
  table { font-size: 9pt; width: 100%; }
  tr, h1, h2 { break-inside: avoid; }
  h1, h2 { break-after: avoid; }
  #the-check-i-could-not-tune-against { break-before: page; }
}
</style>"""
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
