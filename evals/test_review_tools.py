#!/usr/bin/env python3
"""Offline tests for the blind review tooling.

No network, no live agent, no real capture required: every fixture is synthetic
and every grader is a stub. Run with ``pytest evals/test_review_tools.py``.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS))

import blind_export  # noqa: E402
import blind_score  # noqa: E402
import review_common as rc  # noqa: E402
import sealed_score  # noqa: E402


# --------------------------------------------------------------------------
# fixtures and helpers
# --------------------------------------------------------------------------

LONG = ("Welcome to Budget Heating, Cooling & Plumbing. We're a family-owned "
        "company in St. Peters, serving the area since 2009. I'll first sort out "
        "whether your situation needs emergency help, a diagnostic visit, or a "
        "free estimate, and explain why. You can also call or text (636) 887-2800.")


def single_record(rid: str, trial: int, reply: str = LONG,
                  customer: str = "my ac stopped cooling") -> dict:
    thread = f"Home\n{customer}\n{reply[:140]}\n{reply}\nAsk me anything\nSpeak"
    return {"id": rid, "trial": trial, "customer": customer, "thread": thread}


def multi_record(rid: str, trial: int, replies: list[str], turns: list[str] | None = None) -> dict:
    turns = turns or ["my ac stopped cooling", "can you come saturday"]
    return {"id": rid, "trial": trial, "turns": turns, "replies": replies,
            "family": "diagnostic", "at": "2026-11-07T17:07:16.000Z", "chars": 900}


def write_results(directory: Path, arm: str, records: list[dict], **extra) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{arm}.json"
    payload = {"arm": arm, "agent": "project:test", "records": records}
    payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def make_guide(directory: Path, text: str = "# guide\n") -> Path:
    path = directory / "GUIDE.md"
    path.write_text(text, encoding="utf-8")
    return path


def make_grader(rows_by_arm: dict[str, list[dict]]):
    def grader(kind: str, arm: str, set_name=None):
        if arm not in rows_by_arm:
            raise AssertionError(f"unexpected arm {arm}")
        return [dict(r) for r in rows_by_arm[arm]]
    return grader


def read_sheet_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_sheet_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=rc.SHEET_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_batch(tmp_path: Path, records: list[dict], graded: list[dict], arm: str = "SEALED-A0"):
    res = tmp_path / "results"
    path = write_results(res, arm, records)
    out = tmp_path / "batch"
    result = rc.export_batch([rc.InputSpec(path, "sealed" if arm.startswith("SEALED") else None)],
                             out, take_all=True, guide=make_guide(tmp_path),
                             grader_read_dir=res, grader=make_grader({arm: graded}))
    return res, out, result


# --------------------------------------------------------------------------
# schema inference and grader binding
# --------------------------------------------------------------------------

def test_infer_kind_from_schema_and_stem():
    assert rc.infer_kind("SEALED-A0", [{"id": "SD-01", "replies": []}]) == "sealed"
    assert rc.infer_kind("X-ARM", [{"id": "SD-01", "replies": []}]) == "sealed"
    assert rc.infer_kind("MT-A5", [{"id": "MT-C01", "replies": []}]) == "mt"
    assert rc.infer_kind("BIG-A0", [{"id": "G-1", "thread": ""}]) == "single"
    with pytest.raises(rc.InputError):
        rc.infer_kind("WEIRD", [{"id": "x"}])


def test_bind_with_trial_and_sealed_without_trial():
    records = [{"id": "SD-01", "trial": 1}, {"id": "SD-02", "trial": 1}]
    graded = [{"id": "SD-01", "pass": True}, {"id": "SD-02", "pass": False}]
    bound = rc.bind_graded(records, graded)
    assert bound[("SD-01", 1)]["pass"] is True
    assert bound[("SD-02", 1)]["pass"] is False


def test_bind_rejects_row_count_mismatch():
    with pytest.raises(rc.GraderError):
        rc.bind_graded([{"id": "SD-01", "trial": 1}], [])


def test_bind_rejects_ambiguous_duplicate_ids_in_sealed_output():
    records = [{"id": "SD-01", "trial": 1}, {"id": "SD-01", "trial": 2}]
    graded = [{"id": "SD-01", "pass": True}, {"id": "SD-01", "pass": False}]
    with pytest.raises(rc.GraderError, match="cannot be bound"):
        rc.bind_graded(records, graded)


def test_bind_rejects_unknown_graded_ids():
    records = [{"id": "SD-01", "trial": 1}]
    graded = [{"id": "SD-99", "trial": 1, "pass": True}]
    with pytest.raises(rc.GraderError):
        rc.bind_graded(records, graded)


def test_parse_json_array_survives_prefix_noise_and_rejects_garbage():
    assert rc.parse_json_array('warning\n[{"id": "a", "pass": true}]') == [{"id": "a", "pass": True}]
    with pytest.raises(rc.GraderError):
        rc.parse_json_array("no json here")


def test_run_grader_reports_subprocess_failure(monkeypatch):
    class Boom:
        returncode = 3
        stdout = ""
        stderr = "FROZEN mismatch"

    monkeypatch.setattr(rc.subprocess, "run", lambda *a, **k: Boom())
    with pytest.raises(rc.GraderError, match="FROZEN mismatch"):
        rc.run_grader("sealed", "SEALED-A0")


def test_verify_results_input_checks_bytes(tmp_path):
    res = tmp_path / "results"
    good = write_results(res, "SEALED-A0", [{"id": "SD-01", "trial": 1}])
    copy = tmp_path / "copy.json"
    copy.write_bytes(good.read_bytes())
    assert rc.verify_results_input(copy, "SEALED-A0", res) == copy.resolve()

    copy.write_text(copy.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(rc.InputError, match="differs"):
        rc.verify_results_input(copy, "SEALED-A0", res)


# --------------------------------------------------------------------------
# cleaning
# --------------------------------------------------------------------------

def test_preview_prefix_is_dropped_and_greeting_kept():
    thread = (f"Home\nmy ac stopped cooling\n{LONG[:150]}\n{LONG}\nAsk me anything\nSpeak")
    cleaned = rc.clean_text(thread, "my ac stopped cooling")
    assert cleaned.count("Welcome to Budget Heating") == 1
    assert "family-owned" in cleaned
    assert "Home" not in cleaned.split("\n")
    assert "Ask me anything" not in cleaned


def test_greeting_with_different_following_text_is_preserved():
    reply = ("Welcome to Budget Heating, Cooling & Plumbing.\n\n"
             "A diagnostic visit is $99 and covers the trip and diagnosis.")
    assert rc.clean_text(reply).startswith("Welcome to Budget Heating")


def test_short_preview_heading_is_dropped_once():
    reply = ("Saturday, November 14\n\nSaturday, November 14 is within our Saturday "
             "hours of 9:00 a.m. to 5:00 p.m., and a Saturday appointment adds $50.")
    cleaned = rc.clean_text(reply)
    assert cleaned.count("Saturday, November 14") == 1


def test_short_customer_word_does_not_corrupt_agent_reply():
    thread = "Home\nhi\nHi, Casey. This inspection covers anything on the system.\nSpeak"
    cleaned = rc.clean_text(thread, "hi")
    assert cleaned.startswith("Hi, Casey.")
    assert "This inspection covers anything" in cleaned
    assert [ln for ln in cleaned.split("\n") if ln == "hi"] == []


def test_restated_customer_phrase_is_preserved():
    text = "Since my ac stopped cooling, this is a diagnostic visit."
    assert rc.clean_text(text, "my ac stopped cooling") == text


def test_customer_marker_is_removed_at_most_once():
    cleaned = rc.clean_text("Home\nhi\nhi\nthanks", "hi")
    assert cleaned.split("\n") == ["hi", "thanks"]


def test_multi_turn_reply_is_never_customer_stripped():
    rec = {"id": "MT-C01", "trial": 1, "turns": ["hi", "ok"],
           "replies": ["Hi, Casey. This is anything but broken.", "Thanks."]}
    conv = rc.render_conversation(rec, "mt")
    assert "Hi, Casey" in conv
    assert "This is anything but broken." in conv


def test_short_complete_reply_is_not_an_exclusion():
    # "No, closed Sunday." is a complete answer; length is not a failure.
    rec = {"id": "SD-01", "trial": 1, "turns": ["can you come sunday"], "replies": ["No, closed Sunday."]}
    assert rc.classify_record(rec) is None


def test_terse_service_reply_is_not_an_exclusion():
    rec = {"id": "SD-01", "trial": 1, "turns": ["can you come"], "replies": ["Call or text (636) 887-2800."]}
    assert rc.classify_record(rec) is None


def test_only_empty_replies_are_excluded():
    rec = {"id": "SD-01", "trial": 1, "turns": ["hi"], "replies": ["   "]}
    assert rc.classify_record(rec) == ("EMPTY_REPLIES", "no reply text captured")


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------

def test_export_sheet_is_blind_and_key_holds_identity(tmp_path):
    records = [multi_record("SD-01", 1, [LONG, LONG]),
               multi_record("SD-02", 1, [LONG, LONG])]
    graded = [{"id": "SD-01", "pass": True}, {"id": "SD-02", "pass": False}]
    _res, out, _result = build_batch(tmp_path, records, graded)

    header = (out / "sheet.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(rc.SHEET_COLUMNS)
    sheet_text = (out / "sheet.csv").read_text(encoding="utf-8")
    assert "SD-01" not in sheet_text and "SD-02" not in sheet_text
    assert "SEALED-A0" not in sheet_text
    assert "PASS" not in sheet_text and "FAIL" not in sheet_text
    assert "CUSTOMER:" in sheet_text and "AGENT:" in sheet_text

    key = json.loads((out / "private" / "key.json").read_text(encoding="utf-8"))
    assert len(key["rows"]) == 2
    identities = {(v["arm"], v["id"], v["trial"]) for v in key["rows"].values()}
    assert identities == {("SEALED-A0", "SD-01", 1), ("SEALED-A0", "SD-02", 1)}
    manifest = json.loads((out / "private" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["selected"] == 2
    assert manifest["inputs"][0]["kind"] == "sealed"


def test_export_refuses_legacy_blind_and_nonempty_out(tmp_path):
    with pytest.raises(rc.ReviewError, match="evals/blind"):
        rc.ensure_writable_out(rc.LEGACY_BLIND)

    records = [multi_record("SD-01", 1, [LONG, LONG])]
    graded = [{"id": "SD-01", "pass": True}]
    res = tmp_path / "results"
    path = write_results(res, "SEALED-A0", records)
    out = tmp_path / "batch"
    out.mkdir()
    (out / "occupied.txt").write_text("x", encoding="utf-8")
    with pytest.raises(rc.ReviewError, match="already contains files"):
        rc.export_batch([rc.InputSpec(path, "sealed")], out, take_all=True,
                        guide=make_guide(tmp_path),
                        grader_read_dir=res, grader=make_grader({"SEALED-A0": graded}))


def test_export_does_not_modify_historical_blind_artifacts(tmp_path):
    before = {p.name: rc.sha256_file(p) for p in rc.LEGACY_BLIND.iterdir() if p.is_file()}
    records = [multi_record("SD-01", 1, [LONG, LONG])]
    build_batch(tmp_path, records, [{"id": "SD-01", "pass": True}])
    after = {p.name: rc.sha256_file(p) for p in rc.LEGACY_BLIND.iterdir() if p.is_file()}
    assert before == after


def test_stratified_sample_contains_passes_and_failures(tmp_path):
    records = [multi_record(f"SD-{i:02d}", 1, [LONG, LONG]) for i in range(1, 9)]
    graded = [{"id": r["id"], "pass": i >= 4} for i, r in enumerate(records)]
    res = tmp_path / "results"
    path = write_results(res, "MT-A5", records)
    out = tmp_path / "batch"
    result = rc.export_batch([rc.InputSpec(path, "mt")], out, n=6,
                             guide=make_guide(tmp_path),
                             grader_read_dir=res, grader=make_grader({"MT-A5": graded}))
    assert result["selected"] == 6
    assert result["selection"]["strata_selected"]["pass"] >= 1
    assert result["selection"]["strata_selected"]["fail"] >= 1
    assert result["selection"]["selection_bias"]


def test_exclusions_carry_reasons_and_duplicates(tmp_path):
    records = [
        multi_record("SD-01", 1, [LONG, LONG]),
        multi_record("SD-02", 1, [LONG, "Something went wrong loading this page"]),
        multi_record("SD-03", 1, [LONG, LONG]),
        multi_record("SD-03", 1, [LONG, LONG]),
        multi_record("SD-04", 1, [LONG, ""]),
        multi_record("SD-05", 1, ["Call or text (636) 887-2800."], turns=["can you come"]),
        {"id": "SD-06", "trial": 1, "error": "browser died"},
        {"id": "SD-07", "trial": 1, "turns": ["a", "b"], "replies": [LONG]},
    ]
    graded = [
        {"id": "SD-01", "trial": 1, "pass": True},
        {"id": "SD-02", "trial": 1, "pass": True},
        {"id": "SD-03", "trial": 1, "pass": True},
        {"id": "SD-03", "trial": 1, "pass": True},
        {"id": "SD-04", "trial": 1, "pass": True},
        {"id": "SD-05", "trial": 1, "pass": True},
        {"id": "SD-06", "trial": 1, "pass": False},
        {"id": "SD-07", "trial": 1, "pass": True},
    ]
    res = tmp_path / "results"
    path = write_results(res, "SEALED-A0", records)
    result = rc.export_batch([rc.InputSpec(path, "sealed")], tmp_path / "batch",
                             take_all=True, guide=make_guide(tmp_path),
                             grader_read_dir=res,
                             grader=make_grader({"SEALED-A0": graded}))
    reasons = [e["reason"] for e in result["exclusions"]]
    assert "ARTEFACT" in reasons
    assert "DUPLICATE_IDENTITY" in reasons
    assert "EMPTY_REPLY" in reasons
    assert "STORED_ERROR" in reasons
    assert result["unresolved"][0]["reason"] == "TURN_REPLY_MISMATCH"
    assert result["selected"] == 3           # SD-01, SD-03 (first), SD-05


def test_guide_is_copied_and_hashed(tmp_path):
    records = [multi_record("SD-01", 1, [LONG, LONG])]
    res = tmp_path / "results"
    path = write_results(res, "SEALED-A0", records)
    guide = tmp_path / "GUIDE.md"
    guide.write_text("# guide\n", encoding="utf-8")
    result = rc.export_batch([rc.InputSpec(path, "sealed")], tmp_path / "batch",
                             take_all=True, guide=guide, grader_read_dir=res,
                             grader=make_grader({"SEALED-A0": [{"id": "SD-01", "pass": True}]}))
    assert (tmp_path / "batch" / "GUIDE.md").read_text(encoding="utf-8") == "# guide\n"
    assert result["guide"]["sha256"] == rc.sha256_file(guide)


def test_single_set_is_inferred_from_records_not_arm_name():
    assert rc.infer_single_set([{"id": "G-D-HVAC-STCHAR", "split": "big"}]) == "scenarios-big"
    assert rc.infer_single_set([{"id": "G-1"}]) == "scenarios-big"
    assert rc.infer_single_set([{"id": "T01", "split": "tuning"}]) == "scenarios"
    assert rc.infer_single_set([{"id": "T01"}], "scenarios-big") == "scenarios-big"


def test_missing_rubric_is_a_refusal_not_an_empty_pass():
    with pytest.raises(rc.GraderError, match="no rubric|no scenario"):
        rc.validate_single_set("scenarios", [{"id": "G-D-HVAC-STCHAR", "split": "big"}])
    info = rc.validate_single_set("scenarios-big", [{"id": "G-D-HVAC-STCHAR"}])
    assert info["set"] == "scenarios-big"


def test_conversation_arms_refuse_a_missing_rubric():
    assert rc.validate_conversation_coverage("mt", [{"id": "MT-C01"}]) is None
    with pytest.raises(rc.GraderError, match="no rubric"):
        rc.validate_conversation_coverage("mt", [{"id": "NOPE-1"}])
    with pytest.raises(rc.GraderError, match="no rubric"):
        rc.validate_conversation_coverage("sealed", [{"id": "NOPE-1"}])


def test_alternate_read_dir_needs_an_injected_grader(tmp_path):
    records = [multi_record("SD-01", 1, [LONG, LONG])]
    res = tmp_path / "results"
    path = write_results(res, "SEALED-A0", records)
    with pytest.raises(rc.InputError, match="injected grader"):
        rc.prepare_inputs([rc.InputSpec(path, "sealed")], grader_read_dir=res)


def test_export_records_the_set_it_graded_with(tmp_path):
    records = [{"id": "G-1", "trial": 1, "split": "big", "customer": "my ac is broken",
                "thread": "Home\nmy ac is broken\n" + LONG + "\nSpeak"}]
    res = tmp_path / "results"
    path = write_results(res, "A5", records)
    batch = rc.prepare_inputs([rc.InputSpec(path, "single")], grader_read_dir=res,
                              grader=make_grader({"A5": [{"id": "G-1", "trial": 1, "pass": True}]}))
    assert batch.inputs[0]["set"] == "scenarios-big"
    assert batch.candidates[0].kind == "single"


def test_export_requires_a_guide(tmp_path):
    records = [multi_record("SD-01", 1, [LONG, LONG])]
    res = tmp_path / "results"
    path = write_results(res, "SEALED-A0", records)
    with pytest.raises(rc.ReviewError, match="guide is required"):
        rc.export_batch([rc.InputSpec(path, "sealed")], tmp_path / "batch", take_all=True,
                        guide=None, grader_read_dir=res,
                        grader=make_grader({"SEALED-A0": [{"id": "SD-01", "pass": True}]}))


def test_any_empty_turn_excludes_the_conversation(tmp_path):
    records = [multi_record("SD-01", 1, [LONG, LONG]),
               multi_record("SD-02", 1, ["", LONG])]
    graded = [{"id": "SD-01", "pass": True}, {"id": "SD-02", "pass": True}]
    res = tmp_path / "results"
    path = write_results(res, "SEALED-A0", records)
    result = rc.export_batch([rc.InputSpec(path, "sealed")], tmp_path / "batch",
                             take_all=True, guide=make_guide(tmp_path),
                             grader_read_dir=res, grader=make_grader({"SEALED-A0": graded}))
    assert result["selected"] == 1
    assert [e["reason"] for e in result["exclusions"]] == ["EMPTY_REPLY"]


# --------------------------------------------------------------------------
# returned sheet validation
# --------------------------------------------------------------------------

def test_shuffled_return_is_joined_by_id(tmp_path):
    records = [multi_record(f"SD-0{i}", 1, [LONG, LONG]) for i in (1, 2, 3)]
    graded = [{"id": "SD-01", "pass": True}, {"id": "SD-02", "pass": False},
              {"id": "SD-03", "pass": True}]
    res, out, _result = build_batch(tmp_path, records, graded)
    rows = read_sheet_rows(out / "sheet.csv")
    verdicts = {"SD-01": "FAIL", "SD-02": "FAIL", "SD-03": "PASS"}
    key = json.loads((out / "private" / "key.json").read_text(encoding="utf-8"))
    for row in rows:
        row["your_verdict"] = verdicts[key["rows"][row["row_id"]]["id"]]
    write_sheet_rows(out / "sheet.csv", list(reversed(rows)))
    score = rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")
    assert score["returned_out_of_order"] is True
    assert score["metrics"]["n"] == 3
    by_id = {d["id"]: (d["human_verdict"], d["grader_verdict"]) for d in score["detail"]}
    assert by_id == {"SD-01": ("FAIL", "PASS"), "SD-02": ("FAIL", "FAIL"),
                     "SD-03": ("PASS", "PASS")}


def _prepared_sheet(tmp_path):
    records = [multi_record("SD-01", 1, [LONG, LONG]), multi_record("SD-02", 1, [LONG, LONG])]
    graded = [{"id": "SD-01", "pass": True}, {"id": "SD-02", "pass": False}]
    res, out, _result = build_batch(tmp_path, records, graded)
    rows = read_sheet_rows(out / "sheet.csv")
    for row in rows:
        row["your_verdict"] = "PASS"
    return out, rows


def test_altered_conversation_cell_is_rejected(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    rows[0]["conversation"] = rows[0]["conversation"] + " extra"
    write_sheet_rows(out / "sheet.csv", rows)
    with pytest.raises(rc.LabelSheetError, match="altered"):
        rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")


def test_duplicate_injected_and_missing_ids_are_rejected(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    write_sheet_rows(out / "sheet.csv", rows + [dict(rows[0])])
    with pytest.raises(rc.LabelSheetError, match="duplicate"):
        rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")

    injected = [dict(rows[0])]
    injected[0]["row_id"] = "R9999"
    write_sheet_rows(out / "sheet.csv", injected + rows[1:])
    with pytest.raises(rc.LabelSheetError, match="not in the private key"):
        rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")

    write_sheet_rows(out / "sheet.csv", rows[:-1])
    with pytest.raises(rc.LabelSheetError, match="missing"):
        rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")


def test_blank_and_invented_verdicts_are_rejected(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    rows[0]["your_verdict"] = ""
    write_sheet_rows(out / "sheet.csv", rows)
    with pytest.raises(rc.LabelSheetError, match="blank"):
        rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")

    rows[0]["your_verdict"] = "MAYBE"
    write_sheet_rows(out / "sheet.csv", rows)
    with pytest.raises(rc.LabelSheetError, match="not PASS, FAIL or UNSURE"):
        rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")


def test_score_receipt_fields_are_explicit(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    # A blank export must be refused; submit the filled sheet to score.
    write_sheet_rows(out / "sheet.csv", rows)
    key = json.loads((out / "private" / "key.json").read_text(encoding="utf-8"))
    manifest_path = out / "private" / "manifest.json"
    result = rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")
    assert result["format"] == "agentplace-blind-score/1"
    assert result["labels_complete"] is True
    assert result["guide_sha256"] == key["guide"]["sha256"]
    assert result["source_manifest_sha256"] == rc.content_hash(manifest_path)
    assert result["key_sha256"] == rc.content_hash(out / "private" / "key.json")
    # sheet_sha256 is the frozen blank export (same as key/manifest), NOT the
    # returned labelled file; returned_sheet_sha256 binds what came back.
    assert result["sheet_sha256"] == key["sheet_sha256"]
    assert result["returned_sheet_sha256"] == rc.content_hash(out / "sheet.csv")
    assert result["sheet_sha256"] != result["returned_sheet_sha256"]
    assert result["row_counts"] == {"expected": 2, "scored": 2, "unsure": 0,
                                    "blank": 0, "missing": 0, "invalid": 0}
    assert result["n_scored"] + result["n_unsure"] == result["n_total"] == 2


def test_unsure_detail_preserves_identity_and_notes(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    rows[0]["your_verdict"] = "UNSURE"
    rows[0]["notes"] = "policy underdetermined"
    rows[0]["recognized"] = "yes"
    write_sheet_rows(out / "sheet.csv", rows)
    result = rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")
    assert result["n_unsure"] == 1 and result["n_scored"] == 1
    assert len(result["unsure_detail"]) == 1
    entry = result["unsure_detail"][0]
    assert entry["row_id"] == rows[0]["row_id"]
    assert entry["human_verdict"] == "UNSURE"
    assert entry["notes"] == "policy underdetermined"
    assert entry["recognized"] == "yes"
    assert entry["id"] and entry["trial"] is not None
    assert all(d["human_verdict"] != "UNSURE" for d in result["detail"])
    assert result["row_counts"]["unsure"] == 1
    assert result["row_counts"]["scored"] == 1


def test_renamed_column_is_rejected(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    with (out / "sheet.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["row", "conversation", "your_verdict", "recognized", "notes"])
        for row in rows:
            writer.writerow([row[c] for c in rc.SHEET_COLUMNS])
    with pytest.raises(rc.LabelSheetError, match="header"):
        rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")


def test_altered_guide_is_rejected(tmp_path):
    records = [multi_record("SD-01", 1, [LONG, LONG])]
    res = tmp_path / "results"
    path = write_results(res, "SEALED-A0", records)
    guide = tmp_path / "GUIDE.md"
    guide.write_text("# guide\n", encoding="utf-8")
    out = tmp_path / "batch"
    rc.export_batch([rc.InputSpec(path, "sealed")], out, take_all=True,
                    guide=guide, grader_read_dir=res,
                    grader=make_grader({"SEALED-A0": [{"id": "SD-01", "pass": True}]}))
    rows = read_sheet_rows(out / "sheet.csv")
    rows[0]["your_verdict"] = "PASS"
    write_sheet_rows(out / "sheet.csv", rows)
    guide.write_text("# guide, edited\n", encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="guide hash"):
        rc.score_sheet(out / "sheet.csv", out / "private" / "key.json", guide=guide)


def test_unsure_rows_are_counted_not_scored(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    rows[0]["your_verdict"] = "UNSURE"
    rows[0]["recognized"] = "yes"
    write_sheet_rows(out / "sheet.csv", rows)
    score = rc.score_sheet(out / "sheet.csv", out / "private" / "key.json")
    assert score["n_scored"] == 1
    assert score["n_unsure"] == 1
    assert score["recognized"]["yes"] == 1


def _score_ready(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    return out, out / "private" / "key.json", out / "private" / "manifest.json"


def test_scoring_requires_the_private_manifest(tmp_path):
    out, key_path, manifest_path = _score_ready(tmp_path)
    manifest_path.unlink()
    with pytest.raises(rc.LabelSheetError, match="no private manifest"):
        rc.score_sheet(out / "sheet.csv", key_path)


def test_scoring_refuses_a_corrupt_manifest(tmp_path):
    out, key_path, manifest_path = _score_ready(tmp_path)
    manifest_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="not valid JSON"):
        rc.score_sheet(out / "sheet.csv", key_path)


def test_scoring_refuses_a_key_edited_after_export(tmp_path):
    out, key_path, _manifest_path = _score_ready(tmp_path)
    key = json.loads(key_path.read_text(encoding="utf-8"))
    key["rows"]["R0001"]["grader_verdict"] = "FAIL"
    key_path.write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="key content hash"):
        rc.score_sheet(out / "sheet.csv", key_path)


def test_scoring_refuses_incoherent_manifest(tmp_path):
    out, key_path, manifest_path = _score_ready(tmp_path)
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    batch_bad = dict(original, batch="someone-elses-batch")
    manifest_path.write_text(json.dumps(batch_bad), encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="batch"):
        rc.score_sheet(out / "sheet.csv", key_path)

    receipts_bad = dict(original, inputs=[])
    manifest_path.write_text(json.dumps(receipts_bad), encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="no source receipts"):
        rc.score_sheet(out / "sheet.csv", key_path)

    guide_bad = json.loads(json.dumps(original))
    guide_bad["guide"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(guide_bad), encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="guide hash"):
        rc.score_sheet(out / "sheet.csv", key_path)


def test_scoring_refuses_a_batch_without_a_frozen_guide(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    for row in rows:
        row["your_verdict"] = "PASS"
    write_sheet_rows(out / "sheet.csv", rows)
    key_path = out / "private" / "key.json"
    key = json.loads(key_path.read_text(encoding="utf-8"))
    key["guide"] = None
    key_path.write_text(json.dumps(key), encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="no guide hash"):
        rc.score_sheet(out / "sheet.csv", key_path)


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------

def test_ac1_hand_calculation():
    human = ["PASS", "PASS", "PASS", "FAIL", "FAIL"]
    machine = ["PASS", "PASS", "FAIL", "FAIL", "FAIL"]
    ac1, reason = rc.gwet_ac1(human, machine)
    assert reason is None
    assert ac1 == pytest.approx(0.6)          # po=0.8, p=0.5, pe=2*0.5*0.5=0.5


def test_kappa_degenerate_is_null_with_reason():
    kappa, reason = rc.cohen_kappa(["PASS"] * 4, ["PASS"] * 4)
    assert kappa is None
    assert "degenerate" in reason
    # AC1 stays defined where kappa does not: pe = 2*p*(1-p) = 0 when every label
    # is PASS, so the statistic is 1.0 rather than 0/0.
    ac1, ac1_reason = rc.gwet_ac1(["PASS"] * 4, ["PASS"] * 4)
    assert ac1 == pytest.approx(1.0)
    assert ac1_reason is None


def test_zero_overlap_reports_no_agreement():
    result = rc.score_pairs([], [])
    assert result["n"] == 0
    assert result["raw_agreement"] is None
    assert result["cohen_kappa"] is None
    assert result["gwet_ac1"] is None
    assert any("zero overlapping" in n for n in result["notes"])


def test_false_fail_and_failure_recall():
    human = ["PASS", "PASS", "FAIL", "FAIL"]
    machine = ["FAIL", "PASS", "FAIL", "PASS"]
    result = rc.score_pairs(human, machine)
    assert result["confusion"] == {"both_pass": 1, "both_fail": 1,
                                   "human_pass_grader_fail": 1, "human_fail_grader_pass": 1}
    assert result["false_fail_rate"] == pytest.approx(0.5)
    assert result["failure_recall"] == pytest.approx(0.5)
    assert result["false_pass_rate"] == pytest.approx(0.5)
    assert result["raw_agreement"] == pytest.approx(0.5)


def test_undefined_rates_when_a_denominator_is_empty():
    result = rc.score_pairs(["PASS", "PASS"], ["PASS", "FAIL"])
    assert result["false_pass_rate"] is None
    assert result["failure_recall"] is None
    assert result["false_fail_rate"] == pytest.approx(0.5)


def test_wilson_interval_is_bounded_and_nonzero_at_zero():
    lo, hi = rc.wilson(0, 30)
    assert lo == 0.0
    assert 0.10 < hi < 0.12
    assert rc.wilson(0, 0) is None


def test_unknown_verdict_cannot_reach_score_pairs():
    with pytest.raises(rc.ReviewError):
        rc.score_pairs(["PASS", "UNSURE"], ["PASS", "FAIL"])


# --------------------------------------------------------------------------
# sealed labels (legacy CSV path)
# --------------------------------------------------------------------------

def _sealed_fixture(tmp_path, records, graded):
    res = tmp_path / "results"
    path = write_results(res, "SEALED-A0", records)
    return res, path


def test_sealed_labels_score_with_proper_grader(tmp_path):
    records = [multi_record("SD-01", 1, [LONG, LONG]), multi_record("SD-02", 1, [LONG, LONG])]
    graded = [{"id": "SD-01", "pass": True}, {"id": "SD-02", "pass": False}]
    res, path = _sealed_fixture(tmp_path, records, graded)
    labels = tmp_path / "labels.csv"
    labels.write_text("row,verdict,notes\nSD-01#1,PASS,\nSD-02#1,FAIL,good\n", encoding="utf-8")
    result = sealed_score._score_labels(
        labels, path, allow_partial=False, grader_read_dir=res,
        grader=lambda kind, arm, set_name=None: graded)
    assert result["arm"] == "SEALED-A0"
    assert result["grader_kind"] == "sealed"
    assert result["metrics"]["n"] == 2
    assert result["metrics"]["raw_agreement"] == pytest.approx(1.0)


def test_sealed_labels_reject_unknown_missing_duplicate_and_excluded(tmp_path):
    records = [multi_record("SD-01", 1, [LONG, LONG]),
               multi_record("SD-02", 1, ["Something went wrong loading this page"]),
               multi_record("SD-03", 1, [LONG, LONG])]
    graded = [{"id": "SD-01", "pass": True}, {"id": "SD-02", "pass": False},
              {"id": "SD-03", "pass": True}]
    res, path = _sealed_fixture(tmp_path, records, graded)
    labels = tmp_path / "labels.csv"

    labels.write_text("row,verdict\nSD-99#1,PASS\n", encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="not in"):
        sealed_score._score_labels(labels, path, allow_partial=True,
                                   grader_read_dir=res,
                                   grader=lambda kind, arm, set_name=None: graded)

    labels.write_text("row,verdict\nSD-01#1,PASS\n", encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="unlabelled"):
        sealed_score._score_labels(labels, path, allow_partial=False,
                                   grader_read_dir=res,
                                   grader=lambda kind, arm, set_name=None: graded)

    labels.write_text("row,verdict\nSD-01#1,PASS\nSD-01#1,FAIL\nSD-03#1,PASS\n", encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="twice"):
        sealed_score._score_labels(labels, path, allow_partial=True,
                                   grader_read_dir=res,
                                   grader=lambda kind, arm, set_name=None: graded)

    labels.write_text("row,verdict\nSD-01#1,PASS\nSD-02#1,PASS\nSD-03#1,PASS\n", encoding="utf-8")
    with pytest.raises(rc.LabelSheetError, match="excluded"):
        sealed_score._score_labels(labels, path, allow_partial=True,
                                   grader_read_dir=res,
                                   grader=lambda kind, arm, set_name=None: graded)


# --------------------------------------------------------------------------
# legacy blind sheet, explicit non-arm-blind mode
# --------------------------------------------------------------------------

def test_legacy_blind_sheet_scores_without_writing(tmp_path):
    legacy = tmp_path / "blind"
    legacy.mkdir()
    key = {"1": {"arm": "BIG-A0", "id": "G-X", "trial": 3, "my_verdict": "PASS"},
           "2": {"arm": "BIG-A2", "id": "G-Y", "trial": 1, "my_verdict": "FAIL"}}
    (legacy / "key.json").write_text(json.dumps(key), encoding="utf-8")
    sheet = ("row,scenario,arm,customer_says,business_rules,agent_reply,"
             "your_verdict_PASS_or_FAIL,notes\n"
             "1,G-X,BIG-A0,a,r,b,PASS,\n"
             "2,G-Y,BIG-A2,c,r,d,FAIL,\n")
    (legacy / "sheet.csv").write_text(sheet, encoding="utf-8")
    before = (legacy / "sheet.csv").read_text(encoding="utf-8")
    result = rc.score_legacy_blind(legacy)
    assert result["n_scored"] == 2
    assert result["arm_blind"] is False
    assert (legacy / "sheet.csv").read_text(encoding="utf-8") == before
    assert sorted(p.name for p in legacy.iterdir()) == ["key.json", "sheet.csv"]


# --------------------------------------------------------------------------
# CLI contract
# --------------------------------------------------------------------------

def test_help_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rc, "PRIVATE_LABELLING", tmp_path / "labelling")
    for module in (blind_export, blind_score, sealed_score):
        with pytest.raises(SystemExit) as excinfo:
            module.main(["--help"])
        assert excinfo.value.code == 0
    assert not (tmp_path / "labelling").exists()
    assert not list(tmp_path.iterdir())


def test_blind_score_cli_refuses_to_clobber(tmp_path):
    out, rows = _prepared_sheet(tmp_path)
    for row in rows:
        row["your_verdict"] = "PASS"
    write_sheet_rows(out / "sheet.csv", rows)
    dest = tmp_path / "score.json"
    dest.write_text("{}", encoding="utf-8")
    code = blind_score.main(["--sheet", str(out / "sheet.csv"),
                             "--key", str(out / "private" / "key.json"),
                             "--out", str(dest)])
    assert code == 2
    assert dest.read_text(encoding="utf-8") == "{}"
