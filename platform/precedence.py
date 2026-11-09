"""
Rule precedence as data.

The S06 failure was mine before it was the agent's: I wrote a probe that asked
for a water-heater replacement estimate in a county I had marked out of area, and
the agent correctly told me water-heater work is statewide. Two rules were both
true — "coverage is five counties" and "water-heater work is statewide" — and
nothing in either sentence said which one wins for a given job.

Prose has no precedence. This module gives rules an order and a scope, evaluates
them against a facts dict, and returns a decision with the rule that produced it.
The agent then reports a decision instead of reconciling a policy.

    rules = [
        Rule("statewide_water_heater", 10, lambda f: f["job"] == "water_heater_replacement",
             lambda f: Decision(True, "water-heater replacement is offered statewide")),
        Rule("five_county_diagnostic", 20, lambda f: f["job"] == "diagnostic",
             lambda f: Decision(f["county"] in FIVE_COUNTIES,
                                "diagnostic visits are sold in five counties")),
    ]
    resolve(rules, {"job": "diagnostic", "county": "Franklin"})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

FIVE_COUNTIES = {"St. Charles", "St. Louis", "Lincoln", "Warren", "Jefferson"}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class Rule:
    name: str
    order: int
    applies: Callable[[dict], bool]
    decide: Callable[[dict], Decision]


@dataclass
class Resolution:
    allowed: bool
    reason: str
    rule: str
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason,
                "rule": self.rule, "skipped": self.skipped}


def resolve(rules: list[Rule], facts: dict) -> Resolution:
    """First applicable rule wins; every rule that did not apply is recorded."""
    skipped: list[str] = []
    for rule in sorted(rules, key=lambda r: r.order):
        if not rule.applies(facts):
            skipped.append(rule.name)
            continue
        d = rule.decide(facts)
        return Resolution(d.allowed, d.reason, rule.name, skipped)
    return Resolution(False, "no rule covers this request", "none", skipped)


def default_rules() -> list[Rule]:
    return [
        Rule(
            "statewide_water_heater",
            10,
            lambda f: f.get("job") in {"water_heater_replacement", "water_heater_flush", "tankless_flush"},
            lambda f: Decision(True, "water-heater work is offered anywhere in Missouri"),
        ),
        Rule(
            "five_county_diagnostic",
            20,
            lambda f: f.get("job") == "diagnostic",
            lambda f: Decision(f.get("county") in FIVE_COUNTIES,
                               "diagnostic visits are sold inside the five named counties"),
        ),
        Rule(
            "plumbing_estimate_st_charles",
            30,
            lambda f: f.get("job") == "plumbing_equipment_estimate",
            lambda f: Decision(f.get("county") == "St. Charles",
                               "other plumbing-equipment estimates stop at the St. Charles County line"),
        ),
        Rule(
            "hvac_estimate",
            40,
            lambda f: f.get("job") == "hvac_estimate",
            lambda f: Decision(True, "HVAC replacement estimates carry no published area limit"),
        ),
    ]
