from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cases = module_at("prepare_next_cases", ROOT / "datasets/prepare_next_cases.py")


def specimen():
    return {
        "schema_version": "agentplace.fresh-cases.v1", "author": "synthetic offline fixture",
        "cases": [{"id": f"F-{i:03d}", "template_id": f"group-{(i - 1) // 4}",
                   "cohort": "targeted" if i <= 24 else "tripwire",
                   "trials": 3 if i <= 24 else 1, "customer": f"Synthetic case {i}",
                   "required_fact_ids": ["hours_weekday"], "expected_behavior": "Fixture only.",
                   "allowed_clarifications": []} for i in range(1, 49)],
    }


def test_candidate_case_counts_are_diagnostic_not_readiness():
    result = cases.validate(specimen(), {"hours_weekday"})
    assert result["planned_conversations_per_arm_phase"] == 96
    assert result["status"] == "structurally_valid_not_semantically_approved_not_frozen"


@pytest.mark.parametrize("change", ["duplicate-id", "duplicate-message", "missing-fact", "wrong-repeats", "missing-author", "one-template"])
def test_invalid_future_case_set_refused(change):
    data = specimen()
    if change == "duplicate-id":
        data["cases"][1]["id"] = data["cases"][0]["id"]
    elif change == "duplicate-message":
        data["cases"][1]["customer"] = data["cases"][0]["customer"].upper()
    elif change == "missing-fact":
        data["cases"][0]["required_fact_ids"] = ["invented_fact"]
    elif change == "wrong-repeats":
        data["cases"][0]["trials"] = 1
    elif change == "missing-author":
        data["author"] = ""
    else:
        for row in data["cases"]:
            row["template_id"] = "one-group"
    with pytest.raises(ValueError):
        cases.validate(data, {"hours_weekday"})


def test_case_packet_is_explicitly_not_an_api_run():
    result = cases.packet(ROOT)
    assert result["api_called"] is False
    assert result["status"] == "prepared_not_sent_not_frozen"
    assert result["provider_hint"]["response_format"] == {"type": "json_object"}
    assert "human calibration reviewed" in result["required_before_authoring"]
    assert result["source_hashes"]["guide"]["sha256"]


def test_history_audit_is_read_only_and_does_not_assign_builds():
    audit_module = module_at("audit_history", ROOT / "evals/audit_history.py")
    source = ROOT / "evals/results/A5.json"
    before = source.read_bytes()
    result = audit_module.audit(ROOT)
    assert [b["records"] for b in result["blocks"]] == [94, 71]
    assert [b["next_step_heading_count"] for b in result["blocks"]] == [91, 0]
    assert result["historical_scores_changed"] is False
    assert "cannot be recovered" in result["interpretation"]
    assert source.read_bytes() == before


def test_recovered_config_never_claims_current_publication():
    metadata = json.loads((ROOT / "build/recovered/cgiefgaebmgh/capture.json").read_text(encoding="utf-8"))
    assert metadata["current_effective_config_verified"] is False
    assert metadata["publication_revision"] is None
    assert metadata["method"] == "historical_tool_readback_ui"


@pytest.mark.parametrize("bad_shape", ["top-level", "case-string", "id-number", "cohort-list"])
def test_malformed_author_json_is_a_validation_error(bad_shape):
    data = specimen()
    if bad_shape == "top-level":
        data = []
    elif bad_shape == "case-string":
        data["cases"][5] = "not an object"
    elif bad_shape == "id-number":
        data["cases"][0]["id"] = 1
    else:
        data["cases"][0]["cohort"] = []
    with pytest.raises(ValueError):
        cases.validate(data, {"hours_weekday"})
