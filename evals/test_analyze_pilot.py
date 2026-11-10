"""
Synthetic offline tests for evals/analyze_pilot.py.

No browser, no network, no real captures, no graders, no frozen inputs.
Every record here is a temporary fixture.

    pytest -q evals/test_analyze_pilot.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_pilot as ap  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64

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


def rec(
    sid: str,
    tid: str,
    cohort: str,
    phase: str,
    arm: str,
    trial: int,
    passed: bool | None = True,
    *,
    status: str = "valid",
    integrity: bool | None = True,
    project: str | None = "proj",
    config: str | None = HASH_A,
) -> dict:
    return {
        "scenario_id": sid,
        "template_id": tid,
        "cohort": cohort,
        "phase": phase,
        "arm": arm,
        "trial": trial,
        "status": status,
        "integrity_pass": integrity,
        "complete_pass": passed,
        "project_id": project,
        "config_sha256": config,
    }


def emit_cell(
    out: list[dict],
    sid: str,
    tid: str,
    cohort: str,
    phase: str,
    arm: str,
    pattern: list[bool | None],
    *,
    project: str | None = "proj",
    config: str | None = HASH_A,
    invalid_integrity: bool = False,
) -> None:
    for trial, value in enumerate(pattern, 1):
        if value is None:
            out.append(
                rec(
                    sid,
                    tid,
                    cohort,
                    phase,
                    arm,
                    trial,
                    None,
                    status="invalid",
                    integrity=not invalid_integrity,
                    project=project,
                    config=config,
                )
            )
        else:
            out.append(
                rec(
                    sid,
                    tid,
                    cohort,
                    phase,
                    arm,
                    trial,
                    bool(value),
                    status="valid",
                    integrity=True,
                    project=project,
                    config=config,
                )
            )


def emit_four(
    out: list[dict],
    sid: str,
    tid: str,
    cohort: str,
    *,
    before_treatment: list[bool | None],
    before_control: list[bool | None],
    after_treatment: list[bool | None],
    after_control: list[bool | None],
    identities: dict | None = IDENTITIES,
    project: str | None = "proj",
    config: str | None = HASH_A,
) -> None:
    for phase, arm, pattern in (
        ("before", "treatment", before_treatment),
        ("before", "control", before_control),
        ("after", "treatment", after_treatment),
        ("after", "control", after_control),
    ):
        if identities is None:
            emit_cell(out, sid, tid, cohort, phase, arm, pattern, project=project, config=config)
        else:
            spec = identities[phase][arm]
            emit_cell(
                out,
                sid,
                tid,
                cohort,
                phase,
                arm,
                pattern,
                project=spec["project_id"],
                config=spec["config_sha256"],
            )


def make_plan(
    scenarios: list[tuple[str, str, str, int]],
    *,
    seed: int = 20261111,
    resamples: int = 200,
    identities: dict | None = None,
) -> dict:
    plan = {
        "schema_version": ap.PLAN_SCHEMA,
        "bootstrap_seed": seed,
        "bootstrap_resamples": resamples,
        "scenarios": [
            {"id": sid, "template_id": tid, "cohort": cohort, "trials": trials}
            for sid, tid, cohort, trials in scenarios
        ],
    }
    if identities is not None:
        plan["identities"] = identities
    return plan


def make_obs(records: list[dict]) -> dict:
    return {"schema_version": ap.OBSERVATIONS_SCHEMA, "records": records}


# ---------------------------------------------------------------------------
# A/A
# ---------------------------------------------------------------------------


def test_identical_aa_reports_zero_difference_and_no_equivalence_claim():
    patterns = {
        "S1": [True, True, True],
        "S2": [True, True, False],
        "S3": [False, True, False],
        "S4": [False, False, False],
    }
    records: list[dict] = []
    scenarios: list[tuple[str, str, str, int]] = []
    for index, (sid, pattern) in enumerate(patterns.items()):
        tid = "T1" if index < 2 else "T2"
        scenarios.append((sid, tid, "targeted", 3))
        emit_cell(records, sid, tid, "targeted", "before", "treatment", pattern)
        emit_cell(records, sid, tid, "targeted", "before", "control", pattern)

    report = ap.analyze(
        make_obs(records), make_plan(scenarios), phase_mode="aa"
    )

    aa = report["aa"]
    assert report["phase_mode"] == "aa"
    assert report["before_after"] is None
    assert aa["n"] == 4
    assert aa["mean_absolute_difference"] == pytest.approx(0.0)
    assert aa["strict_all_trials_pass_disagreement_count"] == 0
    assert aa["equivalence_claim"] is False
    assert report["claims"]["inferential"] is False

    fractions = {
        scenario["scenario_id"]: scenario["cells"]["before/treatment"]["pass_fraction"]
        for scenario in report["scenarios"]
    }
    assert fractions["S1"] == pytest.approx(1.0)
    assert fractions["S2"] == pytest.approx(2 / 3)
    assert fractions["S3"] == pytest.approx(1 / 3)
    assert fractions["S4"] == pytest.approx(0.0)


def test_nonzero_aa_difference_and_strict_disagreement():
    records: list[dict] = []
    scenarios = [("S1", "T1", "targeted", 3), ("S2", "T1", "targeted", 3)]
    emit_cell(records, "S1", "T1", "targeted", "before", "treatment", [True, True, True])
    emit_cell(records, "S1", "T1", "targeted", "before", "control", [True, True, False])
    emit_cell(records, "S2", "T1", "targeted", "before", "treatment", [True, True, False])
    emit_cell(records, "S2", "T1", "targeted", "before", "control", [True, True, False])

    aa = ap.analyze(make_obs(records), make_plan(scenarios), phase_mode="aa")["aa"]

    assert aa["n"] == 2
    assert aa["mean_absolute_difference"] == pytest.approx(1 / 6)
    assert aa["mean_signed_difference"] == pytest.approx(1 / 6)
    assert aa["strict_all_trials_pass_disagreement_count"] == 1
    assert aa["strict_all_trials_pass_disagreement_fraction"] == pytest.approx(0.5)
    assert aa["strict_all_trials_pass_disagreements"][0]["scenario_id"] == "S1"
    assert aa["treatment_all_trials_pass_count"] == 1
    assert aa["control_all_trials_pass_count"] == 0


def test_aa_ignores_after_records_without_treating_them_as_errors():
    records: list[dict] = []
    scenarios = [("S1", "T1", "targeted", 2)]
    emit_four(
        records,
        "S1",
        "T1",
        "targeted",
        before_treatment=[True, True],
        before_control=[True, True],
        after_treatment=[True, True],
        after_control=[True, True],
    )

    report = ap.analyze(make_obs(records), make_plan(scenarios), phase_mode="aa")

    assert report["counts"]["records_ignored"] == 4
    assert report["counts"]["records_in_scope"] == 4
    assert set(report["scenarios"][0]["cells"]) == {"before/treatment", "before/control"}
    assert report["aa"]["n"] == 1
    assert report["claims"]["inferential"] is False
    assert "equivalence" in report["aa"]["interpretation"].lower()
    assert isinstance(ap.render_text(report), str)


# ---------------------------------------------------------------------------
# before / after
# ---------------------------------------------------------------------------


def test_known_one_clause_treatment_effect():
    base = [True, True, False, False]
    improved = [True, True, True, False]
    records: list[dict] = []
    scenarios: list[tuple[str, str, str, int]] = []
    for sid, tid in (("S1", "T1"), ("S2", "T1"), ("S3", "T2"), ("S4", "T2")):
        scenarios.append((sid, tid, "targeted", 4))
        emit_four(
            records,
            sid,
            tid,
            "targeted",
            before_treatment=base,
            before_control=base,
            after_treatment=improved,
            after_control=base,
        )

    report = ap.analyze(
        make_obs(records),
        make_plan(scenarios, seed=123, resamples=300, identities=IDENTITIES),
    )
    section = report["before_after"]
    treatment = section["treatment_change"]
    control = section["control_drift"]
    did = section["difference_in_differences"]

    assert report["schema_version"] == ap.ANALYSIS_SCHEMA
    assert section["n"] == 4
    assert treatment["case_weighted_mean"] == pytest.approx(0.25)
    assert treatment["template_weighted_mean"] == pytest.approx(0.25)
    assert control["case_weighted_mean"] == pytest.approx(0.0)
    assert did["case_weighted_mean"] == pytest.approx(0.25)
    assert did["template_weighted_mean"] == pytest.approx(0.25)
    assert did["case_weighted_minus_template_weighted"] == pytest.approx(0.0)
    assert did["primary_estimand"] == "template_weighted_mean"
    assert treatment["positive"] == 4
    assert treatment["negative"] == 0
    assert treatment["ties"] == 0
    assert treatment["sign_test"]["two_sided_exact_binomial_p"] == pytest.approx(0.125)
    assert treatment["sign_test"]["decision"] is None
    assert report["claims"]["inferential"] is True
    assert report["claims"]["automatic_success"] is False
    assert report["claims"]["decision"] is None
    assert report["identity"]["all_included_scenarios_identity_verified"] is True
    assert report["identity"]["treatment_identity_change"] == "changed"
    assert report["bootstrap"]["seed"] == 123
    assert report["bootstrap"]["resamples"] == 300
    assert report["bootstrap"]["intervals"]["difference_in_differences"]["lower"] <= (
        did["template_weighted_mean"]
    )
    assert report["bootstrap"]["intervals"]["difference_in_differences"]["upper"] >= (
        did["template_weighted_mean"]
    )


def test_sign_counts_omit_ties():
    base = [True, True, False, False]
    improved = [True, True, True, False]
    records: list[dict] = []
    scenarios: list[tuple[str, str, str, int]] = []
    for index, (sid, tid) in enumerate((("S1", "T1"), ("S2", "T1"), ("S3", "T2"), ("S4", "T2"))):
        scenarios.append((sid, tid, "targeted", 4))
        after_treatment = improved if index < 3 else base
        emit_four(
            records,
            sid,
            tid,
            "targeted",
            before_treatment=base,
            before_control=base,
            after_treatment=after_treatment,
            after_control=base,
        )

    section = ap.analyze(make_obs(records), make_plan(scenarios))["before_after"]
    treatment = section["treatment_change"]

    assert treatment["positive"] == 3
    assert treatment["negative"] == 0
    assert treatment["ties"] == 1
    assert treatment["sign_test"]["n_nonzero"] == 3
    assert treatment["sign_test"]["ties_omitted"] is True
    assert treatment["sign_test"]["two_sided_exact_binomial_p"] == pytest.approx(0.25)
    assert section["difference_in_differences"]["case_weighted_mean"] == pytest.approx(0.1875)


def test_nonzero_control_drift_reduces_difference_in_differences():
    base = [True, True, False, False]
    improved = [True, True, True, False]
    records: list[dict] = []
    scenarios: list[tuple[str, str, str, int]] = []
    for sid, tid in (("S1", "T1"), ("S2", "T1"), ("S3", "T2")):
        scenarios.append((sid, tid, "targeted", 4))
        emit_four(
            records,
            sid,
            tid,
            "targeted",
            before_treatment=base,
            before_control=base,
            after_treatment=base,
            after_control=improved,
        )

    section = ap.analyze(make_obs(records), make_plan(scenarios))["before_after"]

    assert section["treatment_change"]["case_weighted_mean"] == pytest.approx(0.0)
    assert section["treatment_change"]["ties"] == 3
    assert section["treatment_change"]["sign_test"]["two_sided_exact_binomial_p"] is None
    assert section["control_drift"]["case_weighted_mean"] == pytest.approx(0.25)
    assert section["control_drift"]["positive"] == 3
    assert section["difference_in_differences"]["case_weighted_mean"] == pytest.approx(-0.25)


def test_template_clustering_macro_average_differs_from_case_weighted_mean():
    records: list[dict] = []
    scenarios: list[tuple[str, str, str, int]] = []
    for sid in ("S1", "S2", "S3"):
        scenarios.append((sid, "T1", "targeted", 4))
        emit_four(
            records,
            sid,
            "T1",
            "targeted",
            before_treatment=[False] * 4,
            before_control=[False] * 4,
            after_treatment=[True] * 4,
            after_control=[False] * 4,
        )
    scenarios.append(("S4", "T2", "targeted", 4))
    emit_four(
        records,
        "S4",
        "T2",
        "targeted",
        before_treatment=[False] * 4,
        before_control=[False] * 4,
        after_treatment=[False] * 4,
        after_control=[False] * 4,
    )

    report = ap.analyze(
        make_obs(records), make_plan(scenarios, seed=77, resamples=500)
    )
    did = report["before_after"]["difference_in_differences"]

    assert report["before_after"]["n"] == 4
    assert did["case_weighted_mean"] == pytest.approx(0.75)
    assert did["template_weighted_mean"] == pytest.approx(0.5)
    assert did["case_weighted_minus_template_weighted"] == pytest.approx(0.25)
    assert did["weighting"]["primary"] == "template_weighted"
    assert report["before_after"]["primary_estimand"] == (
        "template_weighted_mean difference-in-differences"
    )

    bootstrap = report["bootstrap"]
    assert bootstrap["template_count"] == 2
    assert bootstrap["single_template"] is False
    assert bootstrap["degenerate"] is False
    assert bootstrap["seed"] == 77
    assert bootstrap["resamples"] == 500
    assert [item["scenarios"] for item in bootstrap["templates"]] == [3, 1]
    interval = bootstrap["intervals"]["difference_in_differences"]
    assert 0.0 <= interval["lower"] <= interval["upper"] <= 1.0
    assert interval["lower"] <= did["template_weighted_mean"] <= interval["upper"]
    assert ap.render_json(report) == ap.render_json(
        ap.analyze(make_obs(records), make_plan(scenarios, seed=77, resamples=500))
    )


def test_incomplete_cells_are_reported_and_excluded_from_comparisons():
    base = [True, True, False]
    records: list[dict] = []
    scenarios: list[tuple[str, str, str, int]] = []

    for sid in ("S1", "S2", "S3"):
        scenarios.append((sid, "T1", "targeted", 3))
        emit_four(
            records,
            sid,
            "T1",
            "targeted",
            before_treatment=base,
            before_control=base,
            after_treatment=base,
            after_control=base,
        )

    scenarios.append(("S4", "T1", "targeted", 3))
    emit_cell(records, "S4", "T1", "targeted", "before", "treatment", base)
    emit_cell(records, "S4", "T1", "targeted", "before", "control", base)
    emit_cell(records, "S4", "T1", "targeted", "after", "treatment", base)
    # after/control is entirely missing

    scenarios.append(("S5", "T2", "targeted", 3))
    emit_cell(records, "S5", "T2", "targeted", "before", "treatment", base)
    emit_cell(records, "S5", "T2", "targeted", "before", "control", base)
    emit_cell(records, "S5", "T2", "targeted", "after", "treatment", base[:2])
    emit_cell(records, "S5", "T2", "targeted", "after", "control", base)

    report = ap.analyze(make_obs(records), make_plan(scenarios))
    section = report["before_after"]

    assert section["n"] == 3
    assert set(section["included_scenarios"]) == {"S1", "S2", "S3"}
    excluded = {item["scenario_id"]: item for item in section["excluded_scenarios"]}
    assert set(excluded) == {"S4", "S5"}
    assert "after/control" in excluded["S4"]["missing_cells"]
    assert any(
        item["cell"] == "after/treatment" and item["missing_trials"] == [3]
        for item in excluded["S5"]["incomplete_cells"]
    )
    assert "incomplete_cell:after/treatment" in excluded["S5"]["reasons"]
    assert report["counts"]["missing_valid_trials"] == 4


def test_no_records_is_reported_not_imputed():
    report = ap.analyze(
        make_obs([]), make_plan([("S1", "T1", "targeted", 2)]), phase_mode="ab"
    )

    assert report["before_after"]["n"] == 0
    assert report["before_after"]["excluded_scenarios"][0]["reasons"] == ["no_records"]
    assert report["bootstrap"] is None
    assert report["claims"]["inferential"] is False
    assert report["counts"]["missing_valid_trials"] == 8
    assert isinstance(ap.render_text(report), str)


# ---------------------------------------------------------------------------
# invalid attempts, duplicates, repeats
# ---------------------------------------------------------------------------


def test_invalid_attempts_are_retained_and_not_scored_as_failures():
    records: list[dict] = []
    scenarios = [("S1", "T1", "targeted", 3)]
    emit_cell(
        records,
        "S1",
        "T1",
        "targeted",
        "before",
        "treatment",
        [True, None, True],
        invalid_integrity=True,
    )
    emit_cell(
        records,
        "S1",
        "T1",
        "targeted",
        "before",
        "control",
        [True, True, True],
    )

    report = ap.analyze(make_obs(records), make_plan(scenarios), phase_mode="aa")
    cell = report["scenarios"][0]["cells"]["before/treatment"]

    assert cell["valid_attempts"] == 2
    assert cell["invalid_attempts"] == 1
    assert cell["passes"] == 2
    assert cell["pass_fraction"] == pytest.approx(1.0)
    assert cell["complete"] is False
    assert cell["missing_trials"] == [2]
    assert cell["integrity_failures"] == 0
    assert cell["invalid_integrity_failures"] == 1
    assert report["counts"]["invalid_attempts"] == 1
    assert report["counts"]["invalid_attempts_analyzed"] == 1
    assert report["counts"]["missing_valid_trials"] == 1
    assert report["aa"]["n"] == 0
    assert "incomplete_cell:before/treatment" in report["scenarios"][0]["exclusion_reasons"]

    attempt = next(item for item in cell["attempts"] if item["trial"] == 2)
    assert attempt["status"] == "invalid"
    assert attempt["complete_pass"] is None
    assert attempt["integrity_pass"] is False


def test_invalid_attempts_may_omit_outcome_labels():
    records = [
        {
            "scenario_id": "S1",
            "template_id": "T1",
            "cohort": "targeted",
            "phase": "before",
            "arm": "treatment",
            "trial": 1,
            "status": "invalid",
            "project_id": "proj",
            "config_sha256": HASH_A,
        },
        rec("S1", "T1", "targeted", "before", "treatment", 1, True),
        rec("S1", "T1", "targeted", "before", "treatment", 2, True),
        rec("S1", "T1", "targeted", "before", "control", 1, True),
        rec("S1", "T1", "targeted", "before", "control", 2, True),
    ]
    report = ap.analyze(
        make_obs(records), make_plan([("S1", "T1", "targeted", 2)]), phase_mode="aa"
    )
    cell = report["scenarios"][0]["cells"]["before/treatment"]
    assert report["counts"]["invalid_attempts"] == 1
    assert cell["valid_attempts"] == 2
    assert cell["invalid_attempts"] == 1
    assert cell["complete"] is True
    assert cell["attempts"][0]["status"] == "valid"
    assert all(
        attempt["status"] == "valid" or attempt["complete_pass"] is None
        for attempt in cell["attempts"]
    )


def test_duplicate_valid_cell_trial_is_rejected():
    records = [
        rec("S1", "T1", "targeted", "before", "treatment", 1, True),
        rec("S1", "T1", "targeted", "before", "treatment", 1, False),
    ]
    with pytest.raises(ap.InputError, match="duplicate valid"):
        ap.analyze(make_obs(records), make_plan([("S1", "T1", "targeted", 2)]))


def test_invalid_plus_valid_at_same_trial_is_allowed_and_retained():
    records = [
        rec("S1", "T1", "targeted", "before", "treatment", 1, None, status="invalid"),
        rec("S1", "T1", "targeted", "before", "treatment", 1, True),
        rec("S1", "T1", "targeted", "before", "treatment", 2, True),
        rec("S1", "T1", "targeted", "before", "control", 1, True),
        rec("S1", "T1", "targeted", "before", "control", 2, True),
    ]
    report = ap.analyze(
        make_obs(records), make_plan([("S1", "T1", "targeted", 2)]), phase_mode="aa"
    )
    cell = report["scenarios"][0]["cells"]["before/treatment"]
    assert cell["valid_attempts"] == 2
    assert cell["invalid_attempts"] == 1
    assert cell["complete"] is True
    assert report["aa"]["n"] == 1


def test_expected_repeats_and_out_of_range_trial():
    complete = [
        rec("S1", "T1", "targeted", "before", "treatment", 1, True),
        rec("S1", "T1", "targeted", "before", "treatment", 2, True),
        rec("S1", "T1", "targeted", "before", "treatment", 3, True),
    ]
    report = ap.analyze(
        make_obs(complete), make_plan([("S1", "T1", "targeted", 3)]), phase_mode="aa"
    )
    cell = report["scenarios"][0]["cells"]["before/treatment"]
    assert cell["complete"] is True
    assert cell["missing_trials"] == []
    assert cell["pass_fraction"] == pytest.approx(1.0)

    missing = complete[:2]
    report = ap.analyze(
        make_obs(missing), make_plan([("S1", "T1", "targeted", 3)]), phase_mode="aa"
    )
    cell = report["scenarios"][0]["cells"]["before/treatment"]
    assert cell["complete"] is False
    assert cell["missing_trials"] == [3]

    out_of_range = complete + [
        rec("S1", "T1", "targeted", "before", "treatment", 4, True)
    ]
    with pytest.raises(ap.InputError, match="exceeds planned trials"):
        ap.analyze(
            make_obs(out_of_range),
            make_plan([("S1", "T1", "targeted", 3)]),
            phase_mode="aa",
        )


# ---------------------------------------------------------------------------
# identity and declaration validation
# ---------------------------------------------------------------------------


def test_wrong_declared_config_and_project_are_rejected():
    plan = make_plan(
        [("S1", "T1", "targeted", 2)],
        identities={
            "before": {
                "treatment": {
                    "project_id": "proj-declared",
                    "config_sha256": HASH_A,
                }
            }
        },
    )
    wrong_config = [
        rec(
            "S1",
            "T1",
            "targeted",
            "before",
            "treatment",
            1,
            True,
            project="proj-declared",
            config=HASH_B,
        )
    ]
    with pytest.raises(ap.InputError, match="config_sha256"):
        ap.analyze(make_obs(wrong_config), plan)

    wrong_project = [
        rec(
            "S1",
            "T1",
            "targeted",
            "before",
            "treatment",
            1,
            True,
            project="proj-other",
            config=HASH_A,
        )
    ]
    with pytest.raises(ap.InputError, match="project_id"):
        ap.analyze(make_obs(wrong_project), plan)


def test_inconsistent_observed_identity_within_a_cell_is_rejected():
    records = [
        rec("S1", "T1", "targeted", "before", "treatment", 1, True, project="proj-a"),
        rec("S1", "T1", "targeted", "before", "treatment", 2, True, project="proj-b"),
    ]
    with pytest.raises(ap.InputError, match="inconsistent project_id"):
        ap.analyze(make_obs(records), make_plan([("S1", "T1", "targeted", 2)]))


def test_missing_actual_identity_blocks_inference_and_is_not_filled():
    records: list[dict] = []
    scenarios = [("S1", "T1", "targeted", 2)]
    emit_four(
        records,
        "S1",
        "T1",
        "targeted",
        before_treatment=[True, True],
        before_control=[True, True],
        after_treatment=[True, True],
        after_control=[True, True],
        identities=None,
        project=None,
        config=None,
    )

    report = ap.analyze(
        make_obs(records),
        make_plan(scenarios, identities=IDENTITIES),
    )
    cell = report["scenarios"][0]["cells"]["before/treatment"]

    assert report["before_after"]["n"] == 1
    assert cell["identity"]["status"] == "unverified"
    assert cell["identity"]["observed_project_ids"] == []
    assert cell["identity"]["observed_config_sha256s"] == []
    assert report["identity"]["cell_status_counts"]["unverified"] == 4
    assert report["identity"]["all_included_scenarios_identity_verified"] is False
    assert report["claims"]["inferential"] is False
    assert report["claims"]["blocked_reasons"]


def test_template_and_cohort_inconsistency_are_rejected():
    plan = make_plan([("S1", "T1", "targeted", 2)])
    with pytest.raises(ap.InputError, match="template_id"):
        ap.analyze(
            make_obs([rec("S1", "T2", "targeted", "before", "treatment", 1, True)]), plan
        )
    with pytest.raises(ap.InputError, match="cohort"):
        ap.analyze(
            make_obs([rec("S1", "T1", "tripwire", "before", "treatment", 1, True)]), plan
        )


def test_duplicate_plan_scenario_id_is_rejected():
    plan = make_plan(
        [("S1", "T1", "targeted", 2), ("S1", "T2", "tripwire", 2)]
    )
    with pytest.raises(ap.InputError, match="duplicate scenario id"):
        ap.analyze(make_obs([]), plan)


# ---------------------------------------------------------------------------
# cohort separation and bootstrap determinism
# ---------------------------------------------------------------------------


def test_targeted_and_tripwire_rates_are_separate():
    records: list[dict] = []
    scenarios = [
        ("S1", "T1", "targeted", 2),
        ("S2", "T1", "targeted", 2),
        ("S3", "T2", "tripwire", 2),
        ("S4", "T2", "tripwire", 2),
    ]
    for sid, tid, cohort, trials in scenarios:
        pattern = [True, True] if cohort == "targeted" else [False, False]
        emit_cell(records, sid, tid, cohort, "before", "treatment", pattern)
        emit_cell(records, sid, tid, cohort, "before", "control", pattern)

    report = ap.analyze(make_obs(records), make_plan(scenarios), phase_mode="aa")

    assert (
        report["cohort_rates"]["targeted"]["before"]["treatment"]["pooled_pass_fraction"]
        == pytest.approx(1.0)
    )
    assert (
        report["cohort_rates"]["tripwire"]["before"]["treatment"]["pooled_pass_fraction"]
        == pytest.approx(0.0)
    )
    assert report["aa"]["by_cohort"]["targeted"]["n"] == 2
    assert report["aa"]["by_cohort"]["tripwire"]["n"] == 2
    assert report["aa"]["by_cohort"]["targeted"]["mean_absolute_difference"] == pytest.approx(0.0)
    assert report["aa"]["by_cohort"]["tripwire"]["mean_absolute_difference"] == pytest.approx(0.0)


def test_bootstrap_is_deterministic_and_records_its_seed_and_resamples():
    records: list[dict] = []
    scenarios = [
        ("S1", "T1", "targeted", 3),
        ("S2", "T1", "targeted", 3),
        ("S3", "T2", "targeted", 3),
    ]
    for sid, tid in (("S1", "T1"), ("S2", "T1")):
        emit_four(
            records,
            sid,
            tid,
            "targeted",
            before_treatment=[False] * 3,
            before_control=[False] * 3,
            after_treatment=[True] * 3,
            after_control=[False] * 3,
        )
    emit_four(
        records,
        "S3",
        "T2",
        "targeted",
        before_treatment=[False] * 3,
        before_control=[False] * 3,
        after_treatment=[True, False, False],
        after_control=[False] * 3,
    )

    plan = make_plan(scenarios, seed=4242, resamples=250)
    first = ap.analyze(make_obs(records), plan)
    second = ap.analyze(make_obs(records), plan)

    assert ap.render_json(first) == ap.render_json(second)
    assert first["bootstrap"]["seed"] == 4242
    assert first["bootstrap"]["resamples"] == 250
    assert first["bootstrap"]["template_count"] == 2
    interval = first["bootstrap"]["intervals"]["difference_in_differences"]
    assert interval["level"] == 0.95
    assert interval["lower"] <= interval["upper"]
    assert interval["lower"] <= first["before_after"]["difference_in_differences"]["template_weighted_mean"]
    assert interval["upper"] >= first["before_after"]["difference_in_differences"]["template_weighted_mean"]


# ---------------------------------------------------------------------------
# CLI behaviour: read-only, new file only, no clobber
# ---------------------------------------------------------------------------


def _write(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _complete_fixture() -> tuple[dict, dict]:
    records: list[dict] = []
    scenarios = [("S1", "T1", "targeted", 2)]
    emit_four(
        records,
        "S1",
        "T1",
        "targeted",
        before_treatment=[True, False],
        before_control=[True, False],
        after_treatment=[True, True],
        after_control=[True, False],
    )
    return make_obs(records), make_plan(scenarios, seed=9, resamples=50)


def test_cli_writes_only_a_new_file_and_refuses_overwrite(tmp_path: Path, capsys):
    observations, plan = _complete_fixture()
    obs_path = _write(tmp_path / "observations.json", observations)
    plan_path = _write(tmp_path / "plan.json", plan)
    out_path = tmp_path / "report.json"

    assert (
        ap.main(
            [
                "--observations",
                obs_path,
                "--plan",
                plan_path,
                "--format",
                "json",
                "--out",
                str(out_path),
            ]
        )
        == 0
    )
    first_content = out_path.read_text(encoding="utf-8")
    assert json.loads(first_content)["schema_version"] == ap.ANALYSIS_SCHEMA

    assert (
        ap.main(
            [
                "--observations",
                obs_path,
                "--plan",
                plan_path,
                "--format",
                "json",
                "--out",
                str(out_path),
            ]
        )
        == 3
    )
    assert out_path.read_text(encoding="utf-8") == first_content
    assert "refusing to overwrite" in capsys.readouterr().err


def test_cli_read_only_mode_and_help_do_not_write(tmp_path: Path, capsys):
    observations, plan = _complete_fixture()
    obs_path = _write(tmp_path / "observations.json", observations)
    plan_path = _write(tmp_path / "plan.json", plan)
    before = set(tmp_path.iterdir())

    assert ap.main(["--observations", obs_path, "--plan", plan_path]) == 0
    captured = capsys.readouterr()
    assert "agentplace pilot diagnostic analysis" in captured.out
    assert set(tmp_path.iterdir()) == before

    with pytest.raises(SystemExit) as exc:
        ap.main(["--help"])
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out
    assert set(tmp_path.iterdir()) == before


def test_cli_rejects_bad_input_without_creating_output(tmp_path: Path, capsys):
    obs_path = _write(
        tmp_path / "observations.json",
        {"schema_version": "wrong", "records": []},
    )
    plan_path = _write(tmp_path / "plan.json", make_plan([("S1", "T1", "targeted", 2)]))
    out_path = tmp_path / "report.json"

    assert (
        ap.main(
            [
                "--observations",
                obs_path,
                "--plan",
                plan_path,
                "--out",
                str(out_path),
            ]
        )
        == 2
    )
    assert not out_path.exists()
    assert "schema_version" in capsys.readouterr().err
