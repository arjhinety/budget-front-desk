"""
Synthetic offline tests for evals/prepare_pilot_observations.py.

No browser, no network, no real captures, no real graders, no historical files.
Every capture and every grading receipt here is a temporary fixture.

    pytest -q evals/test_prepare_pilot_observations.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_pilot as ap  # noqa: E402
import prepare_pilot_observations as prep  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_G = "9" * 64

IDENTITIES = {
    "before": {
        "treatment": {"project_id": "proj-before-treatment", "config_sha256": HASH_A},
        "control": {"project_id": "proj-before-control", "config_sha256": HASH_B},
    },
    "after": {
        "treatment": {"project_id": "proj-after-treatment", "config_sha256": HASH_C},
        "control": {"project_id": "proj-after-control", "config_sha256": HASH_D},
    },
}

# Two scenarios, two trials each.  One template each so the analyser has real
# template groups without inventing anything.
SCENARIOS = (
    ("S1", "T1", "targeted", 2),
    ("S2", "T2", "tripwire", 2),
)

CELL_LABELS = (
    "before/treatment",
    "before/control",
    "after/treatment",
    "after/control",
)

ARM_MAP = {
    "before": {"treatment": "A0", "control": "A2"},
    "after": {"treatment": "A5", "control": "A2"},
}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: str | Path, payload: dict) -> str:
    Path(path).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return str(path)


def make_plan(
    *,
    grader: str | None = HASH_G,
    arm_map: dict | None = None,
) -> dict:
    plan = {
        "schema_version": ap.PLAN_SCHEMA,
        "bootstrap_seed": 7,
        "bootstrap_resamples": 40,
        "scenarios": [
            {
                "id": sid,
                "template_id": tid,
                "cohort": cohort,
                "trials": trials,
            }
            for sid, tid, cohort, trials in SCENARIOS
        ],
        "identities": IDENTITIES,
    }
    if grader is not None:
        plan["prospective_grader_sha256"] = grader
    if arm_map is not None:
        plan["arm_map"] = arm_map
    return plan


def source_arm(arm_map: dict | None, phase: str, arm: str) -> str:
    if not arm_map:
        return arm
    if any(isinstance(value, dict) for value in arm_map.values()):
        return arm_map.get(phase, {}).get(arm, arm)
    return arm_map.get(arm, arm)


def make_record(
    sid: str,
    trial: int,
    attempt: int,
    status: str,
    phase: str,
    arm: str,
    project_id: str | None,
    config_hash: str | None,
    *,
    prov_phase: str | None = None,
    prov_arm: str | None = None,
    prov_sid: str | None = None,
    prov_trial: int | None = None,
) -> dict:
    provenance = {
        "schema": prep.RAW_PROVENANCE_SCHEMA,
        "run_id": "synthetic",
        "phase": phase if prov_phase is None else prov_phase,
        "arm": arm if prov_arm is None else prov_arm,
        "scenario_id": sid if prov_sid is None else prov_sid,
        "trial": trial if prov_trial is None else prov_trial,
        "project_id": project_id,
        "config_hash": config_hash,
    }
    record = {
        "id": sid,
        "trial": trial,
        "attempt": attempt,
        "status": status,
        "provenance": provenance,
    }
    if status == "valid":
        record["thread"] = "synthetic reply"
    else:
        record["invalid_reason"] = "synthetic-invalid"
        record["error"] = "invalid capture: synthetic-invalid"
    return record


def default_pass(label: str, sid: str, trial: int) -> bool:
    # Before S2 trial 2 fails; everything else passes.  This gives the
    # analyser a nonzero treatment change and zero control drift.
    return not (label.startswith("before") and sid == "S2" and trial == 2)


def build_fixture(
    tmp_path: Path,
    *,
    plan_grader: str | None = HASH_G,
    arm_map: dict | None = None,
    invalid: set[tuple[str, str, int]] | None = None,
) -> dict:
    """Write a complete four-cell synthetic fixture and return its paths."""
    invalid = invalid or set()
    tmp_path.mkdir(parents=True, exist_ok=True)
    plan = make_plan(grader=plan_grader, arm_map=arm_map)
    plan_path = write_json(tmp_path / "plan.json", plan)

    captures: dict[str, str] = {}
    grades: dict[str, str] = {}

    for label in CELL_LABELS:
        phase, canonical_arm = label.split("/")
        raw_arm = source_arm(arm_map, phase, canonical_arm)
        identity = IDENTITIES[phase][canonical_arm]
        records: list[dict] = []
        grade_rows: list[dict] = []

        for sid, _tid, _cohort, trials in SCENARIOS:
            for trial in range(1, trials + 1):
                if (label, sid, trial) in invalid:
                    records.append(
                        make_record(
                            sid,
                            trial,
                            1,
                            "invalid",
                            phase,
                            raw_arm,
                            identity["project_id"],
                            identity["config_sha256"],
                        )
                    )
                    continue

                records.append(
                    make_record(
                        sid,
                        trial,
                        1,
                        "valid",
                        phase,
                        raw_arm,
                        identity["project_id"],
                        identity["config_sha256"],
                    )
                )
                grade_rows.append(
                    {
                        "id": sid,
                        "trial": trial,
                        "attempt": 1,
                        "integrity_pass": True,
                        "complete_pass": default_pass(label, sid, trial),
                    }
                )

        capture_name = "capture-" + label.replace("/", "-") + ".json"
        capture_path = write_json(
            tmp_path / capture_name,
            {"arm": raw_arm, "agent": "synthetic", "records": records},
        )
        grade_name = "grades-" + label.replace("/", "-") + ".json"
        grade_path = write_json(
            tmp_path / grade_name,
            {
                "schema": prep.RECEIPT_SCHEMA,
                "source_capture_sha256": sha256_file(capture_path),
                "grader_sha256": HASH_G,
                "records": grade_rows,
            },
        )
        captures[label] = capture_path
        grades[label] = grade_path

    return {
        "plan": plan,
        "plan_path": plan_path,
        "captures": captures,
        "grades": grades,
    }


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rewrite(path: str | Path, payload: dict) -> None:
    write_json(path, payload)


def rebind_capture(paths: dict, label: str, records: list[dict]) -> None:
    """Replace a capture and update only its receipt's source hash."""
    capture_path = paths["captures"][label]
    rewrite(
        capture_path,
        {"arm": label.split("/")[1], "agent": "synthetic", "records": records},
    )
    receipt = read_json(paths["grades"][label])
    receipt["source_capture_sha256"] = sha256_file(capture_path)
    rewrite(paths["grades"][label], receipt)


def find_record(
    observations: dict,
    label: str,
    sid: str,
    trial: int,
    attempt: int = 1,
) -> dict:
    phase, arm = label.split("/")
    for record in observations["records"]:
        if (
            record["phase"] == phase
            and record["arm"] == arm
            and record["scenario_id"] == sid
            and record["trial"] == trial
            and record["attempt"] == attempt
        ):
            return record
    raise AssertionError(f"record not found: {label} {sid}#{trial}/a{attempt}")


# ---------------------------------------------------------------------------
# happy path and analyser consumption
# ---------------------------------------------------------------------------


def test_happy_path_bridges_canonical_observations_and_analyzer_consumes(tmp_path: Path):
    paths = build_fixture(tmp_path)
    observations = prep.prepare(
        paths["plan_path"], paths["captures"], paths["grades"]
    )

    assert observations["schema_version"] == ap.OBSERVATIONS_SCHEMA
    assert observations["counts"]["records"] == 16
    assert observations["counts"]["valid"] == 16
    assert observations["counts"]["invalid"] == 0
    assert len(observations["records"]) == 16
    assert observations["grading"]["adapter_runs_grader"] is False
    assert (
        observations["grading"][
            "real_grading_blocked_until_prospective_graders_exist"
        ]
        is True
    )

    record = find_record(observations, "before/treatment", "S1", 1)
    assert record["template_id"] == "T1"
    assert record["cohort"] == "targeted"
    assert record["status"] == "valid"
    assert record["integrity_pass"] is True
    assert record["complete_pass"] is True
    assert record["project_id"] == "proj-before-treatment"
    assert record["config_sha256"] == HASH_A

    assert observations["inputs"]["plan"]["sha256"] == sha256_file(paths["plan_path"])
    for label in CELL_LABELS:
        capture_sha = sha256_file(paths["captures"][label])
        assert observations["inputs"]["captures"][label]["sha256"] == capture_sha
        assert (
            observations["inputs"]["grades"][label]["source_capture_sha256"]
            == capture_sha
        )
        assert observations["inputs"]["grades"][label]["grader_sha256"] == HASH_G

    assert any(
        "matched the plan-declared prospective grader" in item
        for item in observations["limitations"]
    )

    # The analyser must accept the bridge output unchanged.
    report = ap.analyze(observations, paths["plan"])
    assert report["schema_version"] == ap.ANALYSIS_SCHEMA
    assert report["counts"]["records_total"] == 16
    assert report["counts"]["invalid_attempts"] == 0
    assert report["before_after"]["n"] == 2
    assert report["claims"]["inferential"] is True
    assert report["bootstrap"]["seed"] == 7
    assert report["bootstrap"]["resamples"] == 40


def test_invalid_attempts_retained_with_null_outcomes(tmp_path: Path):
    paths = build_fixture(tmp_path, invalid={("before/treatment", "S1", 2)})
    observations = prep.prepare(
        paths["plan_path"], paths["captures"], paths["grades"]
    )

    assert observations["counts"]["records"] == 16
    assert observations["counts"]["valid"] == 15
    assert observations["counts"]["invalid"] == 1

    invalid = find_record(observations, "before/treatment", "S1", 2)
    assert invalid["status"] == "invalid"
    assert invalid["integrity_pass"] is None
    assert invalid["complete_pass"] is None
    assert any("invalid capture attempt(s) retained" in item for item in observations["limitations"])

    report = ap.analyze(observations, paths["plan"])
    assert report["counts"]["invalid_attempts"] == 1
    assert report["before_after"]["n"] == 1
    assert "incomplete_cell:before/treatment" in next(
        scenario["exclusion_reasons"]
        for scenario in report["scenarios"]
        if scenario["scenario_id"] == "S1"
    )


def test_empty_cell_is_retained_as_missing_not_fabricated(tmp_path: Path):
    paths = build_fixture(tmp_path)
    receipt = read_json(paths["grades"]["before/treatment"])
    receipt["records"] = []
    rewrite(paths["grades"]["before/treatment"], receipt)
    rebind_capture(paths, "before/treatment", [])

    observations = prep.prepare(
        paths["plan_path"], paths["captures"], paths["grades"]
    )
    assert observations["counts"]["valid"] == 12
    assert observations["counts"]["invalid"] == 0
    assert any("no records: before/treatment" in item for item in observations["limitations"])

    report = ap.analyze(observations, paths["plan"])
    assert report["before_after"]["n"] == 0
    assert report["counts"]["missing_valid_trials"] == 4


# ---------------------------------------------------------------------------
# grade receipt matching
# ---------------------------------------------------------------------------


def test_missing_grade_row_is_refused(tmp_path: Path):
    paths = build_fixture(tmp_path)
    receipt = read_json(paths["grades"]["before/treatment"])
    receipt["records"].pop()
    rewrite(paths["grades"]["before/treatment"], receipt)

    with pytest.raises(ap.InputError, match="missing grade row"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_extra_grade_row_is_refused_even_for_an_invalid_attempt(tmp_path: Path):
    paths = build_fixture(tmp_path, invalid={("before/treatment", "S1", 2)})
    receipt = read_json(paths["grades"]["before/treatment"])
    receipt["records"].append(
        {
            "id": "S1",
            "trial": 2,
            "attempt": 1,
            "integrity_pass": True,
            "complete_pass": True,
        }
    )
    rewrite(paths["grades"]["before/treatment"], receipt)

    with pytest.raises(ap.InputError, match="extra grade row"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_duplicate_grade_row_is_refused(tmp_path: Path):
    paths = build_fixture(tmp_path)
    receipt = read_json(paths["grades"]["before/treatment"])
    receipt["records"].append(dict(receipt["records"][0]))
    rewrite(paths["grades"]["before/treatment"], receipt)

    with pytest.raises(ap.InputError, match="duplicate grade row"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_receipt_schema_and_source_hash_are_enforced(tmp_path: Path):
    paths = build_fixture(tmp_path)
    receipt = read_json(paths["grades"]["before/treatment"])
    receipt["schema"] = "some-other-schema"
    rewrite(paths["grades"]["before/treatment"], receipt)
    with pytest.raises(ap.InputError, match="schema"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])

    paths = build_fixture(tmp_path / "second")
    receipt = read_json(paths["grades"]["before/treatment"])
    receipt["source_capture_sha256"] = "0" * 64
    rewrite(paths["grades"]["before/treatment"], receipt)
    with pytest.raises(ap.InputError, match="source_capture_sha256"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_grader_hash_must_match_plan_declaration(tmp_path: Path):
    paths = build_fixture(tmp_path)
    receipt = read_json(paths["grades"]["before/treatment"])
    receipt["grader_sha256"] = HASH_E
    rewrite(paths["grades"]["before/treatment"], receipt)

    with pytest.raises(ap.InputError, match="grader_sha256"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_plan_without_grader_declaration_records_unbound_hash(tmp_path: Path):
    paths = build_fixture(tmp_path, plan_grader=None)
    observations = prep.prepare(
        paths["plan_path"], paths["captures"], paths["grades"]
    )

    assert observations["grading"]["prospective_grader_declared"] is False
    assert observations["plan"]["prospective_grader_sha256"] is None
    assert observations["inputs"]["grades"]["before/treatment"]["grader_sha256"] == HASH_G
    assert any(
        "plan declares no prospective grader" in item
        for item in observations["limitations"]
    )


# ---------------------------------------------------------------------------
# capture binding and duplicate refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"prov_phase": "after"}, "provenance.phase"),
        ({"prov_arm": "control"}, "provenance.arm"),
        ({"prov_sid": "S2"}, "provenance.scenario_id"),
        ({"prov_trial": 2}, "provenance.trial"),
    ],
)
def test_wrong_phase_arm_scenario_and_trial_bindings_are_refused(
    tmp_path: Path, mutation: dict, message: str
):
    paths = build_fixture(tmp_path)
    capture = read_json(paths["captures"]["before/treatment"])
    record = capture["records"][0]
    provenance_key = {
        "prov_phase": "phase",
        "prov_arm": "arm",
        "prov_sid": "scenario_id",
        "prov_trial": "trial",
    }
    for key, value in mutation.items():
        record["provenance"][provenance_key[key]] = value
    rewrite(paths["captures"]["before/treatment"], capture)

    with pytest.raises(ap.InputError, match=message):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_unknown_scenario_and_out_of_range_trial_are_refused(tmp_path: Path):
    paths = build_fixture(tmp_path)
    capture = read_json(paths["captures"]["before/treatment"])
    record = capture["records"][0]
    record["id"] = "UNKNOWN"
    record["provenance"]["scenario_id"] = "UNKNOWN"
    rewrite(paths["captures"]["before/treatment"], capture)
    with pytest.raises(ap.InputError, match="not declared in the plan"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])

    paths = build_fixture(tmp_path / "second")
    capture = read_json(paths["captures"]["before/treatment"])
    record = capture["records"][0]
    record["trial"] = 3
    record["provenance"]["trial"] = 3
    rewrite(paths["captures"]["before/treatment"], capture)
    with pytest.raises(ap.InputError, match="exceeds planned trials"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_wrong_declared_config_or_project_is_refused(tmp_path: Path):
    paths = build_fixture(tmp_path)
    capture = read_json(paths["captures"]["before/treatment"])
    capture["records"][0]["provenance"]["config_hash"] = HASH_E
    rewrite(paths["captures"]["before/treatment"], capture)
    with pytest.raises(ap.InputError, match="config_hash"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])

    paths = build_fixture(tmp_path / "second")
    capture = read_json(paths["captures"]["before/treatment"])
    capture["records"][0]["provenance"]["project_id"] = "other-project"
    rewrite(paths["captures"]["before/treatment"], capture)
    with pytest.raises(ap.InputError, match="project_id"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_duplicate_valid_attempt_is_refused(tmp_path: Path):
    paths = build_fixture(tmp_path)
    capture = read_json(paths["captures"]["before/treatment"])
    duplicate = dict(capture["records"][0])
    duplicate["attempt"] = 2
    duplicate["provenance"] = dict(capture["records"][0]["provenance"])
    capture["records"].append(duplicate)
    rewrite(paths["captures"]["before/treatment"], capture)

    with pytest.raises(ap.InputError, match="duplicate valid attempt"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_duplicate_attempt_key_is_refused(tmp_path: Path):
    paths = build_fixture(tmp_path)
    capture = read_json(paths["captures"]["before/treatment"])
    duplicate = dict(capture["records"][0])
    duplicate["status"] = "invalid"
    duplicate["error"] = "invalid capture: duplicate"
    duplicate["provenance"] = dict(capture["records"][0]["provenance"])
    capture["records"].append(duplicate)
    rewrite(paths["captures"]["before/treatment"], capture)

    with pytest.raises(ap.InputError, match="duplicate attempt key"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


def test_missing_raw_identity_is_not_filled_and_blocks_inference(tmp_path: Path):
    paths = build_fixture(tmp_path)
    capture = read_json(paths["captures"]["before/treatment"])
    for record in capture["records"]:
        record["provenance"]["project_id"] = None
        record["provenance"]["config_hash"] = None
    rewrite(paths["captures"]["before/treatment"], capture)
    rebind_capture(paths, "before/treatment", capture["records"])

    observations = prep.prepare(
        paths["plan_path"], paths["captures"], paths["grades"]
    )
    record = find_record(observations, "before/treatment", "S1", 1)
    assert record["project_id"] is None
    assert record["config_sha256"] is None
    assert any("carried no raw project_id/config_hash" in item for item in observations["limitations"])
    assert any("expected values were not written" in item for item in observations["limitations"])

    report = ap.analyze(observations, paths["plan"])
    assert report["before_after"]["n"] == 2
    assert report["scenarios"][0]["cells"]["before/treatment"]["identity"]["status"] == "unverified"
    assert report["claims"]["inferential"] is False


# ---------------------------------------------------------------------------
# arm binding
# ---------------------------------------------------------------------------


def test_explicit_arm_map_binds_source_arms_without_guessing(tmp_path: Path):
    paths = build_fixture(tmp_path, arm_map=ARM_MAP)
    observations = prep.prepare(
        paths["plan_path"], paths["captures"], paths["grades"]
    )

    assert observations["plan"]["arm_map_declared"] is True
    assert any("explicit arm_map" in item for item in observations["limitations"])
    record = find_record(observations, "before/treatment", "S1", 1)
    assert record["arm"] == "treatment"
    assert record["phase"] == "before"

    report = ap.analyze(observations, paths["plan"])
    assert report["before_after"]["n"] == 2


def test_source_arm_without_declared_mapping_is_refused(tmp_path: Path):
    paths = build_fixture(tmp_path)
    capture = read_json(paths["captures"]["before/treatment"])
    capture["records"][0]["provenance"]["arm"] = "A0"
    rewrite(paths["captures"]["before/treatment"], capture)

    with pytest.raises(ap.InputError, match="declare plan.arm_map"):
        prep.prepare(paths["plan_path"], paths["captures"], paths["grades"])


# ---------------------------------------------------------------------------
# CLI: new file only, read-only help, no output on failure
# ---------------------------------------------------------------------------


def cli_args(paths: dict, out: Path) -> list[str]:
    args = ["--plan", paths["plan_path"]]
    for label in CELL_LABELS:
        args.extend(["--capture", f"{label.replace('/', ':')}={paths['captures'][label]}"])
    for label in CELL_LABELS:
        args.extend(["--grades", f"{label.replace('/', ':')}={paths['grades'][label]}"])
    args.extend(["--out", str(out)])
    return args


def test_cli_writes_only_a_new_file_and_refuses_overwrite(tmp_path: Path, capsys):
    paths = build_fixture(tmp_path)
    out = tmp_path / "observations.json"

    assert prep.main(cli_args(paths, out)) == 0
    first = out.read_text(encoding="utf-8")
    assert json.loads(first)["schema_version"] == ap.OBSERVATIONS_SCHEMA

    assert prep.main(cli_args(paths, out)) == 3
    assert out.read_text(encoding="utf-8") == first
    assert "refusing to overwrite" in capsys.readouterr().err


def test_cli_help_is_read_only(tmp_path: Path, capsys):
    before = set(tmp_path.iterdir())
    with pytest.raises(SystemExit) as exc:
        prep.main(["--help"])
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out
    assert set(tmp_path.iterdir()) == before


def test_cli_failure_does_not_create_output(tmp_path: Path, capsys):
    paths = build_fixture(tmp_path)
    receipt = read_json(paths["grades"]["before/treatment"])
    receipt["records"].pop()
    rewrite(paths["grades"]["before/treatment"], receipt)
    out = tmp_path / "observations.json"

    assert prep.main(cli_args(paths, out)) == 2
    assert not out.exists()
    assert "missing grade row" in capsys.readouterr().err


def test_cli_duplicate_and_missing_cells_are_refused(tmp_path: Path, capsys):
    paths = build_fixture(tmp_path)
    out = tmp_path / "observations.json"
    args = cli_args(paths, out)
    args.extend(
        [
            "--capture",
            f"before:treatment={paths['captures']['before/treatment']}",
        ]
    )
    assert prep.main(args) == 2
    assert not out.exists()
    assert "duplicate cell" in capsys.readouterr().err

    short = ["--plan", paths["plan_path"]]
    for label in CELL_LABELS[:3]:
        short.extend(["--capture", f"{label.replace('/', ':')}={paths['captures'][label]}"])
    for label in CELL_LABELS:
        short.extend(["--grades", f"{label.replace('/', ':')}={paths['grades'][label]}"])
    short.extend(["--out", str(out)])
    assert prep.main(short) == 2
    assert not out.exists()
    assert "missing cell" in capsys.readouterr().err
