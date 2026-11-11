"""Offline tests for the fillable review packet builder."""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pymupdf as fitz
import pytest

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("build_review_pdf", ROOT / "evals/build_review_pdf.py")
packet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packet)

COLUMNS = ["row_id", "conversation", "your_verdict", "recognized", "notes"]


def make_batch(root: Path, name: str, rows: int) -> Path:
    batch = root / name
    batch.mkdir(parents=True)
    with (batch / "sheet.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for i in range(1, rows + 1):
            writer.writerow({"row_id": f"R{i:04d}",
                             "conversation": f"CUSTOMER: question {i}\n\nAGENT: answer {i}.",
                             "your_verdict": "", "recognized": "", "notes": ""})
    return batch


def test_two_batches_get_distinct_prefixes_and_round_trip(tmp_path):
    sealed = make_batch(tmp_path / "b", "pre-run-sealed-v2", 2)
    dev = make_batch(tmp_path / "b", "pre-run-development-v2", 2)
    pdf = tmp_path / "packet.pdf"
    info = packet.build([sealed, dev], pdf, "test packet")
    assert info["rows"] == 4 and info["pages"] >= 1

    doc = fitz.open(pdf)
    names = [w.field_name for page in doc for w in (page.widgets() or [])]
    doc.close()
    assert "S-R0001_verdict" in names and "D-R0001_verdict" in names
    assert len(names) == 4 * 3, names

    filled = tmp_path / "filled.pdf"
    doc = fitz.open(pdf)
    for page in doc:
        for widget in page.widgets() or []:
            if widget.field_name == "S-R0001_verdict":
                widget.field_value = "fail"
                widget.update()
            if widget.field_name == "D-R0002_verdict":
                widget.field_value = "UNSURE"
                widget.update()
    doc.save(filled)
    doc.close()

    out = tmp_path / "out"
    result = packet.fill(filled, out, [sealed, dev])
    assert result["rows"] == 4 and result["blank_verdicts"] == 2

    scored = {}
    for path in result["files"]:
        with Path(path).open(encoding="utf-8", newline="") as fh:
            scored[Path(path).name] = {r["row_id"]: r for r in csv.DictReader(fh)}
    assert scored["pre-run-sealed-v2-filled.csv"]["R0001"]["your_verdict"] == "FAIL"
    assert scored["pre-run-development-v2-filled.csv"]["R0002"]["your_verdict"] == "UNSURE"
    # conversation text is restored from the batch, not from the PDF
    assert scored["pre-run-sealed-v2-filled.csv"]["R0001"]["conversation"].startswith("CUSTOMER: question 1")


def test_unknown_field_prefix_is_refused(tmp_path):
    batch = make_batch(tmp_path / "b", "pre-run-sealed-v2", 1)
    pdf = tmp_path / "packet.pdf"
    packet.build([batch], pdf, "test packet")
    extra = tmp_path / "extra.pdf"
    doc = fitz.open(pdf)
    page = doc[0]
    widget = fitz.Widget()
    widget.field_name = "Z-R0001_verdict"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(50, 50, 100, 60)
    page.add_widget(widget)
    doc.save(extra)
    doc.close()
    with pytest.raises(SystemExit):
        packet.fill(extra, tmp_path / "out", [batch])
