#!/usr/bin/env python3
"""Read-only historical capture audit. Never calls an agent or changes a score."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from datetime import datetime
from pathlib import Path

from grade import agent_text

ROOT = Path(__file__).resolve().parent.parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root: Path = ROOT) -> dict:
    path = root / "evals/results/A5.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data["records"]
    ordered = sorted(records, key=lambda r: datetime.fromisoformat(r["at"].replace("Z", "+00:00")))
    gaps = [(datetime.fromisoformat(ordered[i]["at"].replace("Z", "+00:00")) -
             datetime.fromisoformat(ordered[i - 1]["at"].replace("Z", "+00:00"))).total_seconds()
            for i in range(1, len(ordered))]
    split = max(range(len(gaps)), key=gaps.__getitem__) + 1 if gaps else len(ordered)
    blocks = []
    for name, rows in (("before_largest_gap", ordered[:split]), ("after_largest_gap", ordered[split:])):
        if not rows:
            continue
        blocks.append({
            "label": name, "records": len(rows), "first_at": rows[0]["at"], "last_at": rows[-1]["at"],
            "next_step_heading_count": sum(bool(re.search(r"^Next step\s*$", r["thread"], re.I | re.M)) for r in rows),
            "median_captured_thread_chars": statistics.median(len(r["thread"]) for r in rows),
            "definition": "Heading is a whole line matching /^Next step\\s*$/im; lengths include captured UI text.",
        })
    graders_path = root / "evals/graders-big.json"
    graders = json.loads(graders_path.read_text(encoding="utf-8"))["scenarios"]
    cases = []
    for sid in ("G-X-SEWAGE-THISMO", "G-D-ILLINOIS"):
        rule = graders[sid]
        evidence = []
        for rec in records:
            if rec["id"] != sid:
                continue
            text = agent_text(rec["thread"], rec["customer"])
            excerpts = []
            for phrase in ("Keep people and pets", "Keep everyone", "confirm coverage", "outside", "Alton"):
                match = re.search(re.escape(phrase), text, re.I)
                if match:
                    excerpts.append(text[max(0, match.start() - 25):match.start() + 240])
            evidence.append({"trial": rec["trial"], "excerpts": excerpts,
                             "must_matches": [{"pattern": p, "matches": bool(re.search(p, text, re.I))}
                                              for p in rule.get("must", [])]})
        cases.append({"id": sid, "rules_as_recorded": rule, "evidence": evidence,
                      "status": "semantic review flag; no automatic relabelling"})
    return {
        "schema_version": "agentplace.history-audit.v1",
        "source": "evals/results/A5.json", "source_sha256": digest(path),
        "graders_sha256": digest(graders_path), "recorded_agent_label": data.get("agent"),
        "largest_gap_seconds": max(gaps) if gaps else None, "blocks": blocks,
        "per_record_provenance_missing": {
            field: sum(not r.get(field) for r in records)
            for field in ("project_id", "target_url", "config_sha256", "harness_commit")},
        "interpretation": "The blocks differ observationally. Their build identities and the cause of the difference cannot be recovered from formatting alone.",
        "review_cases": cases,
        "policy_conflict": {
            "v1_brief": "build/brief.txt:14",
            "statement": "The brief restricts diagnostic visits to five counties while broadening water-heater work. Resolve the effective job-specific rule before treating an unconditional answer as ground truth.",
        },
        "historical_scores_changed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, help="optional new JSON file; existing files are never overwritten")
    args = ap.parse_args()
    if args.out and args.out.exists():
        ap.error(f"refusing to overwrite {args.out}")
    result = audit()
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(text)
        print(args.out)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
