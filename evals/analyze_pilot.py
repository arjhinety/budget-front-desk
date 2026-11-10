#!/usr/bin/env python3
"""
Read-only scenario-level diagnostic for the agentplace pilot.

This tool never runs an agent, never calls a network service, and never edits a
capture.  It reads two canonical JSON files, validates them, and prints (or
writes once to a new file) a deterministic diagnostic report.

Observations
------------
{
  "schema_version": "agentplace.pilot.observations.v1",
  "records": [
    {
      "scenario_id": "...",
      "template_id": "...",
      "cohort": "targeted" | "tripwire",
      "phase": "before" | "after",
      "arm": "treatment" | "control",
      "trial": 1,
      "status": "valid" | "invalid",
      "integrity_pass": true,
      "complete_pass": true,
      "project_id": "...",          # optional; null/missing means not observed
      "config_sha256": "..."        # optional; null/missing means not observed
    }
  ]
}

Plan
----
{
  "schema_version": "agentplace.pilot.plan.v1",   # optional but checked
  "bootstrap_seed": 20261111,
  "bootstrap_resamples": 5000,
  "scenarios": [
    {
      "id": "S01",
      "template_id": "T-01",
      "cohort": "targeted",
      "trials": 3,
      "identities": {                              # optional per-scenario override
        "before": {"treatment": {"project_id": "...", "config_sha256": "..."}},
        "after":  {"treatment": {"project_id": "...", "config_sha256": "..."}}
      }
    }
  ],
  "identities": {                                  # optional, plan-wide defaults
    "before": {
      "treatment": {"project_id": "...", "config_sha256": "..."},
      "control":   {"project_id": "...", "config_sha256": "..."}
    },
    "after": {
      "treatment": {"project_id": "...", "config_sha256": "..."},
      "control":   {"project_id": "...", "config_sha256": "..."}
    }
  }
}

`identities` (or its alias `required_identities`) may be omitted.  When it is
omitted, or when an observation does not carry the declared value, the cell is
marked unverified and inferential claims are blocked.  Nothing is imputed.

Statistics
----------
* Per scenario and cell: trial pass fraction over valid attempts.  Invalid
  attempts are retained, counted, and excluded from the pass numerator and
  denominator; they are never scored as agent failures.
* A/A (`--phase aa`): mean absolute difference between the treatment and
  control before-phase scenario pass fractions, plus strict disagreement of the
  all-trials-pass indicator.  This is run-to-run variation, including model
  randomness; it is not pure build variance and does not establish
  equivalence.
* Before/after: treatment change, control drift, and their scenario-level
  difference (difference-in-differences).  Only scenarios with all four
  planned cells complete enter.  The treatment-change sign test is exact
  binomial over scenarios, ties omitted.  Trial indices are never paired
  across arms.
* Primary interval: percentile bootstrap over template groups, with each
  template equally weighted (macro-average template effect).  The case-weighted
  descriptive mean is reported separately, together with the explicit
  difference between the two weighting schemes.
* No p-value threshold defines success, and no loop resamples until a
  significant result appears.

Usage
-----
    python evals/analyze_pilot.py --observations obs.json --plan plan.json
    python evals/analyze_pilot.py --observations obs.json --plan plan.json --phase aa
    python evals/analyze_pilot.py --observations obs.json --plan plan.json \
        --format json --out new-report.json

`--out` writes only a new file and refuses to overwrite anything.  Without
`--out` the tool is strictly read-only (apart from stdout).  `--help` performs
no reads and no writes.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "agentplace.pilot.plan.v1"
OBSERVATIONS_SCHEMA = "agentplace.pilot.observations.v1"
ANALYSIS_SCHEMA = "agentplace.pilot.analysis.v1"
TOOL_NAME = "analyze_pilot"
TOOL_VERSION = "1.0.0"

COHORTS = ("targeted", "tripwire")
PHASES = ("before", "after")
ARMS = ("treatment", "control")
STATUSES = ("valid", "invalid")
PHASE_MODES = ("ab", "aa")

SIGN_EPS = 1e-12
BOOTSTRAP_LEVEL = 0.95


class InputError(Exception):
    """Raised when an input file is not the canonical schema or is inconsistent."""


# ---------------------------------------------------------------------------
# small validated field helpers
# ---------------------------------------------------------------------------


def _where(where: str, key: str) -> str:
    return f"{where}.{key}" if where else key


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{where}: expected a non-empty string")
    return value.strip()


def _optional_string(value: Any, where: str) -> str | None:
    if value is None:
        return None
    return _string(value, where)


def _integer(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"{where}: expected an integer")
    return value


def _boolean(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise InputError(f"{where}: expected true or false")
    return value


def _optional_boolean(value: Any, where: str) -> bool | None:
    if value is None:
        return None
    return _boolean(value, where)


def _enum(value: Any, allowed: tuple[str, ...], where: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InputError(f"{where}: expected one of {', '.join(allowed)}")
    return value


def _record_field(record: dict[str, Any], key: str, where: str) -> Any:
    if key not in record:
        raise InputError(f"{_where(where, key)}: required field is missing")
    return record[key]


def _identity_norm(field: str, value: str) -> str:
    value = value.strip()
    return value.lower() if field == "config_sha256" else value


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def _validate_identities(raw: Any, where: str) -> dict[str, dict[str, dict[str, str | None]]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InputError(f"{where}: expected an object keyed by phase")
    out: dict[str, dict[str, dict[str, str | None]]] = {}
    for phase, arms in raw.items():
        if phase not in PHASES:
            raise InputError(f"{where}: unknown phase {phase!r}; expected before or after")
        if not isinstance(arms, dict):
            raise InputError(f"{where}.{phase}: expected an object keyed by arm")
        out[phase] = {}
        for arm, spec in arms.items():
            if arm not in ARMS:
                raise InputError(f"{where}.{phase}: unknown arm {arm!r}; expected treatment or control")
            if not isinstance(spec, dict):
                raise InputError(f"{where}.{phase}.{arm}: expected an object")
            unknown = sorted(set(spec) - {"project_id", "config_sha256"})
            if unknown:
                raise InputError(
                    f"{where}.{phase}.{arm}: unknown identity field(s) {unknown}; "
                    "expected project_id and/or config_sha256"
                )
            out[phase][arm] = {
                "project_id": _optional_string(spec.get("project_id"), f"{where}.{phase}.{arm}.project_id"),
                "config_sha256": _optional_string(spec.get("config_sha256"), f"{where}.{phase}.{arm}.config_sha256"),
            }
    return out


def validate_plan(raw: Any) -> dict[str, Any]:
    """Validate and normalize a plan object.  Raises InputError."""
    if not isinstance(raw, dict):
        raise InputError("plan: expected a JSON object")

    if "schema_version" in raw:
        schema = raw["schema_version"]
        if schema != PLAN_SCHEMA:
            raise InputError(f"plan.schema_version: expected {PLAN_SCHEMA!r}, got {schema!r}")

    scenarios_raw = raw.get("scenarios")
    if not isinstance(scenarios_raw, list) or not scenarios_raw:
        raise InputError("plan.scenarios: expected a non-empty list")

    seed = _integer(raw.get("bootstrap_seed"), "plan.bootstrap_seed")
    resamples = _integer(raw.get("bootstrap_resamples"), "plan.bootstrap_resamples")
    if resamples < 1:
        raise InputError("plan.bootstrap_resamples: expected a positive integer")

    identities_raw = raw.get("identities")
    if identities_raw is None and "required_identities" in raw:
        identities_raw = raw["required_identities"]
    identities = _validate_identities(identities_raw, "plan.identities")

    scenarios: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(scenarios_raw):
        where = f"plan.scenarios[{index}]"
        if not isinstance(item, dict):
            raise InputError(f"{where}: expected an object")

        sid = _string(item.get("id"), f"{where}.id")
        template_id = _string(item.get("template_id"), f"{where}.template_id")
        cohort = _enum(item.get("cohort"), COHORTS, f"{where}.cohort")
        trials = _integer(item.get("trials"), f"{where}.trials")
        if trials < 1:
            raise InputError(f"{where}.trials: expected a positive integer")
        if sid in by_id:
            raise InputError(f"plan.scenarios: duplicate scenario id {sid!r}")

        scenario_identities = {}
        if "identities" in item:
            scenario_identities = _validate_identities(item["identities"], f"{where}.identities")
        elif "required_identities" in item:
            scenario_identities = _validate_identities(
                item["required_identities"], f"{where}.required_identities"
            )

        scenario = {
            "id": sid,
            "template_id": template_id,
            "cohort": cohort,
            "trials": trials,
            "identities": scenario_identities,
        }
        scenarios.append(scenario)
        by_id[sid] = scenario

    return {
        "scenarios": scenarios,
        "by_id": by_id,
        "bootstrap_seed": seed,
        "bootstrap_resamples": resamples,
        "identities": identities,
        "schema_version": raw.get("schema_version"),
    }


# ---------------------------------------------------------------------------
# observations
# ---------------------------------------------------------------------------


def _expected_identity(
    plan: dict[str, Any], scenario: dict[str, Any], phase: str, arm: str
) -> dict[str, str | None] | None:
    """Resolve declared identity for one cell.

    Plan-wide declarations form the base; a non-null per-scenario declaration
    overrides the same field.  Missing declarations stay missing: nothing is
    filled or guessed.
    """
    merged: dict[str, str | None] = {"project_id": None, "config_sha256": None}
    for source in (plan.get("identities") or {}, scenario.get("identities") or {}):
        phase_map = source.get(phase)
        if not phase_map:
            continue
        spec = phase_map.get(arm)
        if not spec:
            continue
        for field in merged:
            if spec.get(field) is not None:
                merged[field] = spec[field]
    if not any(value is not None for value in merged.values()):
        return None
    return merged


def _check_valid_cell_identity_consistency(records: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        if record["status"] != "valid":
            continue
        key = (record["scenario_id"], record["phase"], record["arm"])
        groups.setdefault(key, []).append(record)

    for key, group in groups.items():
        for field in ("project_id", "config_sha256"):
            values = {
                _identity_norm(field, record[field])
                for record in group
                if record[field] is not None
            }
            if len(values) > 1:
                raise InputError(
                    "observations: inconsistent "
                    f"{field} within valid cell ({key[0]}, {key[1]}, {key[2]}): "
                    f"{sorted(values)}"
                )


def validate_observations(raw: Any, plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate observations against the plan.  Raises InputError."""
    if not isinstance(raw, dict):
        raise InputError("observations: expected a JSON object")
    if raw.get("schema_version") != OBSERVATIONS_SCHEMA:
        raise InputError(
            "observations.schema_version: expected "
            f"{OBSERVATIONS_SCHEMA!r}, got {raw.get('schema_version')!r}"
        )
    records_raw = raw.get("records")
    if not isinstance(records_raw, list):
        raise InputError("observations.records: expected a list")

    records: list[dict[str, Any]] = []
    seen_valid: set[tuple[str, str, str, int]] = set()

    for index, item in enumerate(records_raw):
        where = f"observations.records[{index}]"
        if not isinstance(item, dict):
            raise InputError(f"{where}: expected an object")

        sid = _string(item.get("scenario_id"), f"{where}.scenario_id")
        template_id = _string(item.get("template_id"), f"{where}.template_id")
        cohort = _enum(item.get("cohort"), COHORTS, f"{where}.cohort")
        phase = _enum(item.get("phase"), PHASES, f"{where}.phase")
        arm = _enum(item.get("arm"), ARMS, f"{where}.arm")
        trial = _integer(item.get("trial"), f"{where}.trial")
        if trial < 1:
            raise InputError(f"{where}.trial: expected a positive integer")

        if sid not in plan["by_id"]:
            raise InputError(f"{where}.scenario_id: scenario {sid!r} is not declared in the plan")
        scenario = plan["by_id"][sid]
        if template_id != scenario["template_id"]:
            raise InputError(
                f"{where}.template_id: {template_id!r} does not match plan "
                f"{scenario['template_id']!r} for scenario {sid!r}"
            )
        if cohort != scenario["cohort"]:
            raise InputError(
                f"{where}.cohort: {cohort!r} does not match plan "
                f"{scenario['cohort']!r} for scenario {sid!r}"
            )
        if trial > scenario["trials"]:
            raise InputError(
                f"{where}.trial: trial {trial} exceeds planned trials "
                f"{scenario['trials']} for scenario {sid!r}"
            )

        status = _enum(item.get("status"), STATUSES, f"{where}.status")
        if status == "valid":
            integrity_pass = _boolean(
                _record_field(item, "integrity_pass", where), f"{where}.integrity_pass"
            )
            complete_pass = _boolean(
                _record_field(item, "complete_pass", where), f"{where}.complete_pass"
            )
            key = (sid, phase, arm, trial)
            if key in seen_valid:
                raise InputError(
                    "observations: duplicate valid record for cell "
                    f"({sid}, {phase}, {arm}, trial {trial})"
                )
            seen_valid.add(key)
        else:
            # Invalid attempts are retained.  Their outcome labels may be null or
            # absent because they are not scored; they are never converted into
            # agent failures.
            integrity_pass = _optional_boolean(item.get("integrity_pass"), f"{where}.integrity_pass")
            complete_pass = _optional_boolean(item.get("complete_pass"), f"{where}.complete_pass")

        project_id = _optional_string(item.get("project_id"), f"{where}.project_id")
        config_sha256 = _optional_string(item.get("config_sha256"), f"{where}.config_sha256")

        expected = _expected_identity(plan, scenario, phase, arm)
        if expected is not None:
            for field, observed in (("project_id", project_id), ("config_sha256", config_sha256)):
                declared = expected[field]
                if declared is None or observed is None:
                    continue
                if _identity_norm(field, observed) != _identity_norm(field, declared):
                    raise InputError(
                        f"{where}.{field}: {observed!r} does not match declared identity "
                        f"{declared!r} for cell ({sid}, {phase}, {arm})"
                    )

        records.append(
            {
                "scenario_id": sid,
                "template_id": template_id,
                "cohort": cohort,
                "phase": phase,
                "arm": arm,
                "trial": trial,
                "status": status,
                "integrity_pass": integrity_pass,
                "complete_pass": complete_pass,
                "project_id": project_id,
                "config_sha256": config_sha256,
            }
        )

    _check_valid_cell_identity_consistency(records)
    return records


# ---------------------------------------------------------------------------
# cell and scenario calculations
# ---------------------------------------------------------------------------


def _identity_for_cell(
    expected: dict[str, str | None] | None, valid: list[dict[str, Any]]
) -> dict[str, Any]:
    observed_projects = sorted({r["project_id"] for r in valid if r["project_id"] is not None})
    observed_configs = sorted(
        {_identity_norm("config_sha256", r["config_sha256"]) for r in valid if r["config_sha256"] is not None}
    )

    if not valid:
        return {
            "expected": expected,
            "observed_project_ids": observed_projects,
            "observed_config_sha256s": observed_configs,
            "status": "no_valid_attempts",
            "missing_observed_fields": [],
        }

    if expected is None:
        return {
            "expected": None,
            "observed_project_ids": observed_projects,
            "observed_config_sha256s": observed_configs,
            "status": "undeclared",
            "missing_observed_fields": [],
        }

    declared = [field for field in ("project_id", "config_sha256") if expected[field] is not None]
    missing = [
        field
        for field in declared
        if any(record[field] is None for record in valid)
    ]

    if missing:
        status = "unverified"
    else:
        mismatched = False
        for field in declared:
            declared_value = _identity_norm(field, expected[field] or "")
            if any(_identity_norm(field, record[field] or "") != declared_value for record in valid):
                mismatched = True
        status = "mismatch" if mismatched else "verified"

    return {
        "expected": expected,
        "observed_project_ids": observed_projects,
        "observed_config_sha256s": observed_configs,
        "status": status,
        "missing_observed_fields": missing,
    }


def _build_cell(
    scenario: dict[str, Any],
    plan: dict[str, Any],
    phase: str,
    arm: str,
    cell_records: list[dict[str, Any]],
) -> dict[str, Any]:
    planned = scenario["trials"]
    valid = [record for record in cell_records if record["status"] == "valid"]
    invalid = [record for record in cell_records if record["status"] == "invalid"]

    by_trial = {record["trial"]: record for record in valid}
    missing_trials = [trial for trial in range(1, planned + 1) if trial not in by_trial]
    passes = sum(1 for record in valid if record["complete_pass"] is True)
    complete = not missing_trials
    all_trials_pass = complete and passes == planned
    pass_fraction = (passes / len(valid)) if valid else None

    expected = _expected_identity(plan, scenario, phase, arm)
    identity = _identity_for_cell(expected, valid)

    attempts = sorted(
        cell_records,
        key=lambda record: (
            record["trial"],
            0 if record["status"] == "valid" else 1,
            record["project_id"] or "",
            record["config_sha256"] or "",
        ),
    )
    attempt_rows = [
        {
            "trial": record["trial"],
            "status": record["status"],
            "complete_pass": record["complete_pass"],
            "integrity_pass": record["integrity_pass"],
            "project_id": record["project_id"],
            "config_sha256": record["config_sha256"],
        }
        for record in attempts
    ]

    return {
        "phase": phase,
        "arm": arm,
        "planned_trials": planned,
        "valid_attempts": len(valid),
        "invalid_attempts": len(invalid),
        "passes": passes,
        "pass_fraction": pass_fraction,
        "all_trials_pass": all_trials_pass,
        "complete": complete,
        "missing_trials": missing_trials,
        "integrity_passes": sum(1 for record in valid if record["integrity_pass"] is True),
        "integrity_failures": sum(1 for record in valid if record["integrity_pass"] is False),
        "invalid_integrity_failures": sum(
            1 for record in invalid if record["integrity_pass"] is False
        ),
        "identity": identity,
        "attempts": attempt_rows,
    }


def _identity_relation(
    left: dict[str, str | None] | None, right: dict[str, str | None] | None
) -> str:
    """Compare two declarations without inventing missing values.

    Returns "same" when every field declared on both sides agrees, "different"
    when a shared field conflicts, and "unknown" when nothing comparable is
    declared.
    """
    if left is None or right is None:
        return "unknown"
    common = [
        field
        for field in ("project_id", "config_sha256")
        if left.get(field) is not None and right.get(field) is not None
    ]
    if not common:
        return "unknown"
    if any(
        _identity_norm(field, left[field] or "") != _identity_norm(field, right[field] or "")
        for field in common
    ):
        return "different"
    return "same"


def _build_scenario(
    scenario: dict[str, Any],
    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]],
    plan: dict[str, Any],
    phase_mode: str,
) -> dict[str, Any]:
    phases = ("before",) if phase_mode == "aa" else ("before", "after")
    cells: dict[str, dict[str, Any]] = {}
    for phase in phases:
        for arm in ARMS:
            key = (scenario["id"], phase, arm)
            cells[f"{phase}/{arm}"] = _build_cell(
                scenario, plan, phase, arm, by_cell.get(key, [])
            )

    missing_cells: list[str] = []
    incomplete_cells: list[dict[str, Any]] = []
    for cell_name, cell in cells.items():
        if cell["valid_attempts"] == 0:
            missing_cells.append(cell_name)
        elif not cell["complete"]:
            incomplete_cells.append(
                {
                    "cell": cell_name,
                    "valid_attempts": cell["valid_attempts"],
                    "planned_trials": cell["planned_trials"],
                    "missing_trials": cell["missing_trials"],
                }
            )

    has_records = any(cell["attempts"] for cell in cells.values())
    identity_verified = all(
        cell["identity"]["status"] == "verified" for cell in cells.values()
    ) and bool(cells)

    if not has_records:
        reasons = ["no_records"]
    else:
        reasons = [f"missing_cell:{name}" for name in missing_cells]
        reasons.extend(f"incomplete_cell:{item['cell']}" for item in incomplete_cells)

    complete = not missing_cells and not incomplete_cells
    if phase_mode == "aa":
        included = bool(
            cells.get("before/treatment", {}).get("complete")
            and cells.get("before/control", {}).get("complete")
        )
    else:
        included = complete

    result: dict[str, Any] = {
        "scenario_id": scenario["id"],
        "template_id": scenario["template_id"],
        "cohort": scenario["cohort"],
        "planned_trials": scenario["trials"],
        "cells": cells,
        "missing_cells": missing_cells,
        "incomplete_cells": incomplete_cells,
        "complete": complete,
        "identity_verified": identity_verified,
        "included_in_analysis": included,
        "exclusion_reasons": [] if included else reasons,
    }

    if phase_mode == "aa" and included:
        treat = cells["before/treatment"]
        control = cells["before/control"]
        p_treat = treat["pass_fraction"]
        p_control = control["pass_fraction"]
        assert p_treat is not None and p_control is not None
        difference = p_treat - p_control
        result["aa"] = {
            "pass_fraction_treatment": p_treat,
            "pass_fraction_control": p_control,
            "signed_difference": difference,
            "absolute_difference": abs(difference),
            "all_trials_pass_treatment": treat["all_trials_pass"],
            "all_trials_pass_control": control["all_trials_pass"],
            "strict_all_trials_pass_disagreement": (
                treat["all_trials_pass"] != control["all_trials_pass"]
            ),
            "polarity_disagreement": (
                abs(treat["pass_fraction"] or 0.0) < SIGN_EPS
                and abs((control["pass_fraction"] or 0.0) - 1.0) < SIGN_EPS
            )
            or (
                abs(control["pass_fraction"] or 0.0) < SIGN_EPS
                and abs((treat["pass_fraction"] or 0.0) - 1.0) < SIGN_EPS
            ),
        }
    else:
        result["aa"] = None

    if phase_mode == "ab" and complete:
        before_treat = cells["before/treatment"]
        before_control = cells["before/control"]
        after_treat = cells["after/treatment"]
        after_control = cells["after/control"]
        bt = before_treat["pass_fraction"]
        bc = before_control["pass_fraction"]
        at = after_treat["pass_fraction"]
        ac = after_control["pass_fraction"]
        assert None not in (bt, bc, at, ac)
        treatment_change = at - bt
        control_drift = ac - bc
        result["comparison"] = {
            "before": {
                "treatment": _cell_effect_view(before_treat),
                "control": _cell_effect_view(before_control),
            },
            "after": {
                "treatment": _cell_effect_view(after_treat),
                "control": _cell_effect_view(after_control),
            },
            "treatment_change": treatment_change,
            "control_drift": control_drift,
            "difference_in_differences": treatment_change - control_drift,
        }
    else:
        result["comparison"] = None

    return result


def _cell_effect_view(cell: dict[str, Any]) -> dict[str, Any]:
    return {
        "pass_fraction": cell["pass_fraction"],
        "passes": cell["passes"],
        "valid_attempts": cell["valid_attempts"],
        "integrity_failures": cell["integrity_failures"],
        "all_trials_pass": cell["all_trials_pass"],
    }


# ---------------------------------------------------------------------------
# summaries and exact tests
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _template_means(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for row in rows:
        groups.setdefault(row["template_id"], []).append(row[key])
    return {
        template_id: sum(values) / len(values)
        for template_id, values in sorted(groups.items())
    }


def _summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [row[key] for row in rows]
    template_means = _template_means(rows, key)
    case_weighted = _mean(values)
    template_weighted = _mean(list(template_means.values()))
    positive = sum(1 for value in values if value > SIGN_EPS)
    negative = sum(1 for value in values if value < -SIGN_EPS)
    ties = len(values) - positive - negative
    return {
        "n": len(values),
        "case_weighted_mean": case_weighted,
        "template_weighted_mean": template_weighted,
        "case_weighted_minus_template_weighted": (
            case_weighted - template_weighted
            if case_weighted is not None and template_weighted is not None
            else None
        ),
        "median": _median(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "positive": positive,
        "negative": negative,
        "ties": ties,
        "template_count": len(template_means),
    }


def _sign_test(positive: int, negative: int) -> dict[str, Any]:
    n = positive + negative
    if n == 0:
        return {
            "n_nonzero": 0,
            "two_sided_exact_binomial_p": None,
            "ties_omitted": True,
            "decision": None,
            "note": "no nonzero scenario changes; the sign test is undefined",
        }
    smaller = min(positive, negative)
    tail = sum(math.comb(n, i) for i in range(smaller + 1)) / (2**n)
    p_value = min(1.0, 2.0 * tail)
    return {
        "n_nonzero": n,
        "positive": positive,
        "negative": negative,
        "two_sided_exact_binomial_p": p_value,
        "ties_omitted": True,
        "decision": None,
        "note": "ties are omitted; no p-value threshold defines success",
    }


def _percentile(sorted_values: list[float], quantile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _interval(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "level": BOOTSTRAP_LEVEL,
        "lower": _percentile(ordered, (1.0 - BOOTSTRAP_LEVEL) / 2.0),
        "upper": _percentile(ordered, 1.0 - (1.0 - BOOTSTRAP_LEVEL) / 2.0),
        "method": "percentile_linear",
    }


def _bootstrap(
    rows: list[dict[str, Any]], seed: int, resamples: int
) -> dict[str, Any] | None:
    if not rows:
        return None

    keys = ("treatment_change", "control_drift", "difference_in_differences")
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["template_id"], []).append(row)
    templates = sorted(groups)
    template_count = len(templates)

    template_means: dict[str, dict[str, float]] = {}
    template_effects: list[dict[str, Any]] = []
    for template_id in templates:
        group = groups[template_id]
        means = {key: sum(row[key] for row in group) / len(group) for key in keys}
        template_means[template_id] = means
        template_effects.append(
            {
                "template_id": template_id,
                "scenarios": len(group),
                "treatment_change": means["treatment_change"],
                "control_drift": means["control_drift"],
                "difference_in_differences": means["difference_in_differences"],
            }
        )

    rng = random.Random(seed)
    draws: dict[str, list[float]] = {key: [] for key in keys}
    for _ in range(resamples):
        sampled = [rng.randrange(template_count) for _ in range(template_count)]
        for key in keys:
            total = sum(template_means[templates[index]][key] for index in sampled)
            draws[key].append(total / template_count)

    degenerate = template_count == 1
    return {
        "method": "percentile_template_cluster_bootstrap",
        "resampling_unit": "template_id",
        "estimand": "macro-average over templates, each template equally weighted",
        "seed": seed,
        "resamples": resamples,
        "template_count": template_count,
        "templates": template_effects,
        "single_template": degenerate,
        "degenerate": degenerate,
        "intervals": {key: _interval(draws[key]) for key in keys},
        "primary_metric": "difference_in_differences",
        "note": (
            "Only one template is present: every bootstrap draw is identical, so "
            "the interval is degenerate and cannot represent between-template uncertainty."
            if degenerate
            else "Templates are resampled with replacement; scenarios are not independent units."
        ),
    }


# ---------------------------------------------------------------------------
# report sections
# ---------------------------------------------------------------------------


def _build_aa_section(scenario_results: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [scenario for scenario in scenario_results if scenario["aa"] is not None]
    excluded = [
        {
            "scenario_id": scenario["scenario_id"],
            "template_id": scenario["template_id"],
            "cohort": scenario["cohort"],
            "missing_cells": scenario["missing_cells"],
            "incomplete_cells": scenario["incomplete_cells"],
            "reasons": scenario["exclusion_reasons"],
        }
        for scenario in scenario_results
        if scenario["aa"] is None
    ]

    def metrics(subset: list[dict[str, Any]]) -> dict[str, Any]:
        differences = [scenario["aa"]["absolute_difference"] for scenario in subset]
        signed = [scenario["aa"]["signed_difference"] for scenario in subset]
        strict = [
            scenario
            for scenario in subset
            if scenario["aa"]["strict_all_trials_pass_disagreement"]
        ]
        polarity = [
            scenario for scenario in subset if scenario["aa"]["polarity_disagreement"]
        ]
        return {
            "n": len(subset),
            "mean_absolute_difference": _mean(differences),
            "mean_signed_difference": _mean(signed),
            "median_absolute_difference": _median(differences),
            "max_absolute_difference": max(differences) if differences else None,
            "strict_all_trials_pass_disagreement_count": len(strict),
            "strict_all_trials_pass_disagreement_fraction": (
                len(strict) / len(subset) if subset else None
            ),
            "strict_all_trials_pass_disagreements": [
                {
                    "scenario_id": scenario["scenario_id"],
                    "treatment_all_trials_pass": scenario["aa"]["all_trials_pass_treatment"],
                    "control_all_trials_pass": scenario["aa"]["all_trials_pass_control"],
                }
                for scenario in strict
            ],
            "polarity_disagreement_count": len(polarity),
            "treatment_all_trials_pass_count": sum(
                1 for scenario in subset if scenario["aa"]["all_trials_pass_treatment"]
            ),
            "control_all_trials_pass_count": sum(
                1 for scenario in subset if scenario["aa"]["all_trials_pass_control"]
            ),
            "identity_verified_scenarios": sum(
                1 for scenario in subset if scenario["identity_verified"]
            ),
        }

    overall = metrics(eligible)
    by_cohort: dict[str, Any] = {}
    for cohort in COHORTS:
        by_cohort[cohort] = metrics(
            [scenario for scenario in eligible if scenario["cohort"] == cohort]
        )

    identity_identical = 0
    identity_different = 0
    identity_unknown = 0
    different_scenarios: list[str] = []
    for scenario in eligible:
        treat = scenario["cells"]["before/treatment"]["identity"]["expected"]
        control = scenario["cells"]["before/control"]["identity"]["expected"]
        relation = _identity_relation(treat, control)
        if relation == "unknown":
            identity_unknown += 1
        elif relation == "same":
            identity_identical += 1
        else:
            identity_different += 1
            different_scenarios.append(scenario["scenario_id"])

    return {
        "mode": "aa",
        "eligible_scenarios": [scenario["scenario_id"] for scenario in eligible],
        "n": overall["n"],
        **{key: value for key, value in overall.items() if key != "n"},
        "by_cohort": by_cohort,
        "excluded_scenarios": excluded,
        "identity_design": {
            "identical_declared_identity_scenarios": identity_identical,
            "different_declared_identity_scenarios": identity_different,
            "unknown_declared_identity_scenarios": identity_unknown,
            "different_scenarios": different_scenarios,
        },
        "interpretation": (
            "A/A differences are observed run-to-run variation. They include model "
            "randomness, ordering, and other noise; they are not pure build variance. "
            "A nonzero difference does not establish non-equivalence, and a zero "
            "difference does not establish equivalence."
        ),
        "equivalence_claim": False,
        "inferential": False,
    }


def _identity_change_for_scenario(
    plan: dict[str, Any], scenario: dict[str, Any]
) -> str:
    before = _expected_identity(plan, scenario, "before", "treatment")
    after = _expected_identity(plan, scenario, "after", "treatment")
    if before is None or after is None:
        return "unknown"
    if not any(value is not None for value in {**before, **after}.values()):
        return "unknown"
    relation = _identity_relation(before, after)
    if relation == "different":
        return "changed"
    if before == after:
        return "unchanged"
    return "unknown"


def _build_before_after_section(
    scenario_results: list[dict[str, Any]],
    plan: dict[str, Any],
    bootstrap: dict[str, Any] | None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for scenario in scenario_results:
        if scenario["comparison"] is None:
            excluded.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "template_id": scenario["template_id"],
                    "cohort": scenario["cohort"],
                    "missing_cells": scenario["missing_cells"],
                    "incomplete_cells": scenario["incomplete_cells"],
                    "reasons": scenario["exclusion_reasons"],
                }
            )
            continue
        row = {
            "scenario_id": scenario["scenario_id"],
            "template_id": scenario["template_id"],
            "cohort": scenario["cohort"],
            **scenario["comparison"],
            "identity_verified": scenario["identity_verified"],
            "treatment_identity_change": _identity_change_for_scenario(plan, scenario),
        }
        rows.append(row)

    treatment_change = _summary(rows, "treatment_change")
    treatment_change["sign_test"] = _sign_test(
        treatment_change["positive"], treatment_change["negative"]
    )

    control_drift = _summary(rows, "control_drift")
    did = _summary(rows, "difference_in_differences")
    did["primary_estimand"] = "template_weighted_mean"
    did["weighting"] = {
        "case_weighted": "each scenario weighted equally",
        "template_weighted": (
            "scenarios averaged within template, then templates weighted equally"
        ),
        "primary": "template_weighted",
        "case_weighted_minus_template_weighted": did[
            "case_weighted_minus_template_weighted"
        ],
    }

    if bootstrap is not None:
        treatment_change["bootstrap_interval"] = bootstrap["intervals"]["treatment_change"]
        control_drift["bootstrap_interval"] = bootstrap["intervals"]["control_drift"]
        did["bootstrap_interval"] = bootstrap["intervals"][
            "difference_in_differences"
        ]

    return {
        "included_scenarios": [row["scenario_id"] for row in rows],
        "n": len(rows),
        "excluded_scenarios": excluded,
        "per_scenario": rows,
        "treatment_change": treatment_change,
        "control_drift": control_drift,
        "difference_in_differences": did,
        "primary_estimand": "template_weighted_mean difference-in-differences",
    }


def _build_cohort_rates(
    scenario_results: list[dict[str, Any]],
    plan: dict[str, Any],
    phases: tuple[str, ...],
) -> dict[str, Any]:
    rates: dict[str, Any] = {}
    for cohort in COHORTS:
        cohort_scenarios = [
            scenario for scenario in plan["scenarios"] if scenario["cohort"] == cohort
        ]
        cohort_result: dict[str, Any] = {
            "scenarios_planned": len(cohort_scenarios),
        }
        for phase in phases:
            phase_result: dict[str, Any] = {}
            for arm in ARMS:
                cell_name = f"{phase}/{arm}"
                cells = [
                    scenario["cells"][cell_name]
                    for scenario in scenario_results
                    if scenario["cohort"] == cohort
                ]
                valid_attempts = sum(cell["valid_attempts"] for cell in cells)
                passes = sum(cell["passes"] for cell in cells)
                fractions = [
                    cell["pass_fraction"]
                    for cell in cells
                    if cell["pass_fraction"] is not None
                ]
                phase_result[arm] = {
                    "scenarios_with_valid_attempts": sum(
                        1 for cell in cells if cell["valid_attempts"] > 0
                    ),
                    "scenarios_complete": sum(1 for cell in cells if cell["complete"]),
                    "valid_attempts": valid_attempts,
                    "passes": passes,
                    "pooled_pass_fraction": (
                        passes / valid_attempts if valid_attempts else None
                    ),
                    "mean_scenario_pass_fraction": _mean(fractions),
                    "invalid_attempts": sum(cell["invalid_attempts"] for cell in cells),
                    "integrity_failures": sum(
                        cell["integrity_failures"] for cell in cells
                    ),
                }
            cohort_result[phase] = phase_result
        rates[cohort] = cohort_result
    return rates


def _collect_counts(
    records: list[dict[str, Any]],
    scenario_results: list[dict[str, Any]],
    phases: tuple[str, ...],
) -> dict[str, Any]:
    in_scope = tuple(phases)
    records_by_phase_arm: dict[str, int] = {}
    invalid_by_phase_arm: dict[str, int] = {}
    for phase in PHASES:
        for arm in ARMS:
            key = f"{phase}/{arm}"
            selected = [
                record
                for record in records
                if record["phase"] == phase and record["arm"] == arm
            ]
            records_by_phase_arm[key] = len(selected)
            invalid_by_phase_arm[key] = sum(
                1 for record in selected if record["status"] == "invalid"
            )

    analyzed_records = [record for record in records if record["phase"] in in_scope]
    ignored_records = [record for record in records if record["phase"] not in in_scope]

    cells = [
        cell
        for scenario in scenario_results
        for cell in scenario["cells"].values()
    ]

    return {
        "records_total": len(records),
        "records_valid": sum(1 for record in records if record["status"] == "valid"),
        "records_invalid": sum(1 for record in records if record["status"] == "invalid"),
        "records_in_scope": len(analyzed_records),
        "records_ignored": len(ignored_records),
        "records_by_phase_arm": records_by_phase_arm,
        "invalid_attempts": sum(
            1 for record in records if record["status"] == "invalid"
        ),
        "invalid_attempts_analyzed": sum(
            1 for record in analyzed_records if record["status"] == "invalid"
        ),
        "invalid_attempts_ignored": sum(
            1 for record in ignored_records if record["status"] == "invalid"
        ),
        "invalid_attempts_by_phase_arm": invalid_by_phase_arm,
        "missing_valid_trials": sum(len(cell["missing_trials"]) for cell in cells),
        "integrity_passes": sum(cell["integrity_passes"] for cell in cells),
        "integrity_failures": sum(cell["integrity_failures"] for cell in cells),
        "invalid_integrity_failures": sum(
            cell["invalid_integrity_failures"] for cell in cells
        ),
        "planned_cells": len(cells),
        "complete_planned_cells": sum(1 for cell in cells if cell["complete"]),
    }


def _build_identity_summary(
    scenario_results: list[dict[str, Any]],
    before_after: dict[str, Any] | None,
    aa_section: dict[str, Any] | None,
    phase_mode: str,
) -> dict[str, Any]:
    cells = [
        cell
        for scenario in scenario_results
        for cell in scenario["cells"].values()
    ]
    statuses = {"verified": 0, "unverified": 0, "undeclared": 0, "mismatch": 0, "no_valid_attempts": 0}
    for cell in cells:
        statuses[cell["identity"]["status"]] = statuses.get(cell["identity"]["status"], 0) + 1

    if phase_mode == "ab" and before_after is not None:
        included = before_after["per_scenario"]
        verified = sum(1 for row in included if row["identity_verified"])
        all_verified = bool(included) and verified == len(included)
        changes = {row["treatment_identity_change"] for row in included}
        if not included:
            treatment_change = "no_included_scenarios"
        elif changes == {"changed"}:
            treatment_change = "changed"
        elif changes == {"unchanged"}:
            treatment_change = "unchanged"
        elif changes == {"unknown"}:
            treatment_change = "unknown"
        else:
            treatment_change = "mixed"
    elif phase_mode == "aa" and aa_section is not None:
        included = [
            scenario for scenario in scenario_results if scenario["aa"] is not None
        ]
        verified = sum(1 for scenario in included if scenario["identity_verified"])
        all_verified = bool(included) and verified == len(included)
        treatment_change = "not_applicable"
    else:
        included = []
        verified = 0
        all_verified = False
        treatment_change = "not_applicable"

    return {
        "cells_total": len(cells),
        "cell_status_counts": statuses,
        "included_scenarios": len(included),
        "included_scenarios_identity_verified": verified,
        "all_included_scenarios_identity_verified": all_verified,
        "treatment_identity_change": treatment_change,
        "note": (
            "Identity is verified only when the plan declares a value and every valid "
            "attempt in the cell carries that same value. Missing values are not filled."
        ),
    }


# ---------------------------------------------------------------------------
# top-level analysis
# ---------------------------------------------------------------------------


def _assumptions() -> list[str]:
    return [
        "Only scenarios with all planned cells complete enter before/after comparisons; "
        "incomplete and unpaired scenarios are excluded and reported, never imputed.",
        "Before/after comparisons assume parallel trends: absent the treatment change, "
        "the treatment arm's scenario-level change would have averaged the same path as "
        "the control arm.",
        "One control arm and one rebuild do not remove all confounds. Concurrent model, "
        "platform, grader, prompt, scenario, rate-limit, and ordering changes can move "
        "the arms differently.",
        "Trials are repeat measurements, not independent experimental units, and are not "
        "paired across arms by trial index.",
        "The bootstrap resamples template groups, treating templates as exchangeable "
        "clusters. With few templates the interval is unstable; with one template it is "
        "degenerate.",
        "Trial outcomes include model randomness. Integrity failures are reported "
        "separately and are never converted into agent failures.",
        "Missing project_id/config_sha256 values block inferential claims; they are not "
        "imputed and the tool does not invent identities.",
        "No p-value threshold defines success, and the bootstrap is run once at the "
        "declared seed and resample count, never repeatedly until significance.",
        "Counts are small. This is a diagnostic report, not a guarantee of statistical "
        "power.",
    ]


def analyze(
    observations: Any,
    plan: Any,
    phase_mode: str = "ab",
    *,
    observations_path: str | None = None,
    plan_path: str | None = None,
) -> dict[str, Any]:
    """Validate inputs and return the analysis report as a plain dict."""
    if phase_mode not in PHASE_MODES:
        raise InputError(f"phase mode: expected one of {', '.join(PHASE_MODES)}")

    normalized_plan = validate_plan(plan)
    records = validate_observations(observations, normalized_plan)
    phases = ("before",) if phase_mode == "aa" else ("before", "after")

    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (record["scenario_id"], record["phase"], record["arm"])
        by_cell.setdefault(key, []).append(record)

    scenario_results = [
        _build_scenario(scenario, by_cell, normalized_plan, phase_mode)
        for scenario in normalized_plan["scenarios"]
    ]

    counts = _collect_counts(records, scenario_results, phases)
    cohort_rates = _build_cohort_rates(scenario_results, normalized_plan, phases)

    aa_section = _build_aa_section(scenario_results) if phase_mode == "aa" else None

    before_after = None
    bootstrap = None
    if phase_mode == "ab":
        provisional_rows = [
            {
                "scenario_id": scenario["scenario_id"],
                "template_id": scenario["template_id"],
                "cohort": scenario["cohort"],
                **scenario["comparison"],
            }
            for scenario in scenario_results
            if scenario["comparison"] is not None
        ]
        bootstrap = _bootstrap(
            provisional_rows,
            normalized_plan["bootstrap_seed"],
            normalized_plan["bootstrap_resamples"],
        )
        before_after = _build_before_after_section(
            scenario_results, normalized_plan, bootstrap
        )

    identity_summary = _build_identity_summary(
        scenario_results, before_after, aa_section, phase_mode
    )

    blocked_reasons: list[str] = []
    if phase_mode == "aa":
        inferential = False
        blocked_reasons.append(
            "A/A mode is a before-only diagnostic; it makes no before/after "
            "inferential claim and does not establish equivalence."
        )
    elif before_after is None or before_after["n"] == 0:
        inferential = False
        blocked_reasons.append(
            "No complete four-cell scenario is available for a before/after comparison."
        )
    elif not identity_summary["all_included_scenarios_identity_verified"]:
        inferential = False
        blocked_reasons.append(
            "One or more included cells lack a declared and matching project_id/"
            "config_sha256 identity; inferential attribution is blocked."
        )
    else:
        inferential = True

    warnings: list[str] = []
    if counts["invalid_attempts"] > 0:
        warnings.append(
            f"{counts['invalid_attempts']} invalid attempt(s) retained and counted; "
            "invalid attempts are not scored as failures."
        )
    if counts["missing_valid_trials"] > 0:
        warnings.append(
            f"{counts['missing_valid_trials']} planned valid trial(s) are missing; "
            "affected cells are incomplete."
        )
    if counts["integrity_failures"] > 0:
        warnings.append(
            f"{counts['integrity_failures']} valid attempt(s) failed integrity; "
            "integrity is reported separately from pass/fail."
        )
    if bootstrap is not None and bootstrap["single_template"]:
        warnings.append(
            "Only one template is present; the template-cluster bootstrap interval "
            "is degenerate."
        )
    if identity_summary["treatment_identity_change"] == "unchanged":
        warnings.append(
            "The declared treatment identity is unchanged between before and after; "
            "any observed contrast cannot be attributed to a declared build change."
        )
    if identity_summary["treatment_identity_change"] == "mixed":
        warnings.append(
            "Declared treatment identity changes differ across included scenarios; "
            "attribution is mixed."
        )
    if phase_mode == "aa" and aa_section is not None:
        if aa_section["identity_design"]["different_declared_identity_scenarios"] > 0:
            warnings.append(
                "Some A/A scenarios declare different treatment and control "
                "identities; their observed differences include build/config differences."
            )

    notes = [
        "Diagnostic only: counts are small and the report does not guarantee power.",
        "Trials are not paired across arms by index and are not independent experimental units.",
        "Invalid attempts are retained in the report and excluded from pass fractions; "
        "they are never silently treated as agent failures.",
        "Missing labels are never treated as passes.",
        "No p-value threshold defines success; the bootstrap is not repeated until significance.",
        "A/A differences include model randomness, not pure build variance.",
    ]

    plan_echo = {
        "scenario_count": len(normalized_plan["scenarios"]),
        "template_count": len(
            {scenario["template_id"] for scenario in normalized_plan["scenarios"]}
        ),
        "template_ids": sorted(
            {scenario["template_id"] for scenario in normalized_plan["scenarios"]}
        ),
        "cohort_counts": {
            cohort: sum(
                1 for scenario in normalized_plan["scenarios"] if scenario["cohort"] == cohort
            )
            for cohort in COHORTS
        },
        "trials_per_cell": {
            "min": min(scenario["trials"] for scenario in normalized_plan["scenarios"]),
            "max": max(scenario["trials"] for scenario in normalized_plan["scenarios"]),
        },
        "bootstrap_seed": normalized_plan["bootstrap_seed"],
        "bootstrap_resamples": normalized_plan["bootstrap_resamples"],
    }

    return {
        "schema_version": ANALYSIS_SCHEMA,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "phase_mode": phase_mode,
        "inputs": {
            "observations_path": observations_path,
            "plan_path": plan_path,
            "records": len(records),
        },
        "plan": plan_echo,
        "counts": counts,
        "scenarios": scenario_results,
        "cohort_rates": cohort_rates,
        "aa": aa_section,
        "before_after": before_after,
        "bootstrap": bootstrap,
        "identity": identity_summary,
        "claims": {
            "inferential": inferential,
            "descriptive_only": not inferential,
            "automatic_success": False,
            "decision": None,
            "p_value_rule": "none; no threshold defines success",
            "repeated_sampling_until_significance": False,
            "blocked_reasons": blocked_reasons,
        },
        "assumptions": _assumptions(),
        "warnings": warnings,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _fmt_p(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4g}"


def render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("agentplace pilot diagnostic analysis")
    lines.append(f"schema: {report['schema_version']}")
    lines.append(f"mode: {report['phase_mode']}")
    lines.append(
        "records: "
        f"{report['counts']['records_total']} total, "
        f"{report['counts']['records_valid']} valid, "
        f"{report['counts']['invalid_attempts']} invalid attempts retained"
    )
    lines.append(
        "missing valid trials: "
        f"{report['counts']['missing_valid_trials']}; "
        f"integrity failures: {report['counts']['integrity_failures']}; "
        f"planned cells complete: {report['counts']['complete_planned_cells']}/"
        f"{report['counts']['planned_cells']}"
    )
    lines.append(
        "bootstrap: seed="
        f"{report['plan']['bootstrap_seed']}, resamples="
        f"{report['plan']['bootstrap_resamples']} "
        "(no repeated sampling until significance)"
    )
    identity = report["identity"]
    lines.append(
        "identity: "
        f"{identity['included_scenarios_identity_verified']}/"
        f"{identity['included_scenarios']} included scenarios verified; "
        f"treatment identity {identity['treatment_identity_change']}"
    )
    lines.append(
        "inferential claims: "
        + ("available" if report["claims"]["inferential"] else "BLOCKED")
    )
    for reason in report["claims"]["blocked_reasons"]:
        lines.append(f"  blocked: {reason}")

    excluded = []
    if report["before_after"] is not None:
        excluded = report["before_after"]["excluded_scenarios"]
    elif report["aa"] is not None:
        excluded = report["aa"]["excluded_scenarios"]
    if excluded:
        lines.append("excluded scenarios:")
        for item in excluded:
            detail = "; ".join(item["reasons"]) if item["reasons"] else "not included"
            lines.append(f"  {item['scenario_id']}: {detail}")

    lines.append("cohort rates (pooled valid passes/trials; separate cohorts):")
    for cohort in COHORTS:
        cohort_data = report["cohort_rates"][cohort]
        lines.append(
            f"  {cohort}: {cohort_data['scenarios_planned']} planned scenarios"
        )
        for phase in ("before", "after"):
            if phase not in cohort_data:
                continue
            for arm in ARMS:
                cell = cohort_data[phase][arm]
                lines.append(
                    f"    {phase}/{arm}: "
                    f"{cell['passes']}/{cell['valid_attempts']} = "
                    f"{_fmt(cell['pooled_pass_fraction'])} pooled; "
                    f"mean scenario {_fmt(cell['mean_scenario_pass_fraction'])}; "
                    f"complete {cell['scenarios_complete']}"
                )

    if report["aa"] is not None:
        aa = report["aa"]
        lines.append(
            "A/A before-phase diagnostic: "
            f"n={aa['n']}, mean |difference|={_fmt(aa['mean_absolute_difference'])}, "
            f"max={_fmt(aa['max_absolute_difference'])}"
        )
        lines.append(
            "  strict all-trials-pass disagreements: "
            f"{aa['strict_all_trials_pass_disagreement_count']}/"
            f"{aa['n']} "
            f"({_fmt(aa['strict_all_trials_pass_disagreement_fraction'])})"
        )
        lines.append(
            "  not an equivalence claim; differences include model randomness."
        )
        for cohort in COHORTS:
            sub = aa["by_cohort"][cohort]
            lines.append(
                f"  {cohort}: n={sub['n']}, mean |difference|="
                f"{_fmt(sub['mean_absolute_difference'])}, "
                f"strict disagreements={sub['strict_all_trials_pass_disagreement_count']}"
            )

    if report["before_after"] is not None:
        section = report["before_after"]
        treatment = section["treatment_change"]
        control = section["control_drift"]
        did = section["difference_in_differences"]
        lines.append(f"before/after (complete four-cell scenarios, n={section['n']}):")
        lines.append(
            "  treatment change: case-weighted "
            f"{_fmt(treatment['case_weighted_mean'])}, template-weighted "
            f"{_fmt(treatment['template_weighted_mean'])}; "
            f"signs +{treatment['positive']}/-{treatment['negative']}/"
            f"ties {treatment['ties']}; exact sign p="
            f"{_fmt_p(treatment['sign_test']['two_sided_exact_binomial_p'])}"
        )
        lines.append(
            "  control drift: case-weighted "
            f"{_fmt(control['case_weighted_mean'])}, template-weighted "
            f"{_fmt(control['template_weighted_mean'])}"
        )
        lines.append(
            "  difference-in-differences: case-weighted "
            f"{_fmt(did['case_weighted_mean'])}, template-weighted "
            f"{_fmt(did['template_weighted_mean'])}"
        )
        interval = did.get("bootstrap_interval")
        if interval is not None:
            lines.append(
                "  95% template-cluster bootstrap interval: "
                f"[{_fmt(interval['lower'])}, {_fmt(interval['upper'])}]"
            )
        lines.append(
            "  explicit weighting difference (case minus template): "
            f"{_fmt(did['case_weighted_minus_template_weighted'])}"
        )
        if report["bootstrap"] is not None:
            lines.append("  template effects:")
            for item in report["bootstrap"]["templates"]:
                lines.append(
                    f"    {item['template_id']} ({item['scenarios']} scenarios): "
                    f"treatment {_fmt(item['treatment_change'])}, "
                    f"control {_fmt(item['control_drift'])}, "
                    f"difference-in-differences {_fmt(item['difference_in_differences'])}"
                )

    lines.append("assumptions:")
    for assumption in report["assumptions"]:
        lines.append(f"  - {assumption}")
    if report["warnings"]:
        lines.append("warnings:")
        for warning in report["warnings"]:
            lines.append(f"  - {warning}")
    lines.append("notes:")
    for note in report["notes"]:
        lines.append(f"  - {note}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _reject_constant(value: str) -> Any:
    raise InputError(f"non-finite JSON number {value!r} is not allowed")


def _load_json(path: str, label: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle, parse_constant=_reject_constant)
    except InputError:
        raise
    except FileNotFoundError:
        raise InputError(f"{label}: file not found: {path}") from None
    except json.JSONDecodeError as error:
        raise InputError(f"{label}: invalid JSON in {path}: {error}") from None
    except UnicodeDecodeError as error:
        raise InputError(f"{label}: {path} is not valid UTF-8: {error}") from None
    except OSError as error:
        raise InputError(f"{label}: cannot read {path}: {error}") from None


def _parser() -> argparse.ArgumentParser:
    epilog = """\
Input schema (observations):
  schema_version must be "agentplace.pilot.observations.v1".
  Each record: scenario_id, template_id, cohort (targeted|tripwire),
  phase (before|after), arm (treatment|control), trial (positive integer),
  status (valid|invalid), integrity_pass, complete_pass,
  project_id and config_sha256 (optional but required for identity verification).

Plan schema:
  schema_version (optional) "agentplace.pilot.plan.v1",
  bootstrap_seed, bootstrap_resamples,
  scenarios: [{id, template_id, cohort, trials, identities?}],
  identities? or required_identities?: {phase: {arm: {project_id?, config_sha256?}}}.

Read-only by default.  --out writes one new file and refuses to overwrite.
"""
    parser = argparse.ArgumentParser(
        prog="analyze_pilot.py",
        description=(
            "Read-only scenario-level diagnostic for the agentplace pilot. "
            "Reports trial pass fractions, A/A noise, before/after changes, "
            "difference-in-differences, and template-cluster bootstrap intervals."
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--observations",
        required=True,
        help="canonical observations JSON (agentplace.pilot.observations.v1)",
    )
    parser.add_argument(
        "--plan",
        required=True,
        help="plan JSON with scenarios, bootstrap_seed, and bootstrap_resamples",
    )
    parser.add_argument(
        "--phase",
        choices=PHASE_MODES,
        default="ab",
        help="ab: complete before/after analysis; aa: before-only A/A diagnostic",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="stdout/output-file format (default: text)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="optional new output file; refuses to overwrite an existing path",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{TOOL_NAME} {TOOL_VERSION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.out is not None:
        output = Path(args.out)
        if output.exists():
            print(
                f"error: refusing to overwrite existing output path: {args.out}",
                file=sys.stderr,
            )
            return 3

    try:
        observations = _load_json(args.observations, "observations")
        plan = _load_json(args.plan, "plan")
        report = analyze(
            observations,
            plan,
            args.phase,
            observations_path=args.observations,
            plan_path=args.plan,
        )
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    rendered = render_json(report) if args.format == "json" else render_text(report)

    if args.out is None:
        sys.stdout.write(rendered)
        return 0

    try:
        with open(args.out, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
    except FileExistsError:
        print(
            f"error: refusing to overwrite existing output path: {args.out}",
            file=sys.stderr,
        )
        return 3
    except OSError as error:
        print(f"error: cannot write {args.out}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
