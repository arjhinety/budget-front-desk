#!/usr/bin/env python3
"""
Have a model that is not the grader author write the sealed-set scenarios.

The whole point of the sealed set is that its scenarios were not written by the
person who wrote the graders. This script asks Mistral for 20 new customer
messages in the six behavioural families, then records the model, the request, and
the response hash so the authorship is checkable.

It deliberately does NOT write graders. Those are written afterwards, from the
spec, by the grader author, before any reply exists — which is the only thing that
makes the later agreement score mean anything.

  python datasets/gen_sealed_scenarios.py --n 20 --model mistral-large-4-0

Requires MISTRAL_API_KEY. Writes datasets/sealed/scenarios-sealed.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "datasets" / "sealed"
API = "https://api.mistral.ai/v1/chat/completions"

FAMILIES = [
    ("self-correction", "the customer states one thing, then corrects it"),
    ("memory", "the customer gives a fact early and needs it used later without being asked again"),
    ("change-of-mind", "the customer switches service or day partway through"),
    ("pushback", "the customer pushes twice against a published rule"),
    ("recovery", "the opening message is ambiguous and the customer clarifies later"),
    ("arithmetic", "the customer ends up asking for a total built from two published prices"),
]

RULES = """The business publishes exactly these facts and nothing else:

HOURS: Monday-Friday 8:00 a.m. to 7:00 p.m.; Saturday 9:00 a.m. to 5:00 p.m.; closed Sunday. No after-hours,
overnight or 24/7 service exists. Saturday appointments add $50.

PRICES: HVAC diagnostic service call $99 per visit; water-heater diagnostic service call $99 per visit;
one-time HVAC cleaning and maintenance $150 per system; complete HVAC system refresh and performance report
$489 per system; water-heater maintenance and flush $375; tankless water-heater flush $475; savings club
membership $250 per year (includes annual cleaning and inspection, waived dispatch fees, priority
scheduling, 15% off repairs, 5% off new equipment); free written replacement estimates for HVAC, water
heaters and indoor-air upgrades.

COVERAGE: water-heater work is offered anywhere in Missouri; diagnostic visits are sold only in St. Charles,
St. Louis, Lincoln, Warren and Jefferson counties; other plumbing-equipment estimates stop at the St.
Charles County line.

NOT PUBLISHED, so an agent must not state them: a street address, a licence number, per-repair prices, a
cancellation policy, any after-hours service, any discount or promo code, any price match.

The agent's job: work out which lane the customer is in (emergency, diagnostic, free estimate), quote only
published prices, answer coverage correctly for the job type, and end with a next step the customer can act
on - call or text (636) 887-2800, open the booking page, or pay the diagnostic fee."""

PROMPT = """You are writing test scenarios for a customer-service AI agent that serves a real home-services
company (heating, cooling, plumbing) in Missouri.

{rules}

Write {n} scenarios as a JSON array. Each element must be an object with exactly these keys:

  "id":        a short unique id, starting with "SD-"
  "family":    one of {families}
  "turns":     an array of 3 customer messages, in the customer's own voice, lowercase, informal,
               with realistic typos and no punctuation discipline
  "tests":     one sentence saying what the scenario is checking

Requirements:
- Every scenario has exactly 3 customer turns.
- The customer messages must make sense whatever the agent replied, because the customer volunteers
  information rather than reacting to specific wording.
- Cover all six families, spread as evenly as {n} allows.
- Do not mention the agent, the grader, or the test. These are customer messages.
- Vary the county, the service, the day and the phrasing across scenarios. Do not reuse a sentence frame.
- At least three scenarios must involve an address outside the five counties.
- At least two must involve a total the customer asks for that is built from two published prices.

Return a JSON object with exactly one key, "scenarios", whose value is the array. No prose."""


def call(prompt: str, model: str) -> tuple[str, dict]:
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise SystemExit("MISTRAL_API_KEY is not set")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32000,   # this model spends most of the budget on reasoning tokens
        "temperature": 0.7,
        # without this the model returns JSON with trailing commas and the parse fails
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(API, data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Mistral HTTP {e.code}: {e.read()[:400].decode(errors='replace')}")

    choice = d["choices"][0]
    if choice.get("finish_reason") == "length":
        u = d.get("usage", {}).get("completion_tokens_details", {})
        print(f"warning: hit the token ceiling; reasoning used {u.get('reasoning_tokens')} tokens")
    content = choice["message"]["content"]
    if isinstance(content, list):
        text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    else:
        text = content
    return text, {"model": d.get("model"), "usage": d.get("usage")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--model", default="mistral-large-4-0")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    prompt = PROMPT.format(rules=RULES, n=args.n,
                           families=", ".join(f'"{f}"' for f, _ in FAMILIES))
    (OUT / "request.txt").write_text(prompt, encoding="utf-8")

    text, meta = call(prompt, args.model)
    # save first, parse second: a parse failure must never lose the response
    (OUT / "raw-response.txt").write_text(text, encoding="utf-8")

    import re
    blob = text.strip()
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError as e:
        repaired = re.sub(r",\s*([}\]])", r"\1", blob)
        try:
            parsed = json.loads(repaired)
            print(f"repaired malformed JSON ({e.msg} at char {e.pos})")
        except json.JSONDecodeError as e2:
            raise SystemExit(f"unparseable response ({e2}); raw text at datasets/sealed/raw-response.txt")

    if isinstance(parsed, dict):
        scenarios = parsed.get("scenarios") or next(
            (v for v in parsed.values() if isinstance(v, list)), [])
    else:
        scenarios = parsed
    if not scenarios:
        raise SystemExit("response parsed but held no scenarios; see datasets/sealed/raw-response.txt")

    bad = [s for s in scenarios if not (isinstance(s.get("turns"), list) and len(s["turns"]) == 3)]
    if bad:
        print(f"warning: {len(bad)} scenarios do not have exactly 3 turns: {[s.get('id') for s in bad]}")

    payload = {
        "schema": "agentplace-sealed-scenarios-v1",
        "authored_by": f"{meta['model']} via the Mistral API",
        "authored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "not_authored_by": "the grader author, deliberately",
        "request_sha256": hashlib.sha256((OUT / "request.txt").read_bytes()).hexdigest(),
        "request_sha256_note": "hash of request.txt as written to disk, not of the in-memory string",
        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "usage": meta.get("usage"),
        "scenarios": scenarios,
    }
    (OUT / "scenarios-sealed.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    from collections import Counter
    print(f"{len(scenarios)} scenarios -> datasets/sealed/scenarios-sealed.json")
    print("by family:", dict(Counter(s.get("family") for s in scenarios)))
    print(f"request sha256 {payload['request_sha256'][:16]}  response sha256 {payload['response_sha256'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
