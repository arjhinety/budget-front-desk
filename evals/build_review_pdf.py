#!/usr/bin/env python3
"""Render a review batch as a fillable PDF, and read the filled fields back.

The PDF carries only what the labeller is allowed to see: the opaque row id and
the conversation. Arm, scenario, trial and machine verdict stay in the private
key. Fields are named `<row_id>_verdict`, `<row_id>_recognized` and
`<row_id>_notes`, so a returned PDF can be turned back into the sheet CSV.

  python evals/build_review_pdf.py \
      --batch ../agentplace-private/labelling/pre-run-sealed-v2 \
      --batch ../agentplace-private/labelling/pre-run-development-v2 \
      --out ../agentplace-private/labelling/review-packet.pdf

  python evals/build_review_pdf.py --fill ../agentplace-private/labelling/review-packet.pdf \
      --out ../agentplace-private/labelling/review-packet-filled.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pymupdf as fitz

PAGE_W, PAGE_H = fitz.paper_size("a4")
MARGIN = 42
GUTTER = 10
BODY = 8.2
LEAD = 10.2
VERDICTS = ("PASS", "FAIL", "UNSURE")


class Writer:
    def __init__(self, out: Path, title: str):
        self.doc = fitz.open()
        self.out = out
        self.title = title
        self.page = None
        self.y = 0.0
        self.page_no = 0
        self.font = fitz.Font("helv")
        self.bold = fitz.Font("hebo")

    # ---------------------------------------------------------------- layout
    def new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.page_no += 1
        self.page.insert_text((MARGIN, MARGIN - 12), self.title, fontname="hebo", fontsize=8)
        self.page.insert_text((PAGE_W - MARGIN - 60, MARGIN - 12), f"page {self.page_no}",
                              fontname="helv", fontsize=8)
        self.page.draw_line((MARGIN, MARGIN - 6), (PAGE_W - MARGIN, MARGIN - 6), width=0.6)
        self.y = MARGIN + 4

    def need(self, height: float) -> None:
        if self.page is None or self.y + height > PAGE_H - MARGIN:
            self.new_page()

    def wrap(self, text: str, width: float, font: fitz.Font, size: float) -> list[str]:
        lines: list[str] = []
        for raw in text.split("\n"):
            if not raw.strip():
                lines.append("")
                continue
            current = ""
            for word in raw.split(" "):
                trial = f"{current} {word}".strip()
                if font.text_length(trial, fontsize=size) <= width:
                    current = trial
                else:
                    if current:
                        lines.append(current)
                    while font.text_length(word, fontsize=size) > width and len(word) > 1:
                        cut = len(word)
                        while cut > 1 and font.text_length(word[:cut], fontsize=size) > width:
                            cut -= 1
                        lines.append(word[:cut])
                        word = word[cut:]
                    current = word
            lines.append(current)
        return lines

    # ---------------------------------------------------------------- blocks
    def section(self, label: str, note: str) -> None:
        self.need(60)
        self.page.insert_text((MARGIN, self.y + 12), label, fontname="hebo", fontsize=13)
        self.y += 18
        for line in self.wrap(note, PAGE_W - 2 * MARGIN, self.font, BODY + 0.8):
            self.page.insert_text((MARGIN, self.y + 8), line, fontname="helv", fontsize=BODY + 0.8)
            self.y += LEAD
        self.y += 6

    def row(self, row_id: str, conversation: str) -> None:
        width = PAGE_W - 2 * MARGIN
        lines = self.wrap(conversation, width - 16, self.font, BODY)
        # verdict line + notes field + padding
        height = 20 + len(lines) * LEAD + 46
        if height > PAGE_H - 2 * MARGIN:          # very long row: split across pages
            head, tail = lines[:28], lines[28:]
            self._row_block(row_id, head, last=False)
            while tail:
                chunk, tail = tail[:34], tail[34:]
                self._row_block(f"{row_id} (cont.)", chunk, last=not tail)
            return
        self._row_block(row_id, lines, last=True)

    def _row_block(self, row_id: str, lines: list[str], last: bool) -> None:
        width = PAGE_W - 2 * MARGIN
        height = 20 + len(lines) * LEAD + (46 if last else 12)
        self.need(height)
        top = self.y
        self.page.draw_rect(fitz.Rect(MARGIN, top, MARGIN + width, top + height),
                            color=(0.78, 0.82, 0.88), width=0.5)
        shown = row_id if last else row_id.replace(" (cont.)", "")
        self.page.insert_text((MARGIN + 8, top + 14), shown, fontname="hebo", fontsize=8.5)
        y = top + 26
        for line in lines:
            if line:
                self.page.insert_text((MARGIN + 8, y), line, fontname="helv", fontsize=BODY)
            y += LEAD
        if last:
            fy = top + height - 36
            self.page.insert_text((MARGIN + 8, fy + 10), "verdict:", fontname="helv", fontsize=7.5)
            self.field(f"{shown}_verdict", fitz.Rect(MARGIN + 48, fy, MARGIN + 48 + 88, fy + 16))
            self.page.insert_text((MARGIN + 148, fy + 10), "recognized:", fontname="helv", fontsize=7.5)
            self.field(f"{shown}_recognized", fitz.Rect(MARGIN + 214, fy, MARGIN + 214 + 56, fy + 16))
            self.page.insert_text((MARGIN + 8, fy + 28), "notes:", fontname="helv", fontsize=7.5)
            self.field(f"{shown}_notes", fitz.Rect(MARGIN + 48, fy + 17, MARGIN + width - 8, fy + 17 + 15))
            self.page.insert_text((MARGIN + 8, fy + 42),
                                  "PASS / FAIL / UNSURE  ·  recognized: yes / no",
                                  fontname="helv", fontsize=6.6, color=(0.4, 0.45, 0.52))
        self.y = top + height + GUTTER

    def field(self, name: str, rect: fitz.Rect) -> None:
        widget = fitz.Widget()
        widget.field_name = name
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.rect = rect
        widget.text_fontsize = 8
        widget.border_color = (0.55, 0.6, 0.68)
        widget.border_width = 0.5
        widget.fill_color = (0.97, 0.98, 0.99)
        self.page.add_widget(widget)

    def save(self) -> None:
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(self.out, garbage=3, deflate=True)
        self.doc.close()


def prefix_for(batch_name: str, taken: set[str]) -> str:
    """Short, stable per-packet prefix so two batches cannot share field names."""
    base = "S" if "sealed" in batch_name.lower() else "D" if "development" in batch_name.lower() else batch_name[:1].upper()
    prefix, n = base, 1
    while prefix in taken:
        n += 1
        prefix = f"{base}{n}"
    taken.add(prefix)
    return prefix


def load_batch(batch: Path) -> tuple[str, list[tuple[str, str]]]:
    sheet = batch / "sheet.csv"
    if not sheet.is_file():
        raise SystemExit(f"missing sheet: {sheet}")
    with sheet.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"{sheet} has no rows")
    fields = set(rows[0])
    if fields != {"row_id", "conversation", "your_verdict", "recognized", "notes"}:
        raise SystemExit(f"{sheet} has unexpected columns: {sorted(fields)}")
    return batch.name, [(r["row_id"], r["conversation"]) for r in rows]


def build(batches: list[Path], out: Path, title: str) -> dict:
    loaded = [load_batch(b) for b in batches]
    writer = Writer(out, title)
    writer.new_page()
    writer.page.insert_text((MARGIN, MARGIN + 10), "Review packet", fontname="hebo", fontsize=18)
    writer.y = MARGIN + 26
    intro = [
        "Fill the verdict box PASS, FAIL or UNSURE for every row, add a reason in notes, "
        "and mark recognized yes if you remember the reply.",
        "Judge the conversation against the frozen guide, not against remembered grader wording. "
        "A short but complete reply is valid; an empty or quota/render capture is not.",
        "Do not consult the private key until every row is filled. Row ids are opaque and one PDF "
        "may contain more than one batch; each batch is introduced below.",
        "Return the filled PDF, or type the verdicts back in chat. Either is fine; blanks are refused.",
    ]
    for item in intro:
        for line in writer.wrap(item, PAGE_W - 2 * MARGIN, writer.font, BODY + 0.6):
            writer.page.insert_text((MARGIN, writer.y), line, fontname="helv", fontsize=BODY + 0.6)
            writer.y += LEAD
        writer.y += 4
    total = 0
    taken: set[str] = set()
    plan = []
    for name, rows in loaded:
        prefix = prefix_for(name, taken)
        writer.section(f"{name}  ({prefix})",
                       f"{len(rows)} conversations. Write the verdict beside ids {prefix}-R0001 …")
        for row_id, conversation in rows:
            writer.row(f"{prefix}-{row_id}", conversation)
            total += 1
        plan.append({"batch": name, "rows": len(rows), "prefix": prefix})
    writer.save()
    return {"file": str(out), "rows": total, "pages": writer.page_no, "batches": plan}


def fill(pdf: Path, out_dir: Path, batches: list[Path]) -> dict:
    doc = fitz.open(pdf)
    values: dict[str, dict[str, str]] = {}
    for page in doc:
        for widget in page.widgets() or []:
            name = widget.field_name or ""
            if "_" not in name:
                continue
            row_id, kind = name.rsplit("_", 1)
            values.setdefault(row_id, {})[kind] = (widget.field_value or "").strip()
    doc.close()
    loaded = [load_batch(b) for b in batches]
    taken: set[str] = set()
    plan = [(prefix_for(name, taken), name, dict(rows)) for name, rows in loaded]
    by_prefix = {prefix: (name, mapping) for prefix, name, mapping in plan}

    grouped: dict[str, list[dict]] = {prefix: [] for prefix in by_prefix}
    unknown: list[str] = []
    for field_id, item in values.items():
        prefix, _, original = field_id.partition("-")
        if prefix not in by_prefix or original not in by_prefix[prefix][1]:
            unknown.append(field_id)
            continue
        grouped[prefix].append({"row_id": original,
                                "conversation": by_prefix[prefix][1][original],
                                "your_verdict": item.get("verdict", "").upper(),
                                "recognized": item.get("recognized", "").lower(),
                                "notes": item.get("notes", "")})
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    blanks = 0
    for prefix, (name, mapping) in by_prefix.items():
        rows = sorted(grouped[prefix], key=lambda r: r["row_id"])
        seen = {r["row_id"] for r in rows}
        if seen != set(mapping):
            raise SystemExit(f"{name}: packet is missing rows: {sorted(set(mapping) - seen)[:8]}")
        blanks += sum(not r["your_verdict"] for r in rows)
        target = out_dir / f"{name}-filled.csv"
        with target.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["row_id", "conversation", "your_verdict",
                                                    "recognized", "notes"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        written.append(str(target))
    if unknown:
        raise SystemExit(f"fields do not map to the supplied batches: {unknown[:8]}")
    return {"rows": sum(len(r) for r in grouped.values()), "blank_verdicts": blanks,
            "files": written}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", action="append", default=[], type=Path, help="batch directory (repeatable)")
    ap.add_argument("--out", type=Path, required=True,
                    help="PDF to build, or output directory when --fill is used")
    ap.add_argument("--title", default="Budget Front Desk — blind review")
    ap.add_argument("--fill", type=Path, metavar="PDF", help="extract filled fields to CSV instead of building")
    args = ap.parse_args()
    if args.out.exists():
        ap.error(f"refusing to overwrite {args.out}")
    if args.fill:
        if not args.batch:
            ap.error("--fill needs the same --batch arguments used to build the packet")
        result = fill(args.fill, args.out, args.batch)
    else:
        if not args.batch:
            ap.error("at least one --batch is required")
        result = build(args.batch, args.out, args.title)
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
