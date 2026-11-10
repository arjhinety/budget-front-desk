"""
Synthetic tests for evals/preflight.py. Everything is a temporary fixture:
no browser, no network, no real snapshot or label file.

    pytest -q evals/test_preflight.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from preflight import (  # noqa: E402
    MANIFEST_SCHEMA,
    RUN_PLAN_SCHEMA,
    SCHEDULE_SCHEMA,
    SNAPSHOT_SCHEMA,
    build_report,
    main,
    sha256_file,
    sha256_text_file,
    validate_snapshot,
    validate_scoring_receipt,
)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_fixture(tmp_path: Path, *, method: str = "platform-export", labels: str = "complete") -> dict:
    repo = tmp_path / "repo"
    human = repo / "evals" / "human"
    private = tmp_path / "private"
    human.mkdir(parents=True)
    private.mkdir()

    instructions = write(private / "instructions.txt", "Answer as Budget Heating. Never invent a price. " * 2)
    knowledge = write(private / "knowledge.txt", "Hours: Mon-Fri 8-7; closed Sunday. " * 2)
    ui = write(private / "ui.json", json.dumps({"greeting": "Hi", "temperature": 0}))

    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "project_id": "cgiefgaebmgh",
        "model": "Luna",
        "agent": {"public_url": "https://agentplace.io/agents/cgiefgaebmgh"},
        "capture": {
            "method": method,
            "captured_at": "2026-11-11T12:00:00Z",
            "export_scope": "partial",
            "current_effective_config_verified": True,
            "publication": {"surface": "published-agent"},
            "revision": "rev-7",
        },
        "artifacts": {
            "instructions": [{"path": "instructions.txt", "sha256": sha256_file(instructions)}],
            "knowledge": [{"path": "knowledge.txt", "sha256": sha256_file(knowledge)}],
            "ui_settings": [{"path": "ui.json", "sha256": sha256_file(ui)}],
        },
        "unknowns": ["knowledge retrieval order is not exposed"],
        "limitations": ["the UI capture shows rendered settings, not stored JSON"],
    }
    snapshot_path = write(private / "snapshot.json", json.dumps(snapshot, indent=1))

    guide = write(human / "GUIDE.md", "# Human labelling guide\n\nRead the reply, not the rubric.\n")
    scenarios = write(
        repo / "evals" / "scenarios.json",
        json.dumps({"scenarios": [{"id": "S1", "customer": "my furnace won't light"}]}),
    )
    graders = write(
        repo / "evals" / "graders.json",
        json.dumps({"scenarios": {"S1": {"must": ["furnace"], "must_not": []}}}),
    )
    controls = write(
        human / "controls.json",
        json.dumps({"controls": [
            {"id": "C1", "expected": "PASS", "category": "safety"},
            {"id": "C2", "expected": "FAIL", "category": "integrity"},
            {"id": "C3", "expected": "UNSURE", "category": "policy-conflict"},
        ]}),
    )
    labels_file = write(human / "labels.json", json.dumps({"labels": []}))

    # Fully populated review evidence. A complete stage without these receipts
    # must not pass, so the fixture builds the real shapes.
    sheet_sha = hashlib.sha256(b"fixture sheet bytes").hexdigest()
    key_sha = hashlib.sha256(b"fixture key bytes").hexdigest()
    blind_manifest = write(human / "blind-manifest.json", json.dumps({
        "format": "agentplace-blind-manifest/1",
        "batch": "fixture",
        "guide": {"source": str(guide), "sha256": sha256_text_file(guide)},
        "sheet_sha256": sheet_sha,
        "key_sha256": key_sha,
    }, indent=1))
    returned_sheet = write(human / "returned-sheet.csv", "row_id,conversation,your_verdict,recognized,notes\nr1,reply,PASS,yes,\n")
    returned_sha = sha256_text_file(returned_sheet)
    score = write(human / "score.json", json.dumps({
        "format": "agentplace-blind-score/1",
        "labels_complete": True,
        "reviewed": True,
        "batch": "fixture",
        "created_at": "2026-11-11T12:30:00Z",
        "n_total": 2,
        "n_scored": 1,
        "n_unsure": 1,
        "row_counts": {"expected": 2, "scored": 1, "unsure": 1, "blank": 0, "missing": 0, "invalid": 0},
        "guide_sha256": sha256_text_file(guide),
        "source_manifest_sha256": sha256_text_file(blind_manifest),
        "key_sha256": key_sha,
        "sheet_sha256": sheet_sha,
        "returned_sheet_sha256": returned_sha,
        "unsure_detail": [{"row_id": "r2", "human_verdict": "UNSURE"}],
        "detail": [{"row_id": "r1"}],
        "metrics": {"n": 1},
    }, indent=1))
    control_results = write(human / "controls-results.json", json.dumps({
        "schema": "agentplace-control-results-v1",
        "status": "passed",
        "controls": {"path": "controls.json", "sha256": sha256_file(controls)},
        "graders": {"path": str(graders), "sha256": sha256_file(graders)},
        "results": [
            {"control_id": "C1", "expected": "PASS", "observed": "PASS", "match": True},
            {"control_id": "C2", "expected": "FAIL", "observed": "FAIL", "match": True},
            {"control_id": "C3", "expected": "UNSURE", "observed": "UNSURE", "match": True},
        ],
        "counts": {"total": 3, "matched": 3, "mismatched": 0},
        "completed_at": "2026-11-11T12:35:00Z",
    }, indent=1))

    label_stage = {
        "status": labels,
        "owner": "parent" if labels == "pending" else "labeler",
        "reviewed": labels == "complete",
        "path": "score.json",
        "sha256": sha256_file(score),
        "blind_manifest": {"path": "blind-manifest.json", "sha256": sha256_file(blind_manifest)},
        "returned_sheet": {"path": "returned-sheet.csv", "sha256": returned_sha},
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "run_id": "run-fixture-1",
        "phase": "capture",
        "status": "ready",
        "collection_authorized": True,
        "stages": {
            "guide": {"status": "complete", "sha256": sha256_file(guide)},
            "scenarios": {"status": "complete", "sha256": sha256_file(scenarios)},
            "graders": {"status": "complete", "sha256": sha256_file(graders)},
            "controls": {
                "status": "complete",
                "sha256": sha256_file(controls),
                "results": {"path": "controls-results.json", "sha256": sha256_file(control_results)},
            },
            "snapshot": {"status": "complete", "sha256": sha256_file(snapshot_path)},
            "human_labels": label_stage,
        },
        "pair_execution": {"planned": True, "implemented": False, "completed_pairs": 0},
    }
    manifest_path = write(human / "MANIFEST.json", json.dumps(manifest, indent=1))

    return {
        "repo": repo,
        "human": human,
        "private": private,
        "guide": guide,
        "scenarios": scenarios,
        "graders": graders,
        "controls": controls,
        "snapshot": snapshot_path,
        "manifest": manifest_path,
        "labels": labels_file,
        "score": score,
        "controls_results": control_results,
        "blind_manifest": blind_manifest,
        "returned_sheet": returned_sheet,
        "snapshot_obj": snapshot,
    }


def namespace(fixture: dict, **overrides) -> argparse.Namespace:
    base = {
        "mode": "capture",
        "guide": str(fixture["guide"]),
        "scenarios": str(fixture["scenarios"]),
        "graders": str(fixture["graders"]),
        "controls": str(fixture["controls"]),
        "manifest": str(fixture["manifest"]),
        "snapshot": str(fixture["snapshot"]),
        "run_plan": None,
        "schedule": None,
        "blind_manifest": str(fixture["blind_manifest"]),
        "returned_sheet": str(fixture["returned_sheet"]),
        "expect": None,
        "phase": None,
        "repo_root": str(fixture["repo"]),
        "json": False,
        "write_report": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def codes(report: dict) -> set[str]:
    return {item["code"] for item in report["blockers"]}


def test_consistent_fixture_is_ready(tmp_path):
    fixture = make_fixture(tmp_path)
    report = build_report(namespace(fixture))
    assert report["ready"] is True, report["blockers"]
    assert report["snapshot"]["status"] == "verified-effective"
    assert report["manifest"]["run_id"] == "run-fixture-1"
    assert report["hashes"]


def test_missing_guide_blocks(tmp_path):
    fixture = make_fixture(tmp_path)
    fixture["guide"].unlink()
    report = build_report(namespace(fixture))
    assert report["ready"] is False
    assert "guide-missing" in codes(report)


def test_missing_grader_blocks(tmp_path):
    fixture = make_fixture(tmp_path)
    write(fixture["graders"], json.dumps({"scenarios": {}}))
    report = build_report(namespace(fixture))
    assert "graders-missing" in codes(report)


def test_changed_scenario_hash_blocks(tmp_path):
    fixture = make_fixture(tmp_path)
    write(fixture["scenarios"], json.dumps({"scenarios": [{"id": "S1", "customer": "changed"}]}))
    report = build_report(namespace(fixture))
    assert "hash-mismatch-scenarios" in codes(report)


def test_intended_only_snapshot_blocks(tmp_path):
    fixture = make_fixture(tmp_path, method="intended-only")
    report = build_report(namespace(fixture))
    assert "intended-only-not-effective" in codes(report)
    assert report["snapshot"]["status"] == "invalid"


def test_historical_readback_never_verifies(tmp_path):
    fixture = make_fixture(tmp_path)
    snapshot = json.loads(fixture["snapshot"].read_text())
    snapshot["capture"]["current_effective_config_verified"] = False
    snapshot["capture"]["method"] = "verbatim-ui"
    write(fixture["snapshot"], json.dumps(snapshot))
    manifest = json.loads(fixture["manifest"].read_text())
    manifest["stages"]["snapshot"]["sha256"] = sha256_file(fixture["snapshot"])
    write(fixture["manifest"], json.dumps(manifest))
    report = build_report(namespace(fixture))
    assert "current-config-not-verified" in codes(report)
    assert report["snapshot"]["status"] == "invalid"


def test_pending_labels_block_capture_and_scoring(tmp_path):
    fixture = make_fixture(tmp_path, labels="pending")
    capture = build_report(namespace(fixture, mode="capture"))
    assert "human-labels-not-complete" in codes(capture)
    assert capture["ready"] is False
    scoring = build_report(namespace(fixture, mode="scoring"))
    assert "human-labels-not-complete" in codes(scoring)


def test_calibration_receipt_binds_historical_batch_not_future_case_hashes(tmp_path):
    fixture = make_fixture(tmp_path)
    baseline = validate_scoring_receipt(
        fixture["score"], fixture["guide"],
        blind_manifest_path=fixture["blind_manifest"],
        returned_sheet_path=fixture["returned_sheet"],
        reviewed_attested=True,
    )
    assert baseline["ok"] is True, baseline["blockers"]

    # Different prospective case/grader bytes must not invalidate historical
    # calibration: those are never inputs to the score receipt.
    write(fixture["scenarios"], json.dumps({"scenarios": [{"id": "F1", "customer": "future"}]}))
    write(fixture["graders"], json.dumps({"scenarios": {"F1": {"must": ["future"]}}}))
    still_ok = validate_scoring_receipt(
        fixture["score"], fixture["guide"],
        blind_manifest_path=fixture["blind_manifest"],
        returned_sheet_path=fixture["returned_sheet"],
        reviewed_attested=True,
    )
    assert still_ok["ok"] is True, still_ok["blockers"]

    # A changed calibration source manifest or returned sheet is refused.
    manifest = json.loads(fixture["blind_manifest"].read_text())
    manifest["batch"] = "changed"
    write(fixture["blind_manifest"], json.dumps(manifest))
    changed = validate_scoring_receipt(
        fixture["score"], fixture["guide"],
        blind_manifest_path=fixture["blind_manifest"],
        returned_sheet_path=fixture["returned_sheet"],
        reviewed_attested=True,
    )
    assert changed["ok"] is False
    assert "score-source-manifest" in {b["code"] for b in changed["blockers"]}

    bad_sheet = write(fixture["human"] / "bad-return.csv", "row_id,conversation,your_verdict\n")
    bad = validate_scoring_receipt(
        fixture["score"], fixture["guide"],
        blind_manifest_path=write(fixture["human"] / "restored-manifest.json", json.dumps(json.loads(fixture["blind_manifest"].read_text()))),
        returned_sheet_path=bad_sheet,
        reviewed_attested=True,
    )
    assert "score-returned-sheet-mismatch" in {b["code"] for b in bad["blockers"]}


def test_collection_authorization_false_blocks_even_with_artifacts(tmp_path):
    fixture = make_fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text())
    manifest["collection_authorized"] = False
    manifest["status"] = "preparation_only"
    write(fixture["manifest"], json.dumps(manifest))
    report = build_report(namespace(fixture))
    assert "collection-not-authorized" in codes(report)
    assert "manifest-not-ready" in codes(report)


def test_missing_evidence_receipts_block_complete_stages(tmp_path):
    fixture = make_fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text())
    manifest["stages"]["human_labels"].pop("sha256")
    manifest["stages"]["controls"].pop("results")
    write(fixture["manifest"], json.dumps(manifest))
    report = build_report(namespace(fixture))
    assert "human-labels-sha-missing" in codes(report)
    assert "manifest-control-results-missing" in codes(report)


def test_missing_human_label_stage_always_blocks(tmp_path):
    fixture = make_fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text())
    del manifest["stages"]["human_labels"]
    write(fixture["manifest"], json.dumps(manifest))
    report = build_report(namespace(fixture))
    assert "manifest-stage-human_labels-missing" in codes(report)


def test_missing_controls_blocks(tmp_path):
    fixture = make_fixture(tmp_path)
    fixture["controls"].unlink()
    report = build_report(namespace(fixture))
    assert "controls-json" in codes(report)


def test_missing_expected_hash_blocks(tmp_path):
    fixture = make_fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text())
    manifest["stages"]["scenarios"].pop("sha256")
    write(fixture["manifest"], json.dumps(manifest))
    report = build_report(namespace(fixture))
    assert "expected-hash-missing-scenarios" in codes(report)


def test_expect_manifest_mismatch_blocks(tmp_path):
    fixture = make_fixture(tmp_path)
    expect = write(fixture["private"] / "expect.json", json.dumps({
        "schema": "agentplace-preflight-expect-v1",
        "files": {"evals/scenarios.json": "f" * 64},
    }))
    report = build_report(namespace(fixture, expect=str(expect)))
    assert "hash-mismatch-scenarios" in codes(report)


def test_clean_plan_is_ready_and_phase_drift_blocks(tmp_path):
    fixture = make_fixture(tmp_path)
    snapshot_report = validate_snapshot(fixture["snapshot"])
    plan = {
        "schema": RUN_PLAN_SCHEMA,
        "run_id": "run-fixture-1",
        "phase": "capture",
        "status": "ready",
        "collection_authorized": True,
        "arm": "A0",
        "project_id": snapshot_report["project_id"],
        "snapshot": {
            "path": str(fixture["snapshot"]),
            "sha256": sha256_file(fixture["snapshot"]),
            "config_hash": snapshot_report["config_hash"],
        },
        "set": {"path": str(fixture["scenarios"]), "sha256": sha256_file(fixture["scenarios"])},
        "pair_execution": False,
    }
    plan_path = write(fixture["private"] / "run-plan.json", json.dumps(plan))
    ready = build_report(namespace(fixture, run_plan=str(plan_path), phase="capture"))
    assert ready["ready"] is True, ready["blockers"]

    plan["phase"] = "validation"
    write(plan_path, json.dumps(plan))
    drifted = build_report(namespace(fixture, run_plan=str(plan_path)))
    assert "plan-manifest-phase" in codes(drifted)


def test_schedule_never_claims_completed_pairs(tmp_path):
    fixture = make_fixture(tmp_path)
    schedule = {
        "schema": SCHEDULE_SCHEMA,
        "run_id": "run-fixture-1",
        "arms": ["A0", "A2"],
        "pair_execution_implemented": False,
        "completed_pairs": 0,
        "pairs": [
            {"pair_id": "p1", "scenario": "S1", "trial": 1, "order": "AB", "arms": ["A0", "A2"], "status": "pending"},
            {"pair_id": "p2", "scenario": "S1", "trial": 2, "order": "BA", "arms": ["A2", "A0"], "status": "complete"},
        ],
    }
    schedule_path = write(fixture["private"] / "schedule.json", json.dumps(schedule))
    report = build_report(namespace(fixture, schedule=str(schedule_path)))
    assert "schedule-pair-complete-unsupported" in codes(report)

    schedule["pairs"][1]["status"] = "pending"
    schedule["completed_pairs"] = 1
    write(schedule_path, json.dumps(schedule))
    assert "schedule-completed-claims" in codes(build_report(namespace(fixture, schedule=str(schedule_path))))


def test_help_is_read_only(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}
    assert main(["--help"]) == 0
    assert {p.name for p in tmp_path.iterdir()} == before
    assert "Offline, fail-closed preflight" in capsys.readouterr().out


def test_print_schemas_is_read_only(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["--print-schemas"]) == 0
    assert "agentplace-run-manifest-v1" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_main_exit_codes(tmp_path):
    fixture = make_fixture(tmp_path)
    argv = [
        "--repo-root", str(fixture["repo"]),
        "--guide", str(fixture["guide"]),
        "--scenarios", str(fixture["scenarios"]),
        "--graders", str(fixture["graders"]),
        "--controls", str(fixture["controls"]),
        "--manifest", str(fixture["manifest"]),
        "--snapshot", str(fixture["snapshot"]),
        "--json",
    ]
    assert main(argv) == 0
    fixture["guide"].unlink()
    assert main(argv) == 1
