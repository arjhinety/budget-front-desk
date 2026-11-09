#!/usr/bin/env python3
"""
Generate the multi-turn scenario set.

Eighteen scripts, three customer turns each, in six behavioural families. The
grader checks are attached to a specific turn where the behaviour is turn-local,
and applied to every reply where it is not (price integrity, never open Sunday,
never re-ask a fact the customer already gave).

Why three turns and not four: turn 1 gives a fact, turn 2 corrects or complicates
it, turn 3 asks for something that depends on both. A fourth turn adds authoring
cost and a second chance to drift, and the arithmetic case it would test is
covered by a price check on turn 3.

  python evals/gen_multiturn.py
"""

from __future__ import annotations

import json
from pathlib import Path

EVALS = Path(__file__).resolve().parent

PHONE = "(?i)636"
FEE = "\\$99"
SAT = r"(?i)9(?::[0-5][0-9])?\s*(?:a\.?m\.?)?\s*(?:to|until|–|—|-)\s*5(?::[0-5][0-9])?\s*(?:p\.?m\.?)|9\s*a\.?m|5\s*p\.?m"
WEEK = r"(?i)8(?::[0-5][0-9])?\s*(?:a\.?m\.?)?\s*(?:to|until|–|—|-)\s*7(?::[0-5][0-9])?\s*(?:p\.?m\.?)|8\s*a\.?m|7\s*p\.?m"


def script(sid, family, turns, checks, note=""):
    """turns: list of customer messages. checks: {turn_index: {must, must_not}}."""
    return {"id": sid, "family": family, "turns": turns, "checks": checks, "note": note}


def build() -> list[dict]:
    out = []

    # ---- 1. self-correction: the customer fixes a fact, later replies must use it
    out.append(script("MT-C01", "self-correction",
        ["my furnace wont light and im in franklin county, can you send someone",
         "sorry, typo - im in st charles county, ofallon",
         "ok so what does that cost"],
        {1: {"must": ["(?i)(franklin|outside|not in|coverage|service area)"],
             "must_not": ["(?i)(yes,? we (can|do) (serve|cover) franklin)"]},
         2: {"must": [FEE, "(?i)(st\\.? charles|inside|within|coverage)"],
             # naming Franklin to acknowledge the correction is correct; treating it
             # as the location is not
             "must_not": ["(?i)(serve|cover|come to|out to|in) franklin"]},
         3: {"must": [FEE], "must_not": []}},
        "The corrected county must replace the first one, not sit alongside it."))

    out.append(script("MT-C02", "self-correction",
        ["my ac is dead, im in jefferson county",
         "actually it's the furnace, not the ac",
         "and how much for someone to look at it"],
        {1: {"must": ["(?i)(diagnostic|\\$99|address)"], "must_not": []},
         2: {"must": ["(?i)(furnace|heating)"],
             # quoting the cooling diagnostic as the answer is the failure; saying
             # "not the AC" is the correction
             "must_not": [r"(?i)(?:\$99|diagnostic)[^.]{0,30}\b(?:cooling|ac)\b|\b(?:cooling|ac) diagnostic[^.]{0,20}\$99"]},
         3: {"must": [FEE], "must_not": []}},
        "The service must switch from cooling to heating without re-asking."))

    out.append(script("MT-C03", "self-correction",
        ["i want a quote to replace my water heater in franklin county",
         "wait, it's a plumbing fixture replacement not a water heater",
         "so what do i do next"],
        {1: {"must": ["(?i)(estimate|quote)", "(?i)(anywhere|statewide|missouri|franklin)"], "must_not": []},
         2: {"must": ["(?i)(st\\.? charles|county|coverage|estimate)"], "must_not": []},
         3: {"must": ["(?i)(booking|call|text|636)"], "must_not": []}},
        "Different job type, different coverage rule. This is the S06 trap in multi-turn form."))

    # ---- 2. memory: a fact from turn 1 is needed at turn 3
    out.append(script("MT-M01", "memory",
        ["my water heater is leaking, im at 412 s main st in st charles",
         "how much is the visit",
         "and can you get someone out this week"],
        {1: {"must": ["(?i)(diagnostic|\\$99|address|details)"], "must_not": []},
         2: {"must": [FEE], "must_not": []},
         3: {"must": ["(?i)(booking|call|text|636)"],
             "must_not": ["(?i)(what.s|which|share|send).{0,30}(address|county|zip)"]}},
        "The address was given in turn 1. Asking for it again in turn 3 is the failure."))

    out.append(script("MT-M02", "memory",
        ["its a 2016 tankless water heater in warren county, no hot water",
         "what are my options",
         "and what would the flush cost"],
        {1: {"must": ["(?i)(diagnostic|\\$99|tankless|water heater)"], "must_not": []},
         2: {"must": ["(?i)(estimate|diagnostic|\\$99)"], "must_not": []},
         3: {"must": ["(?i)\\$475|tankless"],
             "must_not": ["(?i)(what|which).{0,25}(water heater type|tank or tankless)"]}},
        "Tankless was stated in turn 1; the flush price is the tankless one."))

    out.append(script("MT-M03", "memory",
        ["im in lincoln county and my heat is out",
         "its 15 degrees tonight",
         "whats the next step"],
        {1: {"must": ["(?i)(diagnostic|\\$99|emergency|address)"], "must_not": []},
         2: {"must": ["(?i)(emergency|safety|warm|same.?day|urgent|closed|hours)"], "must_not": []},
         3: {"must": ["(?i)(636|call|text)"],
             "must_not": ["(?i)(what|which).{0,30}(county|address)"]}},
        "County was given in turn 1 and the cold in turn 2; neither may be re-asked."))

    # ---- 3. change of mind: the service switches and the price must switch with it
    out.append(script("MT-S01", "change-of-mind",
        ["my ac stopped cooling, what does a diagnostic cost",
         "actually forget the diagnostic, i want a price to replace the whole system",
         "ok whats the difference"],
        {1: {"must": [FEE], "must_not": []},
         2: {"must": ["(?i)(estimate|quote)", "(?i)(free|no obligation)"], "must_not": ["(?i)^.{0,40}\\$99"]},
         3: {"must": ["(?i)(estimate|diagnostic)"], "must_not": []}},
        "Turn 2 must not keep selling the diagnostic."))

    out.append(script("MT-S02", "change-of-mind",
        ["i need a saturday tune up",
         "actually make it a weekday, im off tuesday",
         "and what does that run"],
        {1: {"must": [SAT, "(?i)\\$50|50 dollar"], "must_not": []},
         2: {"must": [WEEK],
             # applying the Saturday surcharge to a weekday is the failure; noting
             # that it no longer applies is the correction
             "must_not": [r"(?i)(?:adds?|plus|with|and) \$50|\$50 (?:surcharge|fee)[^.]{0,20}(?:applies|added)"]},
         3: {"must": ["(?i)\\$150|clean|maintenance"], "must_not": []}},
        "The Saturday surcharge must disappear when Saturday does."))

    out.append(script("MT-S03", "change-of-mind",
        ["my water heater is leaking, im in jefferson county",
         "on second thought just tell me about the savings club",
         "what does that include"],
        {1: {"must": [FEE], "must_not": []},
         2: {"must": ["(?i)\\$250|savings club|membership"], "must_not": []},
         3: {"must": ["(?i)(waiv|dispatch|maintenance|% off|discount)"], "must_not": []}},
        "The topic moved; the answer must move with it."))

    # ---- 4. constraint under pushback: the rule must hold when pushed twice
    out.append(script("MT-P01", "pushback",
        ["can someone come out sunday",
         "im only free sunday, i really need it",
         "so you cant help me at all"],
        {1: {"must": ["(?i)(closed|not open|no sunday)"], "must_not": ["(?i)(open|available|appointment)[^.]{0,15}sunday"]},
         2: {"must": ["(?i)(closed|can.t|cannot|not available)"], "must_not": ["(?i)(we can|we will|we.ll) (?:come|be there)"]},
         3: {"must": ["(?i)(monday|saturday|weekday|636|call)"], "must_not": ["(?i)(yes|sure|ok)[^.]{0,20}sunday"]}},
        "Three chances to give in. The closed-Sunday rule has to survive all three."))

    out.append(script("MT-P02", "pushback",
        ["do you do emergency calls at 2am",
         "but its an emergency, someone has to come",
         "fine, whats the number"],
        {1: {"must": ["(?i)(not|no|can.t|closed)[^.]{0,40}(24|after.?hours|overnight)"], "must_not": ["(?i)\\b24/7\\b"]},
         2: {"must": ["(?i)(can.t|cannot|not able|no)[^.]{0,40}(2 ?a\\.?m|overnight|after.?hours)"], "must_not": ["(?i)(on (my|our) way|dispatching now)"]},
         3: {"must": [PHONE], "must_not": []}},
        "A 2am emergency is the strongest possible push. The answer may not change."))

    out.append(script("MT-P03", "pushback",
        ["im in franklin county, my furnace is out",
         "your truck was on my street last week, just come out",
         "so youre refusing to help"],
        {1: {"must": ["(?i)(franklin|outside|not in|coverage)"], "must_not": ["(?i)(yes,? we (can|do) (serve|cover) franklin)"]},
         2: {"must": ["(?i)(can.t|cannot|not able|office|confirm|coverage)"], "must_not": ["(?i)(we.ll be there|sending (a|our) (tech|truck))"]},
         3: {"must": ["(?i)(office|636|call|confirm)"], "must_not": ["(?i)(we (can|will) serve franklin)"]}},
        "The neighbour argument is a real one. The coverage rule still has to hold."))

    # ---- 5. misunderstanding recovery: ambiguous opener, then a clarification
    out.append(script("MT-X01", "recovery",
        ["my heater is acting up",
         "its the water heater, not the furnace",
         "how much to look at it"],
        {1: {"must": ["(?i)(what|which|tell me|describe)"], "must_not": ["(?i)^.{0,60}\\$"]},
         2: {"must": ["(?i)(water heater)"], "must_not": []},
         3: {"must": [FEE], "must_not": []}},
        "Turn 1 should ask; turn 3 should quote the water-heater diagnostic, not the HVAC one."))

    out.append(script("MT-X02", "recovery",
        ["i need someone out",
         "the ac, its not cooling",
         "im in warren county"],
        {1: {"must": ["(?i)(what|which|tell me|describe)"], "must_not": []},
         2: {"must": ["(?i)(diagnostic|\\$99|cooling|ac)"], "must_not": []},
         3: {"must": ["(?i)(warren|coverage|address|within)"], "must_not": []}},
        "A bare request is not a diagnosis; the agent has to ask before pricing."))

    out.append(script("MT-X03", "recovery",
        ["hi",
         "hello?",
         "is anyone there"],
        {1: {"must": ["(?i)(help|what|tell me|going on)"], "must_not": ["(?i)(booked|confirmed|scheduled)"]},
         2: {"must": ["(?i)(help|what|tell me|going on)"], "must_not": ["(?i)(booked|confirmed|scheduled)"]},
         3: {"must": ["(?i)(help|what|tell me|636|call)"], "must_not": ["(?i)(booked|confirmed|scheduled)"]}},
        "Three near-empty messages. No invented booking, and no identical reply three times."))

    # ---- 6. arithmetic and totals
    out.append(script("MT-A01", "arithmetic",
        ["i want the one-time hvac cleaning",
         "can you do saturday",
         "so whats the total"],
        {1: {"must": ["\\$150"], "must_not": []},
         2: {"must": [SAT, "(?i)\\$50|50 dollar"], "must_not": []},
         3: {"must": ["\\$200|\\$150.{0,40}\\$50|\\$50.{0,40}\\$150"], "must_not": ["(?i)\\$[0-9]{3,}"]}},
        "150 + 50 = 200. A total built from two published prices is correct, not invented."))

    out.append(script("MT-A02", "arithmetic",
        ["whats the diagnostic cost",
         "and if i join the savings club",
         "so what do i pay for the visit if im a member"],
        {1: {"must": [FEE], "must_not": []},
         2: {"must": ["(?i)\\$250|savings club|membership"], "must_not": []},
         3: {"must": ["(?i)(waiv|included|no dispatch|\\$0)"], "must_not": ["(?i)\\$[0-9]{3,}"]}},
        "Members have the dispatch fee waived. The answer must reflect that, not repeat $99."))

    out.append(script("MT-A03", "arithmetic",
        ["i need the tankless flush",
         "and the regular water heater flush too",
         "whats that together"],
        {1: {"must": ["\\$475"], "must_not": []},
         2: {"must": ["\\$375"], "must_not": []},
         3: {"must": ["\\$850|\\$475.{0,40}\\$375|\\$375.{0,40}\\$475"], "must_not": ["(?i)\\$[0-9]{4,}"]}},
        "475 + 375 = 850. Two published prices, one correct total."))

    return out


def main() -> int:
    scripts = build()
    graders = {
        "note": "Generated by gen_multiturn.py. Turn indices are 1-based.",
        "global_must_not": [
            {"id": "UNFILLED_PLACEHOLDER",
             "pattern": "\\[[^\\]]{4,90}\\]|\\{\\{[^}]+\\}\\}|\\bTODO\\b|\\badd verified\\b",
             "why": "an unfilled template slot reaching a customer"},
            {"id": "CLAIMS_24_7",
             "pattern": "\\b24/7\\b|24 hours a day|round[- ]the[- ]clock|always available",
             "why": "the business publishes no after-hours service"},
        ],
        "scripts": {s["id"]: s["checks"] for s in scripts},
    }
    for s in scripts:
        s.pop("checks")

    (EVALS / "scenarios-mt.json").write_text(
        json.dumps({"schema": 1, "note": "multi-turn, 3 turns per script",
                    "scripts": scripts}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (EVALS / "graders-mt.json").write_text(
        json.dumps(graders, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    from collections import Counter
    print(f"{len(scripts)} scripts, {sum(len(s['turns']) for s in scripts)} customer turns")
    print("by family:", dict(Counter(s["family"] for s in scripts)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
