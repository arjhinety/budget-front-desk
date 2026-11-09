#!/usr/bin/env python3
"""
Turn the captured pages into a facts ledger where every number has a receipt.

Two rules, both enforced by failing the build rather than warning:

  1. A field is written only if its exact evidence string is found in a captured
     page. If the site changes, the build stops instead of shipping a stale price.
  2. A field is rejected if its evidence matches a known placeholder pattern
     (template demo text, fake phone numbers, "mysite.com", "Location 1").
     A placeholder that reaches a customer-facing agent is worse than a gap.

Outputs
  facts/business.json     structured facts for the brief generator
  facts/sources.csv       one row per field: value, source page, evidence line, status
  facts/parameters.csv    every judgement call, with its reason

Usage:  python build_facts.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
FACTS = ROOT / "facts"

PLACEHOLDERS = [
    r"\bmysite\.com\b", r"\b123-456-7890\b", r"\b500 Terry Francine\b",
    r"\bLocation 1\b", r"\blorem ipsum\b", r"\bexample\.com\b", r"\byour-domain\b",
]


def placeholder_hit(text: str) -> str | None:
    for pat in PLACEHOLDERS:
        if re.search(pat, text, re.I):
            return pat
    return None


def load(slug: str) -> list[str]:
    path = RAW / f"{slug}.txt"
    if not path.exists():
        raise SystemExit(f"missing capture: {path} — run scrape.py first")
    return path.read_text(encoding="utf-8").splitlines()


def find(slug: str, pattern: str, field: str) -> tuple[str, int, str]:
    """Return (captured value, 1-based line number, full line) or fail the build."""
    lines = load(slug)
    rx = re.compile(pattern)
    for n, line in enumerate(lines, 1):
        m = rx.search(line)
        if m:
            hit = placeholder_hit(line)
            if hit:
                raise SystemExit(
                    f"{field}: evidence in {slug}.txt:{n} matches placeholder /{hit}/ — refusing to use it"
                )
            value = m.group(1) if m.groups() else m.group(0)
            return value.strip(), n, line.strip()
    raise SystemExit(f"{field}: no line in {slug}.txt matches /{pattern}/ — site changed, rebuild the ledger")


# ---------------------------------------------------------------- service catalogue
#
# Rows exactly as the booking page presents them, with the price token the page
# prints beside each one. Exact-string verification: a renamed row or a changed
# price fails the build instead of silently dropping out of the catalogue.
CATALOGUE = [
    ("hvac_estimate",             "Free HVAC Equipment Estimate",                   "free",   "Free", None),
    ("water_heater_estimate",     "Free Water Heater & Plumbing Equipment Estimate", "free",   "Free", None),
    ("iaq_upgrade_estimate",      "Indoor Air / HVAC Upgrade Estimate",              "free",   "Free", None),
    ("hvac_diagnostic",           "HVAC Diagnostic Service Call",                    "paid",   "$99", "visit"),
    ("water_heater_diagnostic",   "Water Heater Diagnostic Service Call",            "paid",   "$99", "visit"),
    ("savings_club_visit",        "Budget Savings Club Maintenance Visit",           "member", "Included for active members", None),
    ("savings_club",              "Budget Savings Club Membership",                  "paid",   "$250/yr", "year"),
    ("hvac_clean_one_time",       "One-Time HVAC Cleaning and Maintenance",          "paid",   "$150 per system", "system"),
    ("hvac_refresh_report",       "Complete HVAC System Refresh and Performance Report", "paid", "$489 per system", "system"),
    ("water_heater_flush",        "Water Heater Maintenance and Flush",              "paid",   "$375", "flush"),
    ("tankless_flush",            "Tankless Water Heater Maintenance and Flush",     "paid",   "$475", "flush"),
    ("special_access",            "Special Access / Light Commercial Service Request","review", "Requires office review", None),
]


def parse_catalogue() -> tuple[list[dict], str, int]:
    text = (RAW / "book-online.txt").read_text(encoding="utf-8")
    rows, failures = [], []
    for key, name, kind, token, unit in CATALOGUE:
        i = text.find(name)
        if i < 0:
            failures.append(f"{name}: row not found")
            continue
        after = text[i + len(name): i + len(name) + 260]
        if token not in after:
            failures.append(f"{name}: expected {token!r} within the row, found {after[:80]!r}")
            continue
        price = None
        m = re.search(r"\$([0-9][0-9,]*)", token)
        if m:
            price = int(m.group(1).replace(",", ""))
        rows.append({
            "id": key, "name": name, "kind": kind,
            "price_usd": price, "price_unit": unit,
            "requires_office_review": kind == "review",
            "evidence": after.strip()[:180],
            "status": "REAL",
        })
    if failures:
        raise SystemExit("catalogue no longer matches the page:\n  " + "\n  ".join(failures))
    return rows, text, text.find("Please select the service")


SCALARS = [
    ("business_name", "about-us", r"(Budget Heating, Cooling & Plumbing) is a family-owned", "REAL",
     "full trading name as the business writes it"),
    ("established", "about-us", r"since (\d{4})", "REAL", "year the shop says it started"),
    ("phone", "contact-us", r"(\(\d{3}\) \d{3}-\d{4})", "REAL",
     "same number on every captured page; no competing number found"),
    ("hours_weekday", "home", r"(Mon–Fri 8–7)", "REAL", "header strip and footer agree"),
    ("hours_saturday", "home", r"(Sat 9–5)", "REAL", "header strip and footer agree"),
    ("closed_day", "book-online", r"(Closed Sundays)", "REAL", "only the booking page says this outright"),
    ("saturday_surcharge_usd", "book-online", r"Saturdays add \$(\d+)", "REAL",
     "printed on the booking form, not in the service catalogue"),
    ("service_area", "home", r"Serving (St\. Charles, St\. Louis, Lincoln, Warren & Jefferson Counties)", "REAL",
     "five named Missouri counties; no ZIP list or radius published"),
    ("hometown", "about-us", r"company in (St\. Peters, Missouri)", "REAL",
     "base town only — no walk-in address published"),
    ("labour_warranty", "about-us", r"(backed for a full year)", "REAL",
     "one year on labour and workmanship; parts carry manufacturer cover"),
    ("emergency_scope", "emergency-plumbing", r"urgent, (same-day response)", "REAL",
     "emergencies move to the front of the line inside business hours"),
    ("financing", "financing", r"(0% APR options for qualified applicants)", "REAL",
     "Wisetack and Hearth; subject to credit approval"),
    ("savings_club_benefits", "book-online",
     r"Annual membership includes (.+?)\.", "REAL",
     "what the membership actually includes; omitted from the first ledger, which is why one build "
     "answered the question and a later rebuild declined to"),
]


def main() -> int:
    provenance = json.loads((FACTS / "provenance.json").read_text(encoding="utf-8"))
    urls = {p["slug"]: p["url"] for p in provenance["pages"]}

    rows, business, contradictions, not_stated = [], {}, [], []

    for field, slug, pattern, status, note in SCALARS:
        value, lineno, line = find(slug, pattern, field)
        business[field] = int(value) if value.isdigit() else value
        rows.append({
            "field": field, "value": value, "status": status,
            "source_page": urls[slug], "source_file": f"raw/{slug}.txt:{lineno}",
            "evidence": line[:300], "note": note,
        })

    services, book_text, _ = parse_catalogue()
    for svc in services:
        rows.append({
            "field": f"service.{svc['id']}.price",
            "value": f"${svc['price_usd']}" if svc["price_usd"] else svc["kind"].upper(),
            "status": svc["status"],
            "source_page": urls["book-online"], "source_file": "raw/book-online.txt",
            "evidence": svc["evidence"], "note": f"unit={svc['price_unit']}; kind={svc['kind']}",
        })

    # ---------------------------------------------------------- contradiction checks

    if "dispatch fee" in book_text:
        contradictions.append({
            "topic": "the $99",
            "detail": "the catalogue calls it a 'Diagnostic Service Call'; the FAQ calls the same $99 a "
                      "'dispatch fee'. Both describe one charge for the visit that includes the diagnosis.",
            "resolution": "quote $99 once per visit as a diagnostic that includes the trip; never add a "
                          "second dispatch charge on top",
        })

    # Area rules are not uniform across services — a real trap for a naive agent.
    low = book_text.lower()
    wh_area = "water heater estimates available anywhere in missouri" in low
    plumb_area = "plumbing equipment estimates outside st. charles county" in low
    if wh_area and plumb_area:
        contradictions.append({
            "topic": "coverage differs by job type",
            "detail": "water-heater estimates are offered 'anywhere in Missouri' and tankless flushing "
                      "'statewide', while other plumbing-equipment estimates stop at the St. Charles "
                      "County line. Diagnostic visits are sold inside the five-county area.",
            "resolution": "test the address against the job type, not against one blanket map: "
                          "water-heater work statewide, everything else inside the five counties",
        })

    not_stated += [
        "no after-hours or 24/7 service is claimed anywhere; emergencies are handled Monday–Saturday inside business hours",
        "no street address for walk-in visits is published (service-area business)",
        "no per-repair prices are published; the site quotes the $99 diagnostic and a maintenance menu only",
        "no license number is printed on the captured pages, only 'licensed, bonded and insured'",
        "no cancellation or late-arrival policy is published",
        "no explicit travel or trip charge beyond the $99 diagnostic is published",
    ]

    business["services"] = services
    business["not_stated"] = not_stated
    business["contradictions"] = contradictions
    business["captured_at"] = provenance["captured_at"]
    (FACTS / "business.json").write_text(
        json.dumps(business, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with (FACTS / "sources.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["field", "value", "status", "source_page",
                                           "source_file", "evidence", "note"])
        w.writeheader()
        w.writerows(rows)

    assumptions = [
        ("agent_role", "front desk for inbound service requests", "design rule",
         "the agent answers, helps choose a service, collects details and guides to a booking or payment"),
        ("service_area_rule", "inside the five named counties -> proceed; outside -> take the address and say the "
                              "office confirms coverage; water-heater work is offered statewide",
         "design rule", "coverage on the site is not uniform, so the rule is per job type"),
        ("price_rule", "quote only the published catalogue prices; every repair is 'quoted after diagnosis'",
         "design rule", "no repair prices are published; inventing one would be a fabrication"),
        ("diagnostic_rule", "one $99 charge per visit covers travel and diagnosis; repairs are quoted separately "
                            "and approved before work starts",
         "design rule", "reconciles the catalogue name and the FAQ wording"),
        ("emergency_rule", "gas smell, no heat in freezing weather, burst pipe, sewage backup -> safety script, "
                           "then the next same-day slot inside business hours",
         "design rule", "the site commits to same-day only Monday–Saturday"),
        ("photo_request", "ask for a photo of the unit label or the leak before promising a price band",
         "assumption", "not stated by the business; matches how a dispatcher actually triages"),
        ("handoff_threshold", "hand off to a person for commercial rooftops, warranty-company dispatch, permits, "
                              "or multi-system jobs",
         "assumption", "the booking page already routes light commercial work to office review"),
        ("saturday_surcharge_display", "show +$50 before the customer picks a Saturday slot, not after",
         "design rule", "the surcharge is published on the booking form but easy to miss; stating it up front prevents a surprise"),
        ("no_24_7_claim", "never promise round-the-clock service", "design rule",
         "the business publishes no after-hours number or claim"),
        ("freshness_window", "facts are valid for 30 days from captured_at", "assumption",
         "prices and hours drift; a dated ledger forces a re-scrape"),
    ]
    with (FACTS / "parameters.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["parameter", "value", "status", "reason"])
        w.writerows(assumptions)

    print(f"{len(rows)} sourced fields")
    print(f"{len(services)} catalogue rows, {sum(1 for s in services if s['price_usd'])} priced")
    print(f"{len(contradictions)} contradictions resolved, {len(not_stated)} gaps recorded")
    print(f"{len(assumptions)} assumptions logged")
    print("\ngaps the agent must not paper over:")
    for g in not_stated:
        print("  -", g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
