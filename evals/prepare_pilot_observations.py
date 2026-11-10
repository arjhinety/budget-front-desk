#!/usr/bin/env python3
"""
Offline bridge from old-style paired captures to canonical pilot observations.

This is a preparation-only adapter.  It does not start a browser, call a
network service, run a grader, or invent a verdict.  It reads four raw capture
stores plus four prospective grading receipts and writes one canonical
`agentplace.pilot.observations.v1` file in a single new path.

Why a bridge
------------
The paired executor (`evals/run.mjs` / `evals/run_paired.mjs`) records the
old store shape:

    {
      "arm": "A0",
      "agent": "...",
      "records": [
        {
          "id": "T01",
          "trial": 1,
          "attempt": 1,
          "status": "valid" | "invalid",
          "provenance": {
            "schema": "agentplace-record-provenance-v1",
            "scenario_id": "T01",
            "trial": 1,
            "phase": "before",
            "arm": "A0",
            "project_id": "...",
            "config_hash": "..."
          }
        }
      ]
    }

Those names are the names emitted by `evals/provenance.mjs`
(`makeRecordProvenance`) and `evals/run.mjs`.  This adapter does not guess any
alternative field name.  If a capture carries `legacy_unverified` provenance
or omits a required binding, it refuses the file.

The analyser (`evals/analyze_pilot.py`) needs one row per attempt in the
canonical shape:

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
          "integrity_pass": true | false | null,
          "complete_pass": true | false | null,
          "project_id": "..." | null,
          "config_sha256": "..." | null
        }
      ]
    }

Verdicts for valid attempts come only from a prospective grading receipt.  An
invalid attempt is retained with `integrity_pass: null` and
`complete_pass: null`; it is never converted into an agent failure and it must
not have a grade row.

Grading receipt schema
----------------------
    {
      "schema": "agentplace-graded-capture-v1",   # or schema_version
      "source_capture_sha256": "<actual raw capture file sha256>",
      "grader_sha256": "<prospective grader sha256>",
      "records": [
        {
          "id": "T01",
          "trial": 1,
          "attempt": 1,
          "integrity_pass": true,
          "complete_pass": false
        }
      ]
    }

The receipt is produced by the future prospective case/grader stage.  This
adapter consumes it as evidence.  It does not pretend that the old
`evals/grade.py` handles new private files, and it does not run any grader.
Tests use synthetic receipts only.  Real new-data grading remains blocked
until prospective cases, graders and control results exist.

Bindings and refusals
---------------------
* Exactly four capture cells are required: `before:treatment`,
  `before:control`, `after:treatment`, `after:control` (and four matching
  grade cells).  Duplicate or missing cells are refusals.
* `source_capture_sha256` must equal the SHA-256 of the exact capture file
  bytes.  It is not accepted from the plan or recomputed from a re-serialised
  object.
* `grader_sha256` must match the plan-declared prospective grader when the
  plan declares one.  If the plan declares none, the receipt hash is recorded
  but explicitly marked unbound.
* Record `id`, `trial` and `attempt`, and provenance `scenario_id`, `trial`,
  `phase` and `arm`, must agree with the cell label and the plan.  Scenario
  template/cohort/trials metadata comes from the plan.
* `provenance.project_id` and `provenance.config_hash` are copied as
  `project_id` and `config_sha256`.  If the plan declares expected values, a
  present raw value must match; a missing raw value stays null and is reported
  as a limitation.  Expected values are never written into the output as if
  they had been observed.
* Duplicate attempt keys within a cell, and more than one valid attempt for the
  same scenario/trial, are refusals.
* Every valid capture must have exactly one grade row with the same
  `(id, trial, attempt)`.  Missing rows, extra rows, duplicate rows and rows
  for invalid attempts are refusals.
* The plan may declare `arm_map` when the raw provenance arm is not the
  canonical `treatment`/`control` label:

      "arm_map": {"before": {"treatment": "A0", "control": "A2"},
                  "after":  {"treatment": "A5", "control": "A2"}}

  or a flat `{"treatment": "A0", "control": "A2"}` for both phases.  Without a
  declared mapping, `provenance.arm` must literally be `treatment` or
  `control`.  No arm mapping is guessed.

CLI
---
    python evals/prepare_pilot_observations.py \
        --plan analysis-plan.json \
        --capture before:treatment=cap-before-treatment.json \
        --capture before:control=cap-before-control.json \
        --capture after:treatment=cap-after-treatment.json \
        --capture after:control=cap-after-control.json \
        --grades before:treatment=grade-before-treatment.json \
        --grades before:control=grade-before-control.json \
        --grades after:treatment=grade-after-treatment.json \
        --grades after:control=grade-after-control.json \
        --out observations.json

`--out` is required, writes only a new file, and refuses to overwrite anything.
`--help` reads and writes nothing.  On success the only write is the chosen
output path.  Exit codes: 0 wrote the file, 2 invalid input/binding, 3 refused
to overwrite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

# The adapter and analyser live in the same directory.  Running this file
# directly puts that directory on sys.path; importing it as a package does not.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from analyze_pilot import (  # noqa: E402
    InputError,
    OBSERVATIONS_SCHEMA,
    _expected_identity,
    validate_plan,
)

TOOL_NAME = "prepare_pilot_observations"
TOOL_VERSION = "1.0.0"
RECEIPT_SCHEMA = "agentplace-graded-capture-v1"
RAW_PROVENANCE_SCHEMA = "agentplace-record-provenance-v1"

PHASES = ("before", "after")
ARMS = ("treatment", "control")
STATUSES = ("valid", "invalid")
CELL_LABELS = tuple(f"{phase}/{arm}" for phase in PHASES for arm in ARMS)

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


# ---------------------------------------------------------------------------
# small validation helpers
# ---------------------------------------------------------------------------


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{where}: expected a non-empty string")
    return value.strip()


def _positive_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InputError(f"{where}: expected a positive integer")
    return value


def _boolean(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise InputError(f"{where}: expected true or false")
    return value


def _enum(value: Any, allowed: tuple[str, ...], where: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InputError(f"{where}: expected one of {', '.join(allowed)}")
    return value


def _hex64(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value.strip()):
        raise InputError(f"{where}: expected a 64-character hexadecimal sha256")
    return value.strip().lower()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: str | Path, label: str) -> tuple[Any, str, int]:
    """Read bytes once; return (object, sha256, byte count)."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        raise InputError(f"{label}: file not found: {path}") from None
    except OSError as error:
        raise InputError(f"{label}: cannot read {path}: {error}") from None

    digest = _sha256_bytes(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InputError(f"{label}: {path} is not valid UTF-8: {error}") from None

    def reject_constant(value: str) -> Any:
        raise InputError(f"{label}: non-finite JSON number {value!r} is not allowed")

    try:
        parsed = json.loads(text, parse_constant=reject_constant)
    except InputError:
        raise
    except json.JSONDecodeError as error:
        raise InputError(f"{label}: invalid JSON in {path}: {error}") from None
    return parsed, digest, len(data)


def _normalise_cell_paths(
    paths: Mapping[str, str | Path], flag: str
) -> dict[str, str]:
    if not isinstance(paths, Mapping):
        raise InputError(f"{flag}: expected a mapping of phase/arm to path")

    out: dict[str, str] = {}
    for raw_label, raw_path in paths.items():
        label = str(raw_label).replace(":", "/")
        parts = label.split("/")
        if len(parts) != 2:
            raise InputError(f"{flag}: cell label {raw_label!r} must be phase:arm or phase/arm")
        phase, arm = parts
        if phase not in PHASES or arm not in ARMS:
            raise InputError(
                f"{flag}: unknown cell {raw_label!r}; expected one of "
                f"{', '.join(CELL_LABELS)}"
            )
        canonical = f"{phase}/{arm}"
        if canonical in out:
            raise InputError(f"{flag}: duplicate cell {canonical}")
        if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
            raise InputError(f"{flag}.{canonical}: expected a non-empty file path")
        out[canonical] = str(raw_path)

    missing = [label for label in CELL_LABELS if label not in out]
    extra = [label for label in out if label not in CELL_LABELS]
    if missing:
        raise InputError(f"{flag}: missing cell(s): {', '.join(missing)}")
    if extra:
        raise InputError(f"{flag}: unknown cell(s): {', '.join(extra)}")
    return {label: out[label] for label in CELL_LABELS}


# ---------------------------------------------------------------------------
# plan-declared binding material
# ---------------------------------------------------------------------------


def _plan_grader_sha256(plan: dict[str, Any]) -> str | None:
    """Return the one declared prospective grader hash, if any.

    Accepted declarations:
      prospective_grader_sha256
      grader_sha256
      prospective_grader: "<hash>" | {"sha256": "<hash>"} | {"grader_sha256": "<hash>"}
    """
    candidates: list[tuple[str, Any]] = []
    for key in ("prospective_grader_sha256", "grader_sha256"):
        if plan.get(key) is not None:
            candidates.append((key, plan[key]))

    if plan.get("prospective_grader") is not None:
        declaration = plan["prospective_grader"]
        if isinstance(declaration, str):
            candidates.append(("prospective_grader", declaration))
        elif isinstance(declaration, dict):
            found = False
            for key in ("sha256", "grader_sha256"):
                if declaration.get(key) is not None:
                    candidates.append((f"prospective_grader.{key}", declaration[key]))
                    found = True
            if not found:
                raise InputError(
                    "plan.prospective_grader: object has no sha256/grader_sha256 field"
                )
        else:
            raise InputError("plan.prospective_grader: expected a string or object")

    if not candidates:
        return None

    normalised = {_hex64(value, f"plan.{where}") for where, value in candidates}
    if len(normalised) != 1:
        raise InputError(
            "plan: conflicting prospective grader declarations: "
            + ", ".join(sorted(normalised))
        )
    return next(iter(normalised))


def _plan_arm_map(plan: dict[str, Any]) -> dict[tuple[str, str], str]:
    """Resolve an explicit arm-to-source-arm mapping.

    Returns a mapping keyed by (phase, arm).  A missing entry means the raw
    provenance arm must equal the canonical arm label.  Nothing is inferred.
    """
    declarations: list[tuple[str, Any]] = []
    for key in ("arm_map", "source_arm_map"):
        if plan.get(key) is not None:
            declarations.append((key, plan[key]))
    if not declarations:
        return {}
    if len(declarations) > 1:
        raise InputError("plan: use only one of arm_map or source_arm_map")

    where, raw = declarations[0]
    if not isinstance(raw, dict):
        raise InputError(f"plan.{where}: expected an object")
    if not raw:
        return {}

    nested = any(isinstance(value, dict) for value in raw.values())
    if nested:
        if any(not isinstance(value, dict) for value in raw.values()):
            raise InputError(f"plan.{where}: cannot mix flat and phase-nested mappings")
        out: dict[tuple[str, str], str] = {}
        for phase, arms in raw.items():
            if phase not in PHASES:
                raise InputError(f"plan.{where}: unknown phase {phase!r}")
            for arm, source in arms.items():
                if arm not in ARMS:
                    raise InputError(f"plan.{where}.{phase}: unknown arm {arm!r}")
                out[(phase, arm)] = _string(
                    source, f"plan.{where}.{phase}.{arm}"
                )
        for phase in PHASES:
            values = [out[(phase, arm)] for arm in ARMS if (phase, arm) in out]
            if len(values) == 2 and values[0] == values[1]:
                raise InputError(
                    f"plan.{where}.{phase}: treatment and control map to the same source arm"
                )
        return out

    out = {}
    for arm, source in raw.items():
        if arm not in ARMS:
            raise InputError(f"plan.{where}: unknown arm {arm!r}")
        source = _string(source, f"plan.{where}.{arm}")
        for phase in PHASES:
            out[(phase, arm)] = source
    if not all((phase, arm) in out for phase in PHASES for arm in ARMS):
        raise InputError(
            f"plan.{where}: a flat arm_map must declare both treatment and control"
        )
    if out[("before", "treatment")] == out[("before", "control")]:
        raise InputError(
            f"plan.{where}: treatment and control map to the same source arm"
        )
    return out


# ---------------------------------------------------------------------------
# capture validation
# ---------------------------------------------------------------------------


def _read_capture(
    path: str,
    cell_label: str,
    plan: dict[str, Any],
    arm_map: dict[tuple[str, str], str],
) -> dict[str, Any]:
    phase, arm = cell_label.split("/")
    data, digest, size = _load_json(path, f"capture {cell_label}")

    if not isinstance(data, dict):
        raise InputError(f"capture {cell_label}: expected a JSON object")
    records_raw = data.get("records")
    if not isinstance(records_raw, list):
        raise InputError(f"capture {cell_label}: records must be a list")

    parsed: list[dict[str, Any]] = []
    attempt_keys: set[tuple[str, int, int]] = set()
    valid_by_scenario_trial: dict[tuple[str, int], int] = {}
    valid_keys: set[tuple[str, int, int]] = set()
    observed_projects: set[str] = set()
    observed_configs: set[str] = set()
    expected_source_arm = arm_map.get((phase, arm), arm)

    for index, record in enumerate(records_raw):
        where = f"capture {cell_label}.records[{index}]"
        if not isinstance(record, dict):
            raise InputError(f"{where}: expected an object")

        sid = _string(record.get("id"), f"{where}.id")
        trial = _positive_int(record.get("trial"), f"{where}.trial")
        attempt = _positive_int(record.get("attempt"), f"{where}.attempt")
        status = _enum(record.get("status"), STATUSES, f"{where}.status")

        provenance = record.get("provenance")
        if not isinstance(provenance, dict):
            raise InputError(f"{where}.provenance: expected an object")
        if provenance.get("legacy_unverified"):
            raise InputError(
                f"{where}.provenance: legacy_unverified records have no bindable "
                "scenario/phase/config; refusing to manufacture provenance"
            )
        if provenance.get("schema") is not None:
            schema = provenance.get("schema")
            if schema != RAW_PROVENANCE_SCHEMA:
                raise InputError(
                    f"{where}.provenance.schema: expected {RAW_PROVENANCE_SCHEMA!r}, "
                    f"got {schema!r}"
                )

        prov_sid = _string(provenance.get("scenario_id"), f"{where}.provenance.scenario_id")
        prov_trial = _positive_int(provenance.get("trial"), f"{where}.provenance.trial")
        prov_phase = _enum(provenance.get("phase"), PHASES, f"{where}.provenance.phase")
        prov_arm = _string(provenance.get("arm"), f"{where}.provenance.arm")

        if prov_sid != sid:
            raise InputError(
                f"{where}: record id {sid!r} does not match provenance.scenario_id {prov_sid!r}"
            )
        if prov_trial != trial:
            raise InputError(
                f"{where}: record trial {trial} does not match provenance.trial {prov_trial}"
            )
        if prov_phase != phase:
            raise InputError(
                f"{where}: provenance.phase {prov_phase!r} does not match cell phase {phase!r}"
            )
        if prov_arm != expected_source_arm:
            hint = (
                "declare plan.arm_map and do not guess an arm mapping"
                if not arm_map
                else f"the plan maps {cell_label} to source arm {expected_source_arm!r}"
            )
            raise InputError(
                f"{where}: provenance.arm {prov_arm!r} does not match expected source arm "
                f"{expected_source_arm!r}; {hint}"
            )

        if sid not in plan["by_id"]:
            raise InputError(f"{where}.id: scenario {sid!r} is not declared in the plan")
        scenario = plan["by_id"][sid]
        if trial > scenario["trials"]:
            raise InputError(
                f"{where}.trial: trial {trial} exceeds planned trials "
                f"{scenario['trials']} for scenario {sid!r}"
            )

        if status == "valid" and record.get("error"):
            raise InputError(
                f"{where}: status is valid but an error field is present; "
                "the raw capture is self-contradictory"
            )

        project_id = provenance.get("project_id")
        if project_id is not None:
            project_id = _string(project_id, f"{where}.provenance.project_id")
        config_hash = provenance.get("config_hash")
        if config_hash is not None:
            config_hash = _string(config_hash, f"{where}.provenance.config_hash")

        expected = _expected_identity(plan, scenario, phase, arm)
        if expected is not None:
            if (
                expected["project_id"] is not None
                and project_id is not None
                and project_id != expected["project_id"]
            ):
                raise InputError(
                    f"{where}.provenance.project_id: {project_id!r} does not match "
                    f"plan-declared identity {expected['project_id']!r} for "
                    f"({sid}, {phase}, {arm})"
                )
            if (
                expected["config_sha256"] is not None
                and config_hash is not None
                and config_hash.strip().lower() != expected["config_sha256"].strip().lower()
            ):
                raise InputError(
                    f"{where}.provenance.config_hash: {config_hash!r} does not match "
                    f"plan-declared identity {expected['config_sha256']!r} for "
                    f"({sid}, {phase}, {arm})"
                )

        attempt_key = (sid, trial, attempt)
        if attempt_key in attempt_keys:
            raise InputError(
                f"{where}: duplicate attempt key {sid}#{trial}/attempt {attempt} "
                "within this cell; refusing an ambiguous capture"
            )
        attempt_keys.add(attempt_key)

        if status == "valid":
            pair_key = (sid, trial)
            if pair_key in valid_by_scenario_trial:
                raise InputError(
                    f"{where}: duplicate valid attempt for {sid}#{trial} "
                    f"(attempts {valid_by_scenario_trial[pair_key]} and {attempt}); "
                    "a cell may have only one valid attempt per scenario/trial"
                )
            valid_by_scenario_trial[pair_key] = attempt
            valid_keys.add(attempt_key)
            if project_id is not None:
                observed_projects.add(project_id)
            if config_hash is not None:
                observed_configs.add(config_hash.strip().lower())

        parsed.append(
            {
                "scenario_id": sid,
                "template_id": scenario["template_id"],
                "cohort": scenario["cohort"],
                "phase": phase,
                "arm": arm,
                "trial": trial,
                "attempt": attempt,
                "status": status,
                "project_id": project_id,
                "config_sha256": config_hash,
                "expected_identity": expected,
            }
        )

    if len(observed_projects) > 1:
        raise InputError(
            f"capture {cell_label}: inconsistent project_id within valid records: "
            f"{sorted(observed_projects)}"
        )
    if len(observed_configs) > 1:
        raise InputError(
            f"capture {cell_label}: inconsistent config_hash within valid records: "
            f"{sorted(observed_configs)}"
        )

    return {
        "path": path,
        "sha256": digest,
        "bytes": size,
        "records": parsed,
        "valid_keys": valid_keys,
        "valid_by_scenario_trial": valid_by_scenario_trial,
        "counts": {
            "records": len(parsed),
            "valid": sum(1 for row in parsed if row["status"] == "valid"),
            "invalid": sum(1 for row in parsed if row["status"] == "invalid"),
        },
    }


# ---------------------------------------------------------------------------
# grading receipt validation
# ---------------------------------------------------------------------------


def _receipt_schema(data: dict[str, Any], cell_label: str) -> str:
    schema = data.get("schema")
    schema_version = data.get("schema_version")
    if schema is not None and schema_version is not None and schema != schema_version:
        raise InputError(
            f"grades {cell_label}: schema and schema_version disagree"
        )
    value = schema if schema is not None else schema_version
    if value != RECEIPT_SCHEMA:
        raise InputError(
            f"grades {cell_label}.schema: expected {RECEIPT_SCHEMA!r}, got {value!r}"
        )
    return value  # type: ignore[return-value]


def _read_grades(
    path: str,
    cell_label: str,
    capture_sha256: str,
    declared_grader: str | None,
) -> dict[str, Any]:
    data, digest, size = _load_json(path, f"grades {cell_label}")
    if not isinstance(data, dict):
        raise InputError(f"grades {cell_label}: expected a JSON object")

    schema = _receipt_schema(data, cell_label)

    source = _hex64(
        data.get("source_capture_sha256"),
        f"grades {cell_label}.source_capture_sha256",
    )
    if source != capture_sha256:
        raise InputError(
            f"grades {cell_label}.source_capture_sha256: {source} does not match "
            f"the actual capture file hash {capture_sha256}"
        )

    grader = _hex64(data.get("grader_sha256"), f"grades {cell_label}.grader_sha256")
    if declared_grader is not None and grader != declared_grader:
        raise InputError(
            f"grades {cell_label}.grader_sha256: {grader} does not match the "
            f"plan-declared prospective grader {declared_grader}"
        )

    rows_raw = data.get("records")
    if not isinstance(rows_raw, list):
        raise InputError(f"grades {cell_label}: records must be a list")

    rows: dict[tuple[str, int, int], dict[str, bool]] = {}
    for index, row in enumerate(rows_raw):
        where = f"grades {cell_label}.records[{index}]"
        if not isinstance(row, dict):
            raise InputError(f"{where}: expected an object")
        sid = _string(row.get("id"), f"{where}.id")
        trial = _positive_int(row.get("trial"), f"{where}.trial")
        attempt = _positive_int(row.get("attempt"), f"{where}.attempt")
        integrity = _boolean(row.get("integrity_pass"), f"{where}.integrity_pass")
        complete = _boolean(row.get("complete_pass"), f"{where}.complete_pass")
        key = (sid, trial, attempt)
        if key in rows:
            raise InputError(
                f"{where}: duplicate grade row {sid}#{trial}/attempt {attempt}; "
                "grading must be unambiguous"
            )
        rows[key] = {"integrity_pass": integrity, "complete_pass": complete}

    return {
        "path": path,
        "sha256": digest,
        "bytes": size,
        "schema": schema,
        "source_capture_sha256": source,
        "grader_sha256": grader,
        "records": rows,
        "counts": {"records": len(rows)},
    }


def _format_keys(keys: set[tuple[str, int, int]], limit: int = 6) -> str:
    ordered = sorted(keys)
    shown = [f"{sid}#{trial}/attempt {attempt}" for sid, trial, attempt in ordered[:limit]]
    suffix = f" (+{len(ordered) - limit} more)" if len(ordered) > limit else ""
    return ", ".join(shown) + suffix


def _match_grades(
    cell_label: str,
    capture: dict[str, Any],
    grades: dict[str, Any],
) -> dict[tuple[str, int, int], dict[str, bool]]:
    valid_keys = capture["valid_keys"]
    grade_keys = set(grades["records"])
    missing = valid_keys - grade_keys
    extra = grade_keys - valid_keys

    if missing:
        raise InputError(
            f"grades {cell_label}: missing grade row(s) for valid capture(s): "
            f"{_format_keys(missing)}"
        )
    if extra:
        raise InputError(
            f"grades {cell_label}: extra grade row(s) that match no valid capture: "
            f"{_format_keys(extra)}"
        )
    return grades["records"]


# ---------------------------------------------------------------------------
# top-level preparation
# ---------------------------------------------------------------------------


def prepare(
    plan_path: str | Path,
    capture_paths: Mapping[str, str | Path],
    grade_paths: Mapping[str, str | Path],
) -> dict[str, Any]:
    """Validate four cells and return one canonical observations object.

    Reads only the supplied paths; writes nothing.
    """
    captures = _normalise_cell_paths(capture_paths, "capture")
    grades = _normalise_cell_paths(grade_paths, "grades")

    plan_raw, plan_sha256, plan_bytes = _load_json(plan_path, "plan")
    if not isinstance(plan_raw, dict):
        raise InputError("plan: expected a JSON object")
    try:
        plan = validate_plan(plan_raw)
    except InputError as error:
        raise InputError(str(error)) from None

    declared_grader = _plan_grader_sha256(plan_raw)
    arm_map = _plan_arm_map(plan_raw)

    capture_results: dict[str, dict[str, Any]] = {}
    grade_results: dict[str, dict[str, Any]] = {}
    output_records: list[dict[str, Any]] = []

    valid_missing_identity = 0
    valid_without_plan_identity = 0
    expected_identity_without_raw = 0
    total_valid = 0
    total_invalid = 0

    for cell_label in CELL_LABELS:
        capture = _read_capture(
            captures[cell_label], cell_label, plan, arm_map
        )
        receipt = _read_grades(
            grades[cell_label],
            cell_label,
            capture["sha256"],
            declared_grader,
        )
        matched = _match_grades(cell_label, capture, receipt)

        capture_results[cell_label] = {
            "path": capture["path"],
            "sha256": capture["sha256"],
            "bytes": capture["bytes"],
            **capture["counts"],
        }
        grade_results[cell_label] = {
            "path": receipt["path"],
            "sha256": receipt["sha256"],
            "bytes": receipt["bytes"],
            "schema": receipt["schema"],
            "source_capture_sha256": receipt["source_capture_sha256"],
            "grader_sha256": receipt["grader_sha256"],
            "records": receipt["counts"]["records"],
        }

        for row in sorted(
            capture["records"],
            key=lambda item: (
                item["scenario_id"],
                item["trial"],
                item["attempt"],
                0 if item["status"] == "valid" else 1,
            ),
        ):
            key = (row["scenario_id"], row["trial"], row["attempt"])
            valid = row["status"] == "valid"
            if valid:
                total_valid += 1
                verdict = matched[key]
                if row["project_id"] is None or row["config_sha256"] is None:
                    valid_missing_identity += 1
                if row["expected_identity"] is None:
                    valid_without_plan_identity += 1
                elif any(
                    row["expected_identity"][field] is not None
                    and row[field] is None
                    for field in ("project_id", "config_sha256")
                ):
                    expected_identity_without_raw += 1
                integrity_pass: bool | None = verdict["integrity_pass"]
                complete_pass: bool | None = verdict["complete_pass"]
            else:
                total_invalid += 1
                integrity_pass = None
                complete_pass = None

            output_records.append(
                {
                    "scenario_id": row["scenario_id"],
                    "template_id": row["template_id"],
                    "cohort": row["cohort"],
                    "phase": row["phase"],
                    "arm": row["arm"],
                    "trial": row["trial"],
                    "status": row["status"],
                    "integrity_pass": integrity_pass,
                    "complete_pass": complete_pass,
                    "project_id": row["project_id"],
                    "config_sha256": row["config_sha256"],
                    # Extra audit field: the canonical analyser ignores it, but
                    # it preserves which retained attempt this row describes.
                    "attempt": row["attempt"],
                }
            )

    limitations: list[str] = []
    limitations.append(
        "This bridge copies verdicts from supplied prospective grading receipts; "
        "it does not run a grader, score a reply, or invent a verdict."
    )
    limitations.append(
        "Real new-data grading remains blocked until prospective cases, graders "
        "and control results exist; this file is preparation evidence only."
    )
    limitations.append(
        "Each receipt source_capture_sha256 was checked against the exact raw "
        "capture bytes."
    )
    if declared_grader is None:
        limitations.append(
            "The plan declares no prospective grader SHA-256; receipt grader "
            "hashes are recorded but are not bound to a frozen declaration."
        )
    else:
        limitations.append(
            "Every receipt grader_sha256 matched the plan-declared prospective "
            f"grader {declared_grader}."
        )
    if arm_map:
        limitations.append(
            "Raw provenance arms were bound to canonical treatment/control arms "
            "through the plan's explicit arm_map; no arm mapping was guessed."
        )
    else:
        limitations.append(
            "Raw provenance arm values matched the canonical treatment/control "
            "labels directly; no arm mapping was declared or guessed."
        )
    if total_invalid:
        limitations.append(
            f"{total_invalid} invalid capture attempt(s) retained with null "
            "integrity/complete outcomes; they are not agent failures."
        )
    if valid_missing_identity:
        limitations.append(
            f"{valid_missing_identity} valid capture record(s) carried no raw "
            "project_id/config_hash; output leaves them null and identity "
            "verification will be blocked for affected cells."
        )
    if valid_without_plan_identity:
        limitations.append(
            f"The plan declares no expected identity for {valid_without_plan_identity} "
            "valid capture record(s); raw identity is recorded but unverified."
        )
    if expected_identity_without_raw:
        limitations.append(
            f"{expected_identity_without_raw} valid capture record(s) have a "
            "plan-declared identity but no matching raw observation; expected "
            "values were not written into the output."
        )
    empty_cells = [
        label for label in CELL_LABELS if capture_results[label]["records"] == 0
    ]
    if empty_cells:
        limitations.append(
            "Capture cell(s) with no records: " + ", ".join(empty_cells)
            + "; the analyser will report them missing."
        )

    return {
        "schema_version": OBSERVATIONS_SCHEMA,
        "generator": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "inputs": {
            "plan": {
                "path": str(plan_path),
                "sha256": plan_sha256,
                "bytes": plan_bytes,
            },
            "captures": capture_results,
            "grades": grade_results,
        },
        "plan": {
            "sha256": plan_sha256,
            "scenario_count": len(plan["scenarios"]),
            "template_count": len(
                {scenario["template_id"] for scenario in plan["scenarios"]}
            ),
            "prospective_grader_sha256": declared_grader,
            "arm_map_declared": bool(arm_map),
        },
        "grading": {
            "adapter_runs_grader": False,
            "receipt_schema": RECEIPT_SCHEMA,
            "prospective_grader_declared": declared_grader is not None,
            "real_grading_blocked_until_prospective_graders_exist": True,
        },
        "counts": {
            "records": len(output_records),
            "valid": total_valid,
            "invalid": total_invalid,
            "by_cell": {
                label: {
                    "records": capture_results[label]["records"],
                    "valid": capture_results[label]["valid"],
                    "invalid": capture_results[label]["invalid"],
                }
                for label in CELL_LABELS
            },
        },
        "limitations": limitations,
        "records": output_records,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_cell_specs(values: list[str], flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in values:
        if "=" not in spec:
            raise InputError(f"{flag}: expected phase:arm=path, got {spec!r}")
        label, path = spec.split("=", 1)
        label = label.strip()
        path = path.strip()
        if not label or not path:
            raise InputError(f"{flag}: expected phase:arm=path, got {spec!r}")
        parts = label.split(":")
        if len(parts) != 2:
            raise InputError(
                f"{flag}: cell label {label!r} must be phase:arm "
                "(for example before:treatment)"
            )
        phase, arm = parts
        if phase not in PHASES or arm not in ARMS:
            raise InputError(
                f"{flag}: unknown cell {label!r}; expected one of "
                f"{', '.join(label.replace('/', ':') for label in CELL_LABELS)}"
            )
        canonical = f"{phase}/{arm}"
        if canonical in out:
            raise InputError(f"{flag}: duplicate cell {canonical}")
        out[canonical] = path

    missing = [
        label.replace("/", ":") for label in CELL_LABELS if label not in out
    ]
    extra = [label for label in out if label not in CELL_LABELS]
    if missing:
        raise InputError(f"{flag}: missing cell(s): {', '.join(missing)}")
    if extra:
        raise InputError(f"{flag}: unknown cell(s): {', '.join(extra)}")
    return {label: out[label] for label in CELL_LABELS}


def _parser() -> argparse.ArgumentParser:
    epilog = """\
Observations output:
  schema_version "agentplace.pilot.observations.v1", records with scenario_id,
  template_id, cohort, phase, arm, trial, status, integrity_pass,
  complete_pass, project_id, config_sha256, plus an audit attempt field.
  Top-level inputs/limitations/grading keys are extra provenance; the analyser
  ignores them.

Raw capture binding (from evals/provenance.mjs and evals/run.mjs):
  record.id, record.trial, record.attempt, record.status,
  provenance.scenario_id, provenance.trial, provenance.phase, provenance.arm,
  provenance.project_id, provenance.config_hash.

Grade receipt:
  schema "agentplace-graded-capture-v1", source_capture_sha256,
  grader_sha256, records [{id, trial, attempt, integrity_pass, complete_pass}].

The four cells are before:treatment, before:control, after:treatment,
after:control.  Every valid capture needs exactly one grade row; invalid
attempts are retained with null outcomes and must not be graded.
"""
    parser = argparse.ArgumentParser(
        prog="prepare_pilot_observations.py",
        description=(
            "Offline bridge from four old-style paired capture stores plus four "
            "prospective grading receipts to canonical pilot observations."
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--plan", required=True, help="analysis plan JSON")
    parser.add_argument(
        "--capture",
        action="append",
        default=[],
        required=True,
        metavar="PHASE:ARM=PATH",
        help="raw capture store for one cell; repeat for all four cells",
    )
    parser.add_argument(
        "--grades",
        action="append",
        default=[],
        required=True,
        metavar="PHASE:ARM=PATH",
        help="agentplace-graded-capture-v1 receipt for one cell; repeat for all four",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="new observations file; refuses to overwrite",
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

    output = Path(args.out)
    if output.exists():
        print(
            f"error: refusing to overwrite existing output path: {args.out}",
            file=sys.stderr,
        )
        return 3

    try:
        captures = _parse_cell_specs(args.capture, "--capture")
        grades = _parse_cell_specs(args.grades, "--grades")
        report = prepare(args.plan, captures, grades)
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
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
