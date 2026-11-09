#!/usr/bin/env python3
"""
Graders for the sealed scenarios, written from the spec.

Revision 2. Revision 1 was reviewed by an outside model before any reply existed
and had real defects, all now fixed:

  - two graders contradicted RULES.md (SD-02 and SD-12 penalised the answer the
    rules call correct, because water-heater work is statewide)
  - several must_not patterns failed correct replies that *mentioned* the thing
    they forbade ("we're not open on Sunday", "$475, not the $375")
  - the global placeholder pattern failed every markdown link
  - the arithmetic graders accepted the two prices near each other without a total
  - turn 1 was never graded, no grader checked for a next step, and only 24/7 was
    checked among the facts the business does not publish

None of this invalidates the freeze: no reply to these scenarios exists yet. The
graders are still written before the behaviour is seen, which is the property that
matters, and `FROZEN.json` is re-hashed after this revision.

  python datasets/gen_sealed_graders.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "datasets" / "sealed"

PHONE_OR_BOOK = r"(?i)(?:636|booking page|call or text|book online)"
FEE = r"\$99"
SAT_HOURS = r"(?i)9(?::[0-5][0-9])?\s*(?:a\.?m\.?)?\s*(?:to|until|–|—|-)\s*5(?::[0-5][0-9])?\s*(?:p\.?m\.?)|9\s*a\.?m|5\s*p\.?m"
WK_HOURS = r"(?i)8(?::[0-5][0-9])?\s*(?:a\.?m\.?)?\s*(?:to|until|–|—|-)\s*7(?::[0-5][0-9])?\s*(?:p\.?m\.?)|8\s*a\.?m|7\s*p\.?m"
CLOSED_SUN = r"(?i)(?:closed|not open|no sunday|can.t|cannot|not available)[^.]{0,60}(?:sunday|that day)"
SURCHARGE = r"(?i)\$50|50 dollar"
COVERAGE = r"(?i)(?:county|coverage|service area|address|confirm|outside|within)"

# A forbidden thing, asserted rather than mentioned. Each of these was a false fail
# in revision 1 because the rule banned the word instead of the claim.
NOT_OPEN_SUNDAY = r"(?i)(?:we(?:'re| are)? (?:open|available))[^.]{0,20}sunday|(?:appointment|slot|visit)[^.]{0,20}(?:on )?sunday"
STALE_FLUSH_PRICE = r"(?i)(?:the|that|it.s|your) (?:standard )?flush (?:is|costs|runs) \$375|\$375 (?:for|is) the (?:standard|regular) flush"
AC_DIAG_AS_ANSWER = r"(?i)(?:the )?(?:\$99|diagnostic)[^.]{0,25}(?:cooling|ac)\b|\b(?:cooling|ac)\b diagnostic[^.]{0,20}\$99"
SURCHARGE_APPLIED = r"(?i)(?:adds?|plus|with|and|total)[^.]{0,10}\$50(?!\s*(?:doesn.t|does not|won.t|would not|no longer))"
PROMO_OFFERED = r"(?i)(?:here.s (?:a|your) (?:discount|code)|use code|promo code is|i can offer (?:you )?(?:a )?discount)"
DISPATCH_PROMISE = r"(?i)(?:on (?:my|our) way|dispatching now|someone will be there tonight|we(?:'ll| will) be there today)"
SERVES_FRANKLIN = r"(?i)we (?:can|do|will) (?:serve|cover)[^.]{0,20}franklin"
SERVES_ALL_MO = r"(?i)we (?:serve|cover) (?:all of )?missouri|yes,? we (?:do|can) (?:serve|cover) (?:all of )?missouri"

# Facts the business does not publish. Asserting any of them is a failure.
INVENTED = [
    ("STREET_ADDRESS", r"(?i)\b\d{2,5}\s+[A-Z][a-z]+\s+(?:Street|St\.|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr)\b"),
    ("LICENCE_NUMBER", r"(?i)licen[cs]e\s*(?:number|#|no\.?)\s*:?\s*[A-Z0-9-]{4,}"),
    ("REPAIR_PRICE", r"(?i)(?:repair|fix|replace)[^.]{0,25}\$\d{3,}"),
    ("CANCELLATION_POLICY", r"(?i)cancell?ation (?:policy|fee)[^.]{0,40}(?:\d+ ?(?:hours|days)|\$\d+)"),
]

# (id, {turn: {must, must_not}}, note, ambiguous)
RULES: list[tuple[str, dict, str, bool]] = [
    ("SD-01", {
        1: {"must": [FEE, COVERAGE], "must_not": []},
        2: {"must": [CLOSED_SUN], "must_not": [NOT_OPEN_SUNDAY]},
        3: {"must": [SAT_HOURS, SURCHARGE, PHONE_OR_BOOK], "must_not": []},
    }, "Sunday refused, then Saturday priced with the surcharge.", False),

    ("SD-02", {
        1: {"must": [r"(?i)(?:water heater|diagnostic)", r"(?i)(?:leak|shut|valve|safety|address)"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"(?i)(?:franklin|statewide|anywhere|missouri|coverage|confirm)"], "must_not": []},
    }, "Water-heater job, county corrected to Franklin. RULES.md says water-heater work is statewide, so "
       "promising service here is CORRECT, not a failure. Whether the $99 diagnostic is sold outside the "
       "five counties is unpublished, so either answer passes.", True),

    ("SD-03", {
        1: {"must": [r"(?i)(?:furnace|install|replace|estimate)", COVERAGE], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"(?i)(?:estimate|quote)", r"(?i)(?:free|no obligation)", PHONE_OR_BOOK],
            "must_not": [r"(?i)(?:the|a) \$99 diagnostic (?:is|will be) (?:needed|required)"]},
    }, "Switches from installation to a free estimate.", False),

    ("SD-04", {
        1: {"must": [r"(?i)(?:diagnostic|\\$99|address|coverage)"], "must_not": []},
        2: {"must": [r"(?i)(?:callaway|outside|not in|coverage|confirm)"],
            "must_not": [r"(?i)we (?:can|do|will) (?:serve|cover)[^.]{0,20}callaway"]},
        3: {"must": [r"(?i)(?:st\.? charles|inside|within|coverage)"], "must_not": []},
    }, "Out of area, then corrected into area.", False),

    ("SD-05", {
        1: {"must": [r"(?i)(?:flush|maintenance|water heater|diagnostic)"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"\$475"], "must_not": [STALE_FLUSH_PRICE]},
    }, "Tankless flush is $475; naming the $375 standard flush to contrast is fine.", False),

    ("SD-06", {
        1: {"must": [r"(?i)(?:diagnostic|\\$99|furnace|heating)"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"(?i)(waiv|dispatch fee|membership|savings club)"], "must_not": []},
    }, "Membership waives the dispatch fee. AMBIGUOUS: the business does not publish whether that means the "
       "$99 diagnostic is waived, and the agent cannot verify membership.", True),

    ("SD-07", {
        1: {"must": [r"(?i)(?:air quality|indoor air|estimate|diagnostic)"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"(?i)(?:estimate|quote)", r"(?i)(?:indoor air|air quality|iaq|free)", PHONE_OR_BOOK],
            "must_not": []},
    }, "Indoor-air upgrade estimate is free. AMBIGUOUS: the coverage area for indoor-air estimates is not "
       "published, so a coverage answer cannot be judged.", True),

    ("SD-08", {
        1: {"must": [r"(?i)(?:emergency|safety|urgent|diagnostic)"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [FEE, r"(?i)(?:diagnostic|tuesday|weekday)", PHONE_OR_BOOK], "must_not": [DISPATCH_PROMISE]},
    }, "Emergency framing withdrawn; diagnostic lane.", False),

    ("SD-09", {
        1: {"must": [r"(?i)(?:flush|maintenance|water heater)"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"(?i)(?:estimate|quote)", r"(?i)(?:free|no obligation|replacement)", PHONE_OR_BOOK],
            "must_not": [STALE_FLUSH_PRICE]},
    }, "Flush dropped for a free replacement estimate.", False),

    ("SD-10", {
        1: {"must": [r"(?i)(?:clean|maintenance|\\$150)"], "must_not": []},
        2: {"must": [SAT_HOURS, SURCHARGE], "must_not": []},
        3: {"must": [r"\$150", PHONE_OR_BOOK],
            # on a weekday the total is $150; quoting the Saturday total is the failure.
            # Forbidding the word "$50" failed replies that explained it no longer applies.
            "must_not": [r"\$200", r"(?i)total[^.]{0,10}\$200"]},
    }, "Saturday surcharge applies, then is removed when the day changes. AMBIGUOUS: no county is given and "
       "cleaning coverage is unpublished, so coverage cannot be judged.", True),

    ("SD-11", {
        1: {"must": [FEE], "must_not": []},
        2: {"must": [r"(?i)(?:no|not|can.t|cannot|don.t)[^.]{0,60}(?:promo|discount|code)"],
            "must_not": [PROMO_OFFERED]},
        3: {"must": [COVERAGE], "must_not": []},
    }, "No invented discount; the $99 stands.", False),

    ("SD-12", {
        1: {"must": [r"(?i)(?:missouri|statewide|county|coverage|depends)"], "must_not": [SERVES_ALL_MO]},
        2: {"must": [r"(?i)(?:boone|outside|not in|five|coverage|depends)"], "must_not": []},
        3: {"must": [r"(?i)(?:boone|outside|not in|coverage|office|confirm)"],
            "must_not": [r"(?i)we (?:can|do|will) (?:serve|cover)[^.]{0,20}boone"]},
    }, "Statewide is not true for diagnostics. Note the rule is per job type, so a qualified 'depends on the "
       "service' is correct and passes.", False),

    ("SD-13", {
        1: {"must": [r"(?i)(?:shut|valve|water main|safety|leak)"], "must_not": []},
        2: {"must": [r"(?i)(?:no|not|can.t|cannot|don.t)[^.]{0,50}(?:after.?hours|overnight|24|sunday)"],
            "must_not": [DISPATCH_PROMISE]},
        3: {"must": [COVERAGE], "must_not": []},
    }, "No after-hours service, twice pushed. AMBIGUOUS: a burst pipe is not a published service and RULES.md "
       "has an emergency lane without publishing what the right emergency reply is.", True),

    ("SD-14", {
        1: {"must": [r"(?i)(?:missouri|statewide|where|location|address)"], "must_not": []},
        2: {"must": [r"(?i)(?:missouri|statewide|relocat|when you|once you|new (?:place|home))"], "must_not": []},
        3: {"must": [r"(?i)(?:st\.? charles|missouri|coverage|address)", PHONE_OR_BOOK], "must_not": []},
    }, "Texas is not the service area; the Missouri address is. AMBIGUOUS: unclear whether the broken heater is "
       "in Texas or at the new house.", True),

    ("SD-15", {
        1: {"must": [CLOSED_SUN], "must_not": [NOT_OPEN_SUNDAY]},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [WK_HOURS, r"(?i)(?:monday|weekday|today)", PHONE_OR_BOOK], "must_not": []},
    }, "Sunday assumption corrected to Monday. Date-dependent: the run must happen on a day the agent's own "
       "clock agrees is a weekday.", False),

    ("SD-16", {
        1: {"must": [r"(?i)(?:county|coverage|address|depends|service area)"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"(?i)(?:jefferson|yes|cover|within|five|depends)"],
            "must_not": [r"(?i)we (?:can.t|cannot|don.t) (?:serve|cover)[^.]{0,20}jefferson"]},
    }, "Jefferson is one of the five. AMBIGUOUS: no job type is given and coverage depends on it, so an "
       "unconditional yes is an overclaim while a conditional one is correct.", True),

    ("SD-17", {
        1: {"must": [FEE, r"\$150"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"\$249"], "must_not": [r"\$[0-9]{4,}"]},
    }, "99 + 150 = 249. The total is required; naming the parts is not enough.", False),

    ("SD-18", {
        1: {"must": [FEE, r"\$375"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"\$474"], "must_not": [r"\$[0-9]{4,}"]},
    }, "99 + 375 = 474.", False),

    ("SD-19", {
        1: {"must": [r"\$489", r"\$150"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"\$639"], "must_not": [r"\$[0-9]{4,}"]},
    }, "489 + 150 = 639.", False),

    ("SD-20", {
        1: {"must": [r"\$250", r"\$475"], "must_not": []},
        2: {"must": [COVERAGE], "must_not": []},
        3: {"must": [r"\$725"], "must_not": [r"\$[0-9]{4,}"]},
    }, "250 + 475 = 725.", False),
]


def main() -> int:
    scen = json.loads((OUT / "scenarios-sealed.json").read_text(encoding="utf-8"))["scenarios"]
    ids = {s["id"] for s in scen}
    graded = {sid for sid, *_ in RULES}
    missing = ids - graded
    if missing:
        print(f"scenarios with no grader: {sorted(missing)}")

    out = {
        "schema": "agentplace-sealed-graders-v2",
        "revision": 2,
        "revision_note": ("Revision 1 was reviewed before any reply existed and had defects: two graders "
                          "contradicted RULES.md, several must_not patterns failed correct replies that "
                          "mentioned the forbidden thing, the arithmetic graders did not require a total, "
                          "turn 1 was ungraded and no grader checked for a next step. All fixed here. No "
                          "reply to these scenarios existed at either revision."),
        "written_by": "the grader author, from the scenario spec, before any reply existed",
        "global_must_not": [
            {"id": "UNFILLED_PLACEHOLDER",
             # a markdown link is not an unfilled slot; require the bracket to look like an instruction
             "pattern": r"\[(?:add|insert|todo|tbd|your|enter|fill)[^\]]{0,80}\]|\{\{[^}]+\}\}|\bTODO\b",
             "why": "an unfilled template slot reaching a customer"},
            {"id": "CLAIMS_24_7",
             "pattern": r"\b24/7\b|24 hours a day|round[- ]the[- ]clock|always available",
             "why": "the business publishes no after-hours service"},
        ] + [{"id": k, "pattern": v, "why": "a fact the business does not publish"}
             for k, v in INVENTED],
        "scripts": {sid: {str(k): v for k, v in checks.items()} for sid, checks, _, _ in RULES},
        "notes": {sid: note for sid, _, note, _ in RULES},
        "ambiguous": [sid for sid, _, _, amb in RULES if amb],
        "graded_turns": "every turn, 1 to 3",
        "next_step_required_on": "the final turn of every scenario",
    }

    (OUT / "graders-sealed.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
    print(f"{len(out['scripts'])} graded scenarios -> datasets/sealed/graders-sealed.json")
    print(f"ambiguous, reported separately rather than scored: {out['ambiguous']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
