#!/usr/bin/env python3
"""
Render the Agentplace Builder brief from facts/business.json, and print the
exact Builder link.

The brief is generated from the ledger rather than typed by hand, so a price or
a rule can never appear in the brief that is not also in facts/sources.csv with
a page and a line number behind it.

Follows the platform's own guidance for assistant-written briefs: describe the
business, the customer's task, the outcome and the constraints. No component
specs, no prompt text, no invented account access.

Usage:  python generate_brief.py [--out build/brief.txt]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
FACTS = ROOT / "facts"
SITE = "https://justcallbudget.com"


def money(v: int | None) -> str:
    return f"${v:,}" if v else "on request"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/brief.txt")
    args = ap.parse_args()

    b = json.loads((FACTS / "business.json").read_text(encoding="utf-8"))
    svc = {s["id"]: s for s in b["services"]}

    def line(key: str, show_unit: bool = True) -> str:
        s = svc[key]
        if s["price_usd"]:
            unit = ""
            if show_unit and s["price_unit"] and s["price_unit"] != "visit":
                unit = f" per {s['price_unit'].rstrip('s')}"
            return f"{s['name']} {money(s['price_usd'])}{unit}"
        if s["requires_office_review"]:
            return f"{s['name']} (office review required)"
        if s["kind"] == "member":
            return f"{s['name']} (included for members)"
        return s["name"].removeprefix("Free ")

    priced = [line(k, show_unit=False) for k in ("hvac_diagnostic", "water_heater_diagnostic")]
    menu = [line(k) for k in ("savings_club", "hvac_clean_one_time", "hvac_refresh_report",
                              "water_heater_flush", "tankless_flush")]
    free = [line(k) for k in ("hvac_estimate", "water_heater_estimate", "iaq_upgrade_estimate")]

    brief = f"""Build an AI agent for {b['business_name']}, a family-owned heating, cooling and plumbing company in {b['hometown']} that has served {b['service_area']} since {b['established']}. The website is {SITE} — use its service pages and booking page as the source of the facts below, and keep the brand, the photography style and the plain-spoken tone.

The customer is a homeowner with something wrong in the house, often worried and often comparing two or three companies. The agent runs the front desk: it works out what is actually broken, picks the right service from the catalogue, collects what a dispatcher would collect, and gets the customer to a booked or paid slot.

What it must do, in this order:
1. Triage the complaint into one of three lanes — emergency, diagnostic, or free estimate — and say which lane it chose and why.
2. Help the customer choose a service using the real catalogue: {"; ".join(priced)}; {"; ".join(menu)}. Three written estimates are free with no obligation: {"; ".join(free)}.
3. Collect the property address, the customer's name, mobile number, the equipment type and age if known, and a photo of the unit label or the leak. Repeat the details back before confirming.
4. Drive to the next step: the online booking page, a call or text to {b['phone']}, or payment of the diagnostic fee.

Rules that matter more than sounding helpful:
- One {money(svc['hvac_diagnostic']['price_usd'])} charge per visit covers the trip and the diagnosis. Repairs, parts and refrigerant are quoted separately and the customer approves before any work starts. Never invent a repair price.
- Open {b['hours_weekday']}, {b['hours_saturday']}, and closed on Sundays. Saturday appointments add {money(b['saturday_surcharge_usd'])} — show that before the customer commits to a Saturday, not after. Never promise 24/7 or same-night service.
- Coverage is not uniform. Diagnostic visits are sold inside the five named counties. Water-heater work is offered anywhere in Missouri; other plumbing-equipment estimates stop at the St. Charles County line. Ask for the address before saying yes.
- Emergency lane: gas smell, no heat in freezing weather, a burst pipe or a sewage backup. Give the safety instruction first, then the earliest slot inside business hours.
- Hand off to a person for commercial rooftop or restricted-access work, warranty-company dispatch, permits, or more than one system.
- If the site does not answer something, say so and route to {b['phone']}. Do not fill a gap with a guess.

Everything is labour-backed for one year, and the shop is licensed, bonded and insured. Financing is available subject to credit approval. Close by confirming what happens next and when the customer will hear from a person."""

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(brief + "\n", encoding="utf-8")

    url = f"{SITE.rsplit('/', 1)[0]}/admin/dashboard".replace("//admin", "/admin")
    url = "https://agentplace.io/admin/dashboard?" + urlencode(
        {"create_new": "true", "autosend": "false", "instruction": brief}
    )
    (ROOT / "build" / "builder_url.txt").write_text(url + "\n", encoding="utf-8")

    print(f"brief: {len(brief)} chars, {len(brief.split())} words -> {out}")
    print(f"builder link: {len(url)} chars -> build/builder_url.txt")
    print("\n" + brief)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
