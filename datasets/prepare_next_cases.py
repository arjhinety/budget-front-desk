#!/usr/bin/env python3
"""Prepare/validate future case authoring locally. This script makes no API calls."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ledger_fields(root: Path = ROOT) -> set[str]:
    with (root / "facts/sources.csv").open(encoding="utf-8", newline="") as stream:
        return {row["field"] for row in csv.DictReader(stream)}


def packet(root: Path = ROOT) -> dict:
    sources = {"guide": "evals/human/GUIDE.md", "protocol": "evals/next_run/PROTOCOL.md",
               "v1_brief": "build/brief.txt", "candidate_edit": "build/next-run/instructions-A6-candidate.patch",
               "ledger": "facts/sources.csv"}
    return {
        "schema_version": "agentplace.case-authoring-request.v1",
        "status": "prepared_not_sent_not_frozen",
        "provider_hint": {"model": "mistral-large-4-0", "max_tokens": 32000,
                          "response_format": {"type": "json_object"}},
        "source_hashes": {name: {"file": path, "sha256": sha(root / path)} for name, path in sources.items()},
        "required_before_authoring": ["human calibration reviewed", "effective input verified or its limits explicitly accepted", "single intervention finalised"],
        "instructions": (
            "Return one JSON object with schema_version 'agentplace.fresh-cases.v1', author, and cases. "
            "Do not return agent replies or claim any case has been tested. Author 48 new single-turn customer scenarios: "
            "24 targeted scheduling-disclosure cases (3 trials each) and 24 regression tripwires (1 trial each). "
            "Tripwires cover safety, prices, known/unclear coverage, human handoff, unknown information and off-topic pushback. "
            "The sealed 20 is supplemental; do not copy historical test wording or inspect historical agent replies. "
            "Each case has id F-001 through F-048, template_id, cohort targeted/tripwire, trials, customer, "
            "required_fact_ids, expected_behavior, and allowed_clarifications. required_fact_ids must be selected "
            "from the ledger field list, not invented. Use at least eight semantic template groups; paraphrases, "
            "county swaps and date swaps of one decision belong in the SAME template group. "
            "Customer times are explicit premises, not the current clock. Do not infer real appointment availability. "
            "Use no real customer personal information. Do not demand v2 membership benefits from v1; safe refusal "
            "or office confirmation is allowed. The v1 water-heater diagnostic boundary is ambiguous, so do not "
            "require one unconditional resolution. Clarifying-first replies can be appropriate. "
            "New scheduling-disclosure expectations are prospective and not retroactive corrections to old scores. "
            "Expected behaviour describes semantic requirements, not mandatory vocabulary. "
            "Do not assert statistical power from this count; it is a diagnostic pilot."
        ),
        "ledger_field_ids": sorted(ledger_fields(root)),
        "inputs": {name: (root / path).read_text(encoding="utf-8") for name, path in sources.items()},
        "api_called": False,
    }


def validate(data: dict, allowed_fields: set[str]) -> dict:
    if not isinstance(data, dict):
        raise ValueError("authoring response must be one JSON object")
    if data.get("schema_version") != "agentplace.fresh-cases.v1":
        raise ValueError("wrong fresh-case schema_version")
    if not isinstance(data.get("author"), str) or not data["author"].strip():
        raise ValueError("record the actual author/model, not an assumed independent author")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) != 48:
        raise ValueError("expected exactly 48 cases")
    ids, texts, templates = set(), set(), set()
    counts = {"targeted": 0, "tripwire": 0}
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each case must be a JSON object")
        sid = case.get("id", "")
        if not isinstance(sid, str) or not re.fullmatch(r"F-\d{3}", sid) or sid in ids:
            raise ValueError(f"invalid or duplicate case id: {sid!r}")
        ids.add(sid)
        cohort = case.get("cohort")
        if not isinstance(cohort, str) or cohort not in counts:
            raise ValueError(f"{sid}: invalid cohort")
        if type(case.get("trials")) is not int or case["trials"] != (3 if cohort == "targeted" else 1):
            raise ValueError(f"{sid}: incorrect planned repeat count")
        counts[cohort] += 1
        customer = case.get("customer", "")
        norm = " ".join(customer.casefold().split()) if isinstance(customer, str) else ""
        if not norm or norm in texts:
            raise ValueError(f"{sid}: empty or exact-duplicate customer message")
        texts.add(norm)
        template = case.get("template_id")
        if not isinstance(template, str) or not template.strip():
            raise ValueError(f"{sid}: missing semantic template group")
        templates.add(template)
        facts = case.get("required_fact_ids")
        if not isinstance(facts, list) or not facts or any(not isinstance(f, str) or f not in allowed_fields for f in facts):
            raise ValueError(f"{sid}: expected facts are missing or absent from ledger")
        if not isinstance(case.get("expected_behavior"), str) or not case["expected_behavior"].strip():
            raise ValueError(f"{sid}: missing semantic expected behaviour")
        if not isinstance(case.get("allowed_clarifications"), list):
            raise ValueError(f"{sid}: allowed_clarifications must be explicit")
    if ids != {f"F-{i:03d}" for i in range(1, 49)}:
        raise ValueError("case ids must be F-001 through F-048")
    if counts != {"targeted": 24, "tripwire": 24}:
        raise ValueError("expected 24 targeted cases and 24 tripwires")
    if len(templates) < 8:
        raise ValueError("fewer than eight declared semantic template groups")
    return {"cases": 48, "counts": counts, "template_groups": len(templates),
            "planned_conversations_per_arm_phase": sum(c["trials"] for c in cases),
            "status": "structurally_valid_not_semantically_approved_not_frozen",
            "remaining_review": ["semantic grouping", "source/effective-input alignment", "grader/control checks", "independent review", "pre-reply freeze"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true", help="prepare authoring request locally, no API call")
    group.add_argument("--validate", type=Path, metavar="CASES.json", help="validate a supplied authoring response")
    ap.add_argument("--out", type=Path, help="new output file, never overwritten")
    args = ap.parse_args()
    if args.out and args.out.exists():
        ap.error(f"refusing to overwrite {args.out}")
    try:
        result = packet() if args.prepare else validate(json.loads(args.validate.read_text(encoding="utf-8")), ledger_fields())
    except (ValueError, OSError, KeyError) as exc:
        ap.error(str(exc))
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
