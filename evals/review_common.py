#!/usr/bin/env python3
"""Shared machinery for blind human review and human-vs-grader scoring.

Used by ``evals/blind_export.py``, ``evals/blind_score.py`` and
``evals/sealed_score.py``. Nothing in this module writes unless a caller asks it
to; importing it is inert and ``--help`` on any CLI leaves the filesystem alone.

Design rules that the rest of the code depends on:

* The public sheet never carries the arm, the scenario id, the trial, the source
  file or a grader verdict. All of that lives in a private key, keyed by an
  opaque row id.
* Identity is normalised as ``source-file / arm / id / trial`` in the private
  key only. Two arms may contain the same scenario at the same trial; they are
  different rows because the arm differs.
* Graders are invoked read-only and their output is bound to the records that
  actually produced it. A row count mismatch, a duplicate id or a missing id is
  a hard error rather than a guess.
* Cleaning removes definite capture chrome and the duplicated preview prefix.
  A greeting is content, not chrome, and a terse service reply is a valid reply.
* Scoring never fabricates agreement. Degenerate kappa or AC1 is reported as
  ``None`` with the reason attached.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
RESULTS = EVALS / "results"
DATASETS = ROOT / "datasets"
LEGACY_BLIND = EVALS / "blind"

# Labelling output lives outside the repository by default. Nothing here creates
# this directory at import time.
PRIVATE_LABELLING = ROOT.parent / "agentplace-private" / "labelling"

SHEET_COLUMNS = ["row_id", "conversation", "your_verdict", "recognized", "notes"]
KEY_FORMAT = "agentplace-blind-key/1"
MANIFEST_FORMAT = "agentplace-blind-manifest/1"
SCORE_FORMAT = "agentplace-blind-score/1"

VERDICTS = ("PASS", "FAIL", "UNSURE")
GRADER_TIMEOUT = 300

UI_NOISE = (
    r"^Home$",
    r"^Start over$",
    r"^Speak$",
    r"^Send$",
    r"^Attach files$",
    r"^Ask me anything$",
    r"^What.s going on at home\?$",
    r"^Budget Heating, Cooling & Plumbing mascot.*",
    r"^Turn \d+: .*",
    r"^This agent cannot continue right now.*",
    r"^Try again in about .*",
    r"^Retry$",
)

ARTEFACT_MARKERS = (
    "cannot continue right now",
    "something went wrong loading this page",
    "the answer could not be displayed",
)

class ReviewError(RuntimeError):
    """Base class for a refusal that the CLI turns into a clear message."""


class InputError(ReviewError):
    """The requested input cannot be read, or is not the file the grader used."""


class GraderError(ReviewError):
    """A grader failed, printed nothing usable, or disagreed with its input."""


class LabelSheetError(ReviewError):
    """A returned sheet is incomplete, altered, reordered into ambiguity, or fake."""


# --------------------------------------------------------------------------
# small utilities
# --------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def content_hash(path: Path) -> str:
    """Hash a JSON/text artifact the way export does, so line endings cannot drift.

    ``read_text`` applies universal-newline translation on both sides; a file
    copied between checkouts with CRLF still hashes to the same value.
    """
    return sha256_text(Path(path).read_text(encoding="utf-8"))


key_content_hash = content_hash


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(list(header))
        for row in rows:
            w.writerow(list(row))


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_atomic(path: Path, obj: Any) -> None:
    write_text_atomic(path, json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
                         "\u2014": "-", "\u2013": "-"})


def _match_norm(text: str) -> str:
    """Normalisation used only for comparison, never for output."""
    return _norm_ws((text or "").translate(_QUOTES)).lower()


# --------------------------------------------------------------------------
# cleaning
# --------------------------------------------------------------------------

def strip_customer(text: str, customer: str) -> str:
    """Remove the captured customer-message line, at most once.

    Only a whole line that is exactly the customer's message (after whitespace
    and quote normalisation) is removed. Nothing else is touched. That matters:
    an agent reply that greets ("Hi, Casey"), quotes ("Since my AC stopped
    cooling, ...") or restates the customer's words is substantive content, not
    a duplicate marker. An unanchored phrase match deleted "hi" inside "this"
    and stripped quoted phrases out of otherwise correct replies.
    """
    if not customer.strip():
        return text
    target = _match_norm(customer)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _match_norm(line) == target:
            del lines[i]
            break
    return "\n".join(lines)


def _is_chrome(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return any(re.match(p, s) for p in UI_NOISE)


def drop_preview_duplicates(text: str, min_head: int = 12) -> str:
    """Drop a collapsed preview line when the full message follows it.

    The capture writes a flattened, character-truncated preview of each message
    and then the full message. The preview is therefore a prefix of what follows.
    A greeting that is followed by different content does not match.
    """
    lines = text.split("\n")
    guard = 0
    while True:
        guard += 1
        if guard > len(lines) + 5:
            break
        dropped = False
        for i in range(len(lines) - 1):
            head = _match_norm(lines[i])
            if len(head) < min_head:
                continue
            head_cmp = head.rstrip("\u2026 ")
            if len(head_cmp) < min_head:
                continue
            rest = _match_norm("\n".join(lines[i + 1:]))
            if rest.startswith(head_cmp) and len(rest) > len(head_cmp):
                del lines[i]
                dropped = True
                break
        if not dropped:
            break
    return "\n".join(lines)


def _tidy(text: str) -> str:
    lines = [ln.rstrip() for ln in text.split("\n")]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def clean_text(text: str, customer: str = "") -> str:
    """Conservative cleaning of a captured single reply or thread."""
    text = strip_customer(text or "", customer)
    kept = [ln for ln in text.split("\n") if not _is_chrome(ln)]
    text = "\n".join(kept)
    text = drop_preview_duplicates(text)
    return _tidy(text)


def clean_reply(reply: str) -> str:
    """Clean one reply of a multi-turn capture.

    The reply is already the agent's message by itself, so no customer text is
    removed here. Stripping a short turn like "hi" from a reply would corrupt
    every "this" and "anything" in it.
    """
    return clean_text(reply, "")


# --------------------------------------------------------------------------
# record shapes
# --------------------------------------------------------------------------

def has_thread(rec: dict) -> bool:
    return "thread" in rec


def has_replies(rec: dict) -> bool:
    return isinstance(rec.get("replies"), list)


def _ids(records: Sequence[dict]) -> list[str]:
    return [str(r.get("id", "")) for r in records]


def infer_kind(stem: str, records: Sequence[dict]) -> str:
    if any(has_thread(r) for r in records):
        return "single"
    if any(has_replies(r) for r in records):
        upper = stem.upper()
        ids = _ids(records)
        if upper.startswith("SEALED") or (ids and all(i.startswith("SD-") for i in ids)):
            return "sealed"
        return "mt"
    raise InputError(f"{stem}: records carry neither 'thread' nor 'replies' — unknown schema")


def arm_from_path(path: Path) -> str:
    return Path(path).stem


SINGLE_SETS = ("scenarios", "scenarios-big")


def validate_conversation_coverage(kind: str, records: Sequence[dict]) -> None:
    """Refuse when a conversation arm has no rubric for one of its scripts.

    Both graders read ``.get(id, {})``, so a missing entry silently becomes an
    empty requirement list that passes everything. That must be an error.
    """
    if kind == "single":
        return
    ids = {str(r.get("id")) for r in records}
    if kind == "mt":
        scripts = json.loads((EVALS / "graders-mt.json").read_text(encoding="utf-8"))["scripts"]
        known = set(scripts)
        label = "graders-mt.json"
    else:
        scripts = json.loads((DATASETS / "sealed" / "graders-sealed.json")
                             .read_text(encoding="utf-8"))["scripts"]
        known = set(scripts)
        label = "datasets/sealed/graders-sealed.json"
    missing = sorted(ids - known)
    if missing:
        raise GraderError(
            f"{kind}: no rubric for {missing[:5]} in {label}; refusing to grade "
            "with empty requirements")


def infer_single_set(records: Sequence[dict], requested: str | None = None) -> str:
    """Choose the rubric set a single-turn capture was graded against.

    The arm name is not evidence: ``A5`` holds the generated ``scenarios-big``
    set while ``A0`` holds ``scenarios``. The split metadata and the id prefix
    are. An explicit override always wins.
    """
    if requested:
        return requested
    splits = {str(r.get("split")) for r in records if r.get("split")}
    ids = [str(r.get("id", "")) for r in records]
    if splits == {"big"} or (ids and all(i.startswith("G-") for i in ids)):
        return "scenarios-big"
    return "scenarios"


def validate_single_set(set_name: str, records: Sequence[dict]) -> dict:
    """Load a set and refuse if a record has no scenario entry or no rubric.

    ``grade.py`` treats a missing grader entry as ``{}`` — an empty requirement
    list that passes everything. That is the failure this check exists to stop.
    """
    scenario_path = EVALS / f"{set_name}.json"
    graders_path = EVALS / f"{set_name.replace('scenarios', 'graders')}.json"
    if not scenario_path.exists() or not graders_path.exists():
        raise InputError(f"scenario set {set_name!r} is not present in evals/")
    scenarios = json.loads(scenario_path.read_text(encoding="utf-8"))["scenarios"]
    graders = json.loads(graders_path.read_text(encoding="utf-8"))["scenarios"]
    known = {str(s["id"]) for s in scenarios}
    ids = [str(r.get("id", "")) for r in records]
    missing_scenario = sorted({i for i in ids if i not in known})
    missing_rubric = sorted({i for i in ids if i not in graders})
    if missing_scenario or missing_rubric:
        raise GraderError(
            f"{set_name}: "
            + (f"no scenario entry for {missing_scenario[:5]}; " if missing_scenario else "")
            + (f"no rubric for {missing_rubric[:5]} (grade.py would read empty "
               "requirements and pass them)" if missing_rubric else "")
            + " pass --set with the correct scenario set")
    return {"set": set_name, "scenarios": len(scenarios), "graders": len(graders)}


def replies_of(rec: dict) -> list[str]:
    reps = rec.get("replies")
    if isinstance(reps, list):
        return [str(x) if x is not None else "" for x in reps]
    if has_thread(rec):
        return [str(rec.get("thread") or "")]
    return []


def raw_text_of(rec: dict) -> str:
    if has_replies(rec):
        return "\n".join(replies_of(rec))
    return str(rec.get("thread") or "")


# --------------------------------------------------------------------------
# exclusions
# --------------------------------------------------------------------------

@dataclass
class Exclusion:
    identity: dict
    reason: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"identity": self.identity, "reason": self.reason, "detail": self.detail}


def find_artefact(text: str) -> str | None:
    low = (text or "").lower()
    for marker in ARTEFACT_MARKERS:
        if marker in low:
            return marker
    return None


def classify_record(rec: dict) -> tuple[str, str] | None:
    """Return (reason_code, detail) when the capture is unusable.

    Length is deliberately not a criterion. "No, closed Sunday." is a complete
    answer and "Call or text (636) 887-2800." is a complete answer; excluding
    either would be the tool inventing a failure.
    """
    if "error" in rec:
        return ("STORED_ERROR", str(rec.get("error"))[:300])
    artefact = find_artefact(raw_text_of(rec))
    if artefact:
        return ("ARTEFACT", f"transcript contains {artefact!r}")
    if not any(r.strip() for r in replies_of(rec)):
        return ("EMPTY_REPLIES", "no reply text captured")
    return None


# --------------------------------------------------------------------------
# grading adapters
# --------------------------------------------------------------------------

GRADER_SCRIPTS = {
    "single": EVALS / "grade.py",
    "mt": EVALS / "grade_mt.py",
    "sealed": DATASETS / "grade_sealed.py",
}


def grader_command(kind: str, arm: str, set_name: str | None = None) -> list[str]:
    script = GRADER_SCRIPTS.get(kind)
    if script is None:
        raise InputError(f"unknown grader kind {kind!r}")
    cmd = [sys.executable, str(script), "--arm", arm, "--json"]
    if kind == "single":
        if not set_name:
            raise InputError(
                "single-turn grading needs a scenario set; it is resolved from the "
                "records' split/id before the grader runs")
        cmd += ["--set", set_name]
    return cmd


def parse_json_array(stdout: str) -> list[dict]:
    text = (stdout or "").lstrip("\ufeff").strip()
    if not text:
        raise GraderError("grader printed nothing")
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "[":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            return obj
    raise GraderError(f"grader output is not a JSON array: {text[:200]!r}")


def run_grader(kind: str, arm: str, set_name: str | None = None, *,
               cwd: Path | None = None) -> list[dict]:
    cmd = grader_command(kind, arm, set_name)
    workdir = Path(cwd) if cwd else ROOT
    # A piped child on Windows otherwise writes its JSON in the locale encoding;
    # a single unpaired character in a reply would then fail the whole grade.
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=str(workdir), timeout=GRADER_TIMEOUT,
                              env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GraderError(f"could not run {' '.join(cmd)}: {exc}") from exc
    if proc.returncode != 0:
        tail = ((proc.stderr or proc.stdout or "").strip())[-600:]
        raise GraderError(
            f"grader {Path(cmd[1]).name} exited {proc.returncode} for {arm}: {tail}")
    rows = parse_json_array(proc.stdout)
    for row in rows:
        if not isinstance(row, dict) or "id" not in row or "pass" not in row:
            raise GraderError(
                f"grader {Path(cmd[1]).name} returned a row without id/pass: {row!r}")
    return rows


def canonical_results(arm: str, grader_read_dir: Path | None = None) -> Path:
    return (Path(grader_read_dir) if grader_read_dir else RESULTS) / f"{arm}.json"


def verify_results_input(path: Path, arm: str, grader_read_dir: Path | None = None) -> Path:
    """Check that the selected results file is the one the grader will read.

    The graders resolve ``evals/results/<arm>.json`` themselves from their own
    ``__file__``. ``grader_read_dir`` may only be supplied together with an
    injected grader that actually consumes that directory; the CLI never sets
    it, so a selected capture is always compared against the real grader input.
    A different copy is accepted only when its bytes are identical.
    """
    selected = Path(path).resolve()
    if not selected.exists():
        raise InputError(f"results file not found: {path}")
    canon = canonical_results(arm, grader_read_dir).resolve()
    if selected == canon:
        return selected
    if not canon.exists():
        raise InputError(
            f"selected --results {path} is not {canon}, and the grader reads only "
            f"{canon}; copy the capture there first (historical results are not "
            "rewritten by this tool)")
    if sha256_file(selected) != sha256_file(canon):
        raise InputError(
            f"selected --results {path} differs from {canon}, which is what the "
            "grader reads; refusing to score the wrong capture")
    return selected


def bind_graded(records: Sequence[dict], graded: Sequence[dict]) -> dict[tuple[str, int], dict]:
    """Bind grader rows to the records that produced them.

    ``grade_sealed.py`` returns no trial (its schema is
    ``{id, pass, fails, first_fail_turn}``), so a duplicate id inside one file
    cannot be resolved without guessing. That is an error, not a coin flip.
    """
    if len(graded) != len(records):
        raise GraderError(
            f"grader returned {len(graded)} rows for {len(records)} records; "
            "refusing to align them by position")
    with_trial = all("trial" in g for g in graded)
    by_key: dict[tuple[str, int], dict] = {}
    by_id: dict[str, list[dict]] = {}
    for g in graded:
        sid = str(g.get("id"))
        if with_trial:
            key = (sid, int(g["trial"]))
            if key in by_key:
                # A duplicated capture identity is excluded later; the grader's
                # two verdicts must nonetheless agree or the row is unassignable.
                if bool(by_key[key].get("pass")) != bool(g.get("pass")):
                    raise GraderError(
                        f"grader returned conflicting verdicts for {sid}#{key[1]}")
                continue
            by_key[key] = g
        else:
            by_id.setdefault(sid, []).append(g)

    if not with_trial:
        record_counts: dict[str, int] = {}
        for rec in records:
            record_counts[str(rec.get("id"))] = record_counts.get(str(rec.get("id")), 0) + 1
        for sid, rows in by_id.items():
            if len(rows) != record_counts.get(sid, 0):
                raise GraderError(
                    f"grader output for {sid} cannot be bound: {len(rows)} rows for "
                    f"{record_counts.get(sid, 0)} records")
            if len({bool(r.get("pass")) for r in rows}) > 1:
                raise GraderError(
                    f"grader output for {sid} cannot be bound: {len(rows)} rows disagree "
                    "and this grader reports no trial")
        extra_ids = set(by_id) - set(record_counts)
        if extra_ids:
            raise GraderError(f"grader returned rows with no matching record: {sorted(extra_ids)[:5]}")

    out: dict[tuple[str, int], dict] = {}
    used: set[tuple[str, int]] = set()
    for rec in records:
        sid = str(rec.get("id"))
        trial = int(rec.get("trial", 1))
        if with_trial:
            g = by_key.get((sid, trial))
            if g is None:
                raise GraderError(f"grader returned no row for {sid}#{trial}")
        else:
            g = by_id[sid][0]
        out[(sid, trial)] = {
            "pass": bool(g.get("pass")),
            "why": [str(x) for x in (g.get("why") or g.get("fails") or [])],
            "soft_missed": [str(x) for x in (g.get("soft_missed") or [])],
            "first_fail_turn": g.get("first_fail_turn"),
        }
        used.add((sid, trial))
    if with_trial:
        extra = sorted({str(g.get("id")) for g in graded} - {k[0] for k in used})
        if extra:
            raise GraderError(f"grader returned rows with no matching record: {extra[:5]}")
    return out


# --------------------------------------------------------------------------
# inputs -> candidates
# --------------------------------------------------------------------------

@dataclass
class InputSpec:
    path: Path
    kind: str | None = None

    @classmethod
    def parse(cls, value: str) -> "InputSpec":
        raw = value.strip()
        kind = None
        if "@" in raw:
            head, tail = raw.split("@", 1)
            if head in GRADER_SCRIPTS:
                kind, raw = head, tail
        return cls(path=Path(raw), kind=kind)


@dataclass
class Candidate:
    identity: dict
    source_file: str
    arm: str
    kind: str
    scenario: str
    trial: int
    conversation: str
    grader: dict
    capture: dict = field(default_factory=dict)


@dataclass
class Batch:
    candidates: list[Candidate]
    exclusions: list[Exclusion]
    unresolved: list[dict]
    inputs: list[dict]
    excluded_total: int = 0


def _load_results(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read results file {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise InputError(f"{path} has no 'records' list")
    if any(not isinstance(r, dict) for r in data["records"]):
        raise InputError(f"{path} has a non-object record; refusing to read it")
    return data


def render_conversation(rec: dict, kind: str) -> str:
    if kind == "single":
        customer = str(rec.get("customer") or "").strip()
        agent = clean_text(str(rec.get("thread") or ""), customer)
        parts = []
        if customer:
            parts.append(f"CUSTOMER: {customer}")
        parts.append(f"AGENT: {agent}")
        return "\n\n".join(parts)
    turns = [str(t) for t in (rec.get("turns") or [])]
    replies = replies_of(rec)
    parts = []
    for i, turn in enumerate(turns):
        parts.append(f"CUSTOMER: {turn.strip()}")
        if i < len(replies):
            reply = clean_reply(replies[i])
            if reply:
                parts.append(f"AGENT: {reply}")
    return "\n\n".join(parts)


def prepare_inputs(specs: Sequence[InputSpec], *,
                   set_name: str | None = None,
                   grader_read_dir: Path | None = None,
                   grader: Callable[..., list[dict]] | None = None) -> Batch:
    real_graders = grader is None
    if grader_read_dir is not None and real_graders:
        raise InputError(
            "the graders resolve evals/results/<arm>.json from their own file; "
            "an alternate grader_read_dir is only valid with an injected grader")
    grader = grader or run_grader
    candidates: list[Candidate] = []
    exclusions: list[Exclusion] = []
    unresolved: list[dict] = []
    inputs_meta: list[dict] = []
    # Identity for de-duplication is arm/id/trial, not the path: the same capture
    # copied to another filename is still the same conversation.
    seen: dict[tuple[str, str, int], dict] = {}

    for spec in specs:
        path = Path(spec.path)
        data = _load_results(path)
        records = data["records"]
        arm = arm_from_path(path)
        kind = spec.kind or infer_kind(arm, records)
        chosen_set = None
        if kind == "single":
            chosen_set = infer_single_set(records, set_name)
            if real_graders:
                validate_single_set(chosen_set, records)
        elif real_graders:
            validate_conversation_coverage(kind, records)
        verified = verify_results_input(path, arm, grader_read_dir)
        digest = sha256_file(verified)
        graded = grader(kind, arm, chosen_set)
        bound = bind_graded(records, graded)
        capture_blob = {k: v for k, v in data.items() if k != "records"}
        inputs_meta.append({
            "arm": arm,
            "kind": kind,
            "selected_file": str(path),
            "grader_file": str(verified),
            "sha256": digest,
            "records": len(records),
            "grader": Path(GRADER_SCRIPTS[kind]).name,
            "set": chosen_set,
            "capture": capture_blob,
            "observed_url": data.get("url"),
            # The platform's effective hidden configuration is not exported by
            # this tool. Only what the capture itself recorded is retained.
            "platform_config_exported": False,
        })
        source_file = _rel(path)

        for rec in records:
            sid = str(rec.get("id"))
            trial = int(rec.get("trial", 1))
            identity = {"source_file": source_file, "arm": arm, "id": sid, "trial": trial}
            dedupe_key = (arm, sid, trial)
            if dedupe_key in seen:
                exclusions.append(Exclusion(identity, "DUPLICATE_IDENTITY",
                                            "same source-file/arm/id/trial already present"))
                continue
            seen[dedupe_key] = identity
            reason = classify_record(rec)
            if reason:
                exclusions.append(Exclusion(identity, reason[0], reason[1]))
                continue
            if kind != "single":
                turns = rec.get("turns") or []
                replies = rec.get("replies") or []
                if len(turns) != len(replies):
                    unresolved.append({
                        "identity": identity,
                        "reason": "TURN_REPLY_MISMATCH",
                        "detail": f"{len(replies)} replies for {len(turns)} turns",
                    })
                    continue
                empty_turns = [i + 1 for i, rep in enumerate(replies) if not str(rep).strip()]
                if empty_turns:
                    # A non-empty neighbour does not rescue a missing turn: the
                    # labeller would be reading a conversation the customer never had.
                    exclusions.append(Exclusion(
                        identity, "EMPTY_REPLY",
                        f"empty reply for turn(s) {empty_turns}"))
                    continue
            conversation = render_conversation(rec, kind)
            if not _norm_ws(conversation).replace("CUSTOMER:", "").replace("AGENT:", "").strip():
                unresolved.append({"identity": identity, "reason": "EMPTY_CONVERSATION",
                                   "detail": "nothing left after cleaning"})
                continue
            capture = {k: rec.get(k) for k in ("at", "chars", "ms", "agent", "family", "split", "lane")
                       if k in rec}
            candidates.append(Candidate(
                identity=identity, source_file=source_file, arm=arm, kind=kind,
                scenario=sid, trial=trial, conversation=conversation,
                grader=bound[(sid, trial)], capture=capture))

    return Batch(candidates, exclusions, unresolved, inputs_meta, len(exclusions))


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def stratum_of(cand: Candidate) -> str:
    if cand.grader.get("soft_missed"):
        return "edge"
    return "pass" if cand.grader.get("pass") else "fail"


def select(candidates: Sequence[Candidate], *, n: int | None, take_all: bool,
           seed: int, strata: Sequence[str] = ("pass", "fail", "edge")) -> tuple[list[Candidate], dict]:
    pool = list(candidates)
    rng = random.Random(seed)
    available = {k: [c for c in pool if stratum_of(c) == k] for k in strata}
    for v in available.values():
        rng.shuffle(v)

    if take_all:
        picked = list(pool)
        rng.shuffle(picked)
        report = {
            "mode": "all",
            "seed": seed,
            "pool": len(pool),
            "selected": len(picked),
            "strata_pool": {k: len(v) for k, v in available.items()},
            "strata_selected": {k: sum(1 for c in picked if stratum_of(c) == k) for k in strata},
            "selection_bias": None,
        }
        return picked, report

    target = n if n and n > 0 else 30
    per = max(1, target // len(strata)) if pool else 0
    picked: list[Candidate] = []
    for k in strata:
        picked.extend(available[k][:per])
    if len(picked) < min(target, len(pool)):
        taken = {id(c) for c in picked}
        for k in strata:
            for c in available[k]:
                if len(picked) >= min(target, len(pool)):
                    break
                if id(c) not in taken:
                    picked.append(c)
                    taken.add(id(c))
    rng.shuffle(picked)
    report = {
        "mode": "stratified",
        "seed": seed,
        "pool": len(pool),
        "selected": len(picked),
        "target": target,
        "strata_pool": {k: len(v) for k, v in available.items()},
        "strata_selected": {k: sum(1 for c in picked if stratum_of(c) == k) for k in strata},
        "selection_bias": (
            "Deliberately stratified, not a uniform sample: pass and fail rows are "
            "over-sampled roughly evenly, so the agreement estimate describes this "
            "sample and not the arm's base rate. Recompute on the full eligible "
            "pool (--all) before quoting a population pass rate."
            if any(len(v) for v in available.values()) else None
        ),
    }
    return picked, report


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------

def private_default_out(arms: Sequence[str], kinds: Sequence[str],
                        base: Path | None = None) -> Path:
    base = Path(base) if base else PRIVATE_LABELLING
    slug = "-".join(sorted({*(a.lower() for a in arms), *(k for k in kinds)}))[:60] or "batch"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return base / f"{stamp}-{slug}"


def ensure_writable_out(out: Path) -> Path:
    out = Path(out).resolve()
    legacy = LEGACY_BLIND.resolve()
    if out == legacy or legacy in out.parents:
        raise ReviewError(
            f"{out} is the historical evals/blind directory; those artifacts are "
            "preserved byte-for-byte. Choose a new --out path.")
    if out.exists() and not out.is_dir():
        raise ReviewError(f"{out} exists and is not a directory")
    if out.exists() and any(out.iterdir()):
        raise ReviewError(
            f"{out} already contains files; refusing to overwrite. Choose a fresh "
            "--out path (or an empty directory).")
    return out


def export_batch(specs: Sequence[InputSpec], out: Path, *,
                 guide: Path,
                 n: int | None = None, take_all: bool = False,
                 seed: int = 20261111,
                 set_name: str | None = None,
                 grader_read_dir: Path | None = None,
                 grader: Callable[..., list[dict]] | None = None,
                 strata: Sequence[str] = ("pass", "fail", "edge")) -> dict:
    strata = tuple(strata) or ("pass", "fail", "edge")
    if guide is None:
        raise ReviewError(
            "a guide is required for a modern labelling batch: its hash is frozen "
            "in the private key so labels cannot be collected without the rules")
    out = ensure_writable_out(out)
    batch = prepare_inputs(specs, set_name=set_name, grader_read_dir=grader_read_dir,
                           grader=grader)
    if not batch.candidates:
        raise ReviewError("no eligible conversations after exclusions; nothing exported")
    picked, selection = select(batch.candidates, n=n, take_all=take_all, seed=seed, strata=strata)

    guide_path = Path(guide)
    if not guide_path.exists():
        raise InputError(f"guide not found: {guide}")
    guide_meta = {"source": str(guide_path), "sha256": sha256_file(guide_path),
                  "copied_to": "GUIDE.md"}

    out.mkdir(parents=True, exist_ok=True)
    sheet_rows = []
    key_rows: dict[str, dict] = {}
    for idx, cand in enumerate(picked, 1):
        row_id = f"R{idx:04d}"
        text = cand.conversation
        sheet_rows.append([row_id, text, "", "", ""])
        key_rows[row_id] = {
            "source_file": cand.identity["source_file"],
            "arm": cand.arm,
            "id": cand.scenario,
            "trial": cand.trial,
            "grader": cand.kind,
            "grader_verdict": "PASS" if cand.grader.get("pass") else "FAIL",
            "grader_why": cand.grader.get("why") or [],
            "conversation_sha256": sha256_text(text),
            "sheet_row": idx,
            "capture": cand.capture,
        }

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(SHEET_COLUMNS)
    for row in sheet_rows:
        w.writerow(row)
    sheet_text = buf.getvalue()
    write_text_atomic(out / "sheet.csv", sheet_text)

    (out / "GUIDE.md").write_bytes(guide_path.read_bytes())

    key = {
        "format": KEY_FORMAT,
        "batch": out.name,
        "created_at": utc_now(),
        "seed": seed,
        "sheet_sha256": sha256_text(sheet_text),
        "guide": guide_meta,
        "rows": key_rows,
    }
    write_json_atomic(out / "private" / "key.json", key)

    manifest = {
        "format": MANIFEST_FORMAT,
        "batch": out.name,
        "created_at": key["created_at"],
        "tool": {"blind_export": "evals/blind_export.py",
                 "review_common": _rel(Path(__file__))},
        "seed": seed,
        "sheet_columns": SHEET_COLUMNS,
        "guide": guide_meta,
        "inputs": batch.inputs,
        "selection": selection,
        "counts": {
            "candidates": len(batch.candidates),
            "selected": len(picked),
            "excluded": len(batch.exclusions),
            "unresolved": len(batch.unresolved),
        },
        "exclusions": [e.as_dict() for e in batch.exclusions],
        "unresolved": batch.unresolved,
        "sheet_sha256": key["sheet_sha256"],
        "key_sha256": key_content_hash(out / "private" / "key.json"),
    }
    write_json_atomic(out / "private" / "manifest.json", manifest)
    return {
        "out": str(out),
        "sheet": str(out / "sheet.csv"),
        "key": str(out / "private" / "key.json"),
        "manifest": str(out / "private" / "manifest.json"),
        "selected": len(picked),
        "candidates": len(batch.candidates),
        "exclusions": [e.as_dict() for e in batch.exclusions],
        "unresolved": batch.unresolved,
        "selection": selection,
        "guide": guide_meta,
    }


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------

def wilson(successes: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n <= 0:
        return None
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


def _rate(k: int, n: int) -> tuple[float | None, list[float] | None]:
    if n <= 0:
        return None, None
    return k / n, wilson(k, n)


def cohen_kappa(human: Sequence[str], machine: Sequence[str]) -> tuple[float | None, str | None]:
    n = len(human)
    if n == 0:
        return None, "no scored pairs"
    po = sum(1 for h, m in zip(human, machine) if h == m) / n
    ph = human.count("PASS") / n
    pm = machine.count("PASS") / n
    pe = ph * pm + (1 - ph) * (1 - pm)
    if abs(1.0 - pe) < 1e-12:
        return None, ("degenerate: expected chance agreement is 1.0 because at least "
                      "one rater used a single category on every pair")
    return (po - pe) / (1.0 - pe), None


def gwet_ac1(human: Sequence[str], machine: Sequence[str]) -> tuple[float | None, str | None]:
    """Binary Gwet AC1. Expected agreement is 2*p*(1-p) with p the pooled pass rate."""
    n = len(human)
    if n == 0:
        return None, "no scored pairs"
    po = sum(1 for h, m in zip(human, machine) if h == m) / n
    p = (human.count("PASS") + machine.count("PASS")) / (2 * n)
    # Binary AC1: the expected term is 2*p*(1-p), which peaks at 0.5 and never
    # reaches 1, so AC1 stays defined where kappa collapses to 0/0.
    pe = 2 * p * (1 - p)
    return (po - pe) / (1.0 - pe), None


def score_pairs(human: Sequence[str], machine: Sequence[str]) -> dict:
    """Score aligned PASS/FAIL sequences. UNSURE must be filtered by the caller."""
    pairs = [(h, m) for h, m in zip(human, machine) if h in ("PASS", "FAIL") and m in ("PASS", "FAIL")]
    if len(pairs) != len(human) or len(pairs) != len(machine):
        raise ReviewError("score_pairs received an UNSURE or unknown verdict; filter first")
    n = len(pairs)
    tp = sum(1 for h, m in pairs if h == "PASS" and m == "PASS")
    tn = sum(1 for h, m in pairs if h == "FAIL" and m == "FAIL")
    fn = sum(1 for h, m in pairs if h == "PASS" and m == "FAIL")
    fp = sum(1 for h, m in pairs if h == "FAIL" and m == "PASS")
    assert tp + tn + fn + fp == n

    agreement = (tp + tn) / n if n else None
    kappa, kappa_reason = cohen_kappa([p[0] for p in pairs], [p[1] for p in pairs])
    ac1, ac1_reason = gwet_ac1([p[0] for p in pairs], [p[1] for p in pairs])

    human_pass = tp + fn
    human_fail = tn + fp
    ff_rate, ff_ci = _rate(fn, human_pass)
    fp_rate, fp_ci = _rate(fp, human_fail)
    recall, recall_ci = _rate(tn, human_fail)
    specificity, spec_ci = _rate(tp, human_pass)

    return {
        "n": n,
        "confusion": {"both_pass": tp, "both_fail": tn,
                      "human_pass_grader_fail": fn, "human_fail_grader_pass": fp},
        "human_pass": human_pass,
        "human_fail": human_fail,
        "grader_pass": tp + fp,
        "grader_fail": tn + fn,
        "raw_agreement": agreement,
        "raw_agreement_wilson": wilson(tp + tn, n) if n else None,
        "cohen_kappa": kappa,
        "cohen_kappa_reason": kappa_reason,
        "gwet_ac1": ac1,
        "gwet_ac1_reason": ac1_reason,
        "false_fail_rate": ff_rate,
        "false_fail_rate_wilson": ff_ci,
        "false_pass_rate": fp_rate,
        "false_pass_rate_wilson": fp_ci,
        "failure_recall": recall,
        "failure_recall_wilson": recall_ci,
        "pass_specificity": specificity,
        "pass_specificity_wilson": spec_ci,
        "notes": _score_notes(n, kappa_reason, ac1_reason),
    }


def _score_notes(n: int, kappa_reason: str | None, ac1_reason: str | None) -> list[str]:
    notes = []
    if n == 0:
        notes.append("zero overlapping labels: no agreement, kappa or AC1 is defined; "
                     "none is reported rather than 1.0")
        return notes
    if kappa_reason:
        notes.append(f"kappa undefined: {kappa_reason}")
    if ac1_reason:
        notes.append(f"AC1 undefined: {ac1_reason}")
    if n < 30:
        notes.append(f"n={n}: Wilson intervals here are wide; a 0/N rate is not evidence "
                     "that the event never occurs")
    return notes


def summarize(*, pairs: Sequence[tuple[str, str, dict]], unsure: int,
              recognized: dict, exclusions: Sequence[dict], unresolved: Sequence[dict],
              selection: dict | None = None, extra: dict | None = None,
              unsure_detail: Sequence[dict] = ()) -> dict:
    human = [p[0] for p in pairs]
    machine = [p[1] for p in pairs]
    metrics = score_pairs(human, machine)
    result = {
        "format": SCORE_FORMAT,
        "created_at": utc_now(),
        "n_total": len(pairs) + unsure,
        "n_scored": len(pairs),
        "n_unsure": unsure,
        "unsure_detail": list(unsure_detail),
        "recognized": recognized,
        "metrics": metrics,
        "selection": selection,
        "excluded": len(exclusions),
        "unresolved": len(unresolved),
        "detail": [p[2] for p in pairs],
        "exclusions": list(exclusions),
        "unresolved_items": list(unresolved),
    }
    if extra:
        result.update(extra)
    return result


def format_report(result: dict) -> str:
    m = result["metrics"]
    lines = [
        f"rows {result['n_total']}   scored {m['n']}   unsure {result['n_unsure']}"
        f"   excluded {result['excluded']}   unresolved {result['unresolved']}",
        f"  confusion (human x grader): both PASS {m['confusion']['both_pass']}, "
        f"both FAIL {m['confusion']['both_fail']}, "
        f"human PASS/grader FAIL {m['confusion']['human_pass_grader_fail']}, "
        f"human FAIL/grader PASS {m['confusion']['human_fail_grader_pass']}",
    ]

    def fmt(value, ci=None):
        if value is None:
            return "undefined"
        text = f"{value:.3f}"
        if ci:
            text += f"  [{ci[0]:.3f}, {ci[1]:.3f}]"
        return text

    lines += [
        f"  raw agreement   {fmt(m['raw_agreement'], m['raw_agreement_wilson'])}",
        f"  Cohen kappa     {fmt(m['cohen_kappa'])}",
        f"  Gwet AC1        {fmt(m['gwet_ac1'])}",
        f"  false-fail      {fmt(m['false_fail_rate'], m['false_fail_rate_wilson'])}"
        f"   ({m['human_pass']} human-PASS rows)",
        f"  false-pass      {fmt(m['false_pass_rate'], m['false_pass_rate_wilson'])}"
        f"   ({m['human_fail']} human-FAIL rows)",
        f"  failure recall  {fmt(m['failure_recall'], m['failure_recall_wilson'])}",
    ]
    recognized = result.get("recognized") or {}
    if recognized:
        shown = ", ".join(f"{k} {v}" for k, v in recognized.items())
        lines.append(f"  recognized/unresolved: {shown}")
    for note in m["notes"]:
        lines.append(f"  note: {note}")
    unsure_rows = result.get("unsure_detail") or []
    if unsure_rows:
        labels = [str(d.get("row_id") or d.get("row")) for d in unsure_rows]
        lines.append(f"  unsure: {len(labels)} row(s) " + ", ".join(labels[:20]))
    disagreements = [d for d in (result.get("detail") or [])
                     if d.get("human_verdict") != d.get("grader_verdict")]
    if disagreements:
        labels = [str(d.get("row_id") or d.get("row")) for d in disagreements]
        lines.append(f"  disagreements: {len(labels)} row(s) "
                     + ", ".join(labels[:20]) + (" ..." if len(labels) > 20 else ""))
    sel = result.get("selection") or {}
    if sel.get("selection_bias"):
        lines.append(f"  selection: {sel['selection_bias']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# returned-sheet validation and scoring
# --------------------------------------------------------------------------

def read_sheet(path: Path) -> list[dict]:
    try:
        with Path(path).open("r", newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            rows = list(reader)
    except OSError as exc:
        raise LabelSheetError(f"cannot read sheet {path}: {exc}") from exc
    if header != SHEET_COLUMNS:
        raise LabelSheetError(
            f"sheet header is {header!r}; expected {SHEET_COLUMNS!r}. "
            "Do not rename, reorder or delete columns.")
    return rows


def load_key(path: Path) -> dict:
    try:
        key = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LabelSheetError(f"cannot read key {path}: {exc}") from exc
    if key.get("format") != KEY_FORMAT or not isinstance(key.get("rows"), dict):
        raise LabelSheetError(f"{path} is not a {KEY_FORMAT} key")
    return key


def _normalise_verdict(raw: str, row_id: str) -> str:
    value = (raw or "").strip().upper()
    if value == "":
        raise LabelSheetError(f"{row_id}: blank verdict. A blank is not a no; use PASS, FAIL or UNSURE.")
    if value not in VERDICTS:
        raise LabelSheetError(f"{row_id}: verdict {raw!r} is not PASS, FAIL or UNSURE")
    return value


def _normalise_recognized(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in ("y", "yes", "true", "1"):
        return "yes"
    if value in ("n", "no", "false", "0"):
        return "no"
    if value == "":
        return "blank"
    if value in ("unknown", "unsure", "maybe"):
        return "unknown"
    return "other"


def join_sheet(rows: Sequence[dict], key: dict, *, guide: Path | None = None) -> tuple[list[tuple[str, str, dict]], int, dict]:
    """Validate a returned sheet against the frozen private key.

    Rows may come back in any order: the join is by ``row_id``, never by
    position. Everything that would mispair a verdict is rejected: an unknown
    id, a duplicate id, a missing row, an altered conversation cell, a blank or
    invented verdict.
    """
    key_rows: dict[str, dict] = key["rows"]
    errors: list[str] = []
    seen: set[str] = set()
    out_of_order = False
    expected_order = list(key_rows.keys())
    actual_order = []
    pairs: list[tuple[str, str, dict]] = []
    unsure = 0
    unsure_detail: list[dict] = []
    recognized = {"yes": 0, "no": 0, "blank": 0, "unknown": 0, "other": 0}

    if guide is not None:
        expected = (key.get("guide") or {}).get("sha256")
        if not Path(guide).exists():
            errors.append(f"guide not found: {guide}")
        elif expected is None:
            errors.append("key records no guide hash, but a guide was supplied")
        elif sha256_file(Path(guide)) != expected:
            errors.append("guide hash does not match the key: the guide was edited after export")

    for row in rows:
        row_id = (row.get("row_id") or "").strip()
        actual_order.append(row_id)
        if row_id in seen:
            errors.append(f"{row_id}: duplicate row id in the returned sheet")
            continue
        seen.add(row_id)
        if row_id not in key_rows:
            errors.append(f"{row_id}: row id is not in the private key (injected or renamed row)")
            continue
        entry = key_rows[row_id]
        conversation = row.get("conversation") or ""
        if sha256_text(conversation) != entry.get("conversation_sha256"):
            errors.append(f"{row_id}: conversation cell was altered after export")
            continue
        try:
            verdict = _normalise_verdict(row.get("your_verdict", ""), row_id)
        except LabelSheetError as exc:
            errors.append(str(exc))
            continue
        recognized[_normalise_recognized(row.get("recognized", ""))] += 1
        detail = {
            "row_id": row_id,
            "arm": entry.get("arm"),
            "source_file": entry.get("source_file"),
            "id": entry.get("id"),
            "trial": entry.get("trial"),
            "grader_verdict": entry.get("grader_verdict"),
            "human_verdict": verdict,
            "notes": row.get("notes", "") or "",
            "recognized": row.get("recognized", "") or "",
        }
        if verdict == "UNSURE":
            unsure += 1
            unsure_detail.append(detail)
        else:
            pairs.append((verdict, entry["grader_verdict"], detail))

    missing = [rid for rid in key_rows if rid not in seen]
    if missing:
        errors.append(f"{len(missing)} row(s) missing from the returned sheet: {missing[:10]}")
    if [r for r in actual_order if r in key_rows] != expected_order:
        out_of_order = True
    if errors:
        raise LabelSheetError("sheet rejected:\n  " + "\n  ".join(errors[:20]))

    return pairs, unsure, {"recognized": recognized, "returned_out_of_order": out_of_order,
                           "unsure_detail": unsure_detail}


def _validate_manifest(manifest: dict, key: dict, key_path: Path) -> None:
    """Refuse a modern batch whose private manifest is missing, corrupt or incoherent.

    The manifest is the only record of what the key is supposed to contain. If it
    is absent or cannot be matched to the key, the labelled rows cannot be
    paired with a trustworthy verdict, so scoring stops instead of skipping the
    source checks.
    """
    problems: list[str] = []
    if not isinstance(manifest, dict):
        raise LabelSheetError("private manifest is not a JSON object")
    if manifest.get("format") != MANIFEST_FORMAT:
        problems.append(f"manifest format is {manifest.get('format')!r}, "
                        f"expected {MANIFEST_FORMAT!r}")
    if manifest.get("batch") != key.get("batch"):
        problems.append(f"manifest batch {manifest.get('batch')!r} does not match "
                        f"key batch {key.get('batch')!r}")
    if manifest.get("sheet_sha256") != key.get("sheet_sha256"):
        problems.append("manifest sheet_sha256 does not match the key")
    if manifest.get("sheet_columns") != list(SHEET_COLUMNS):
        problems.append("manifest sheet_columns do not match this scorer's schema")
    manifest_guide = (manifest.get("guide") or {}).get("sha256")
    key_guide = (key.get("guide") or {}).get("sha256")
    if manifest_guide != key_guide:
        problems.append("manifest guide hash does not match the key")
    expected = manifest.get("key_sha256")
    if not expected:
        problems.append("manifest records no key_sha256")
    elif expected != key_content_hash(key_path):
        problems.append("key content hash does not match manifest.key_sha256 "
                        "(the key was edited after export)")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        problems.append("manifest has no source receipts")
    else:
        for i, item in enumerate(inputs):
            if not isinstance(item, dict):
                problems.append(f"source receipt {i} is not an object")
                continue
            if not str(item.get("selected_file") or "").strip():
                problems.append(f"source receipt {i} has no selected_file")
            digest = str(item.get("sha256") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                problems.append(f"source receipt {i} has no valid sha256")
            if not isinstance(item.get("records"), int) or item["records"] < 0:
                problems.append(f"source receipt {i} has no record count")

    rows = key.get("rows") if isinstance(key.get("rows"), dict) else {}
    counts = manifest.get("counts")
    if not isinstance(counts, dict) or counts.get("selected") != len(rows):
        problems.append("manifest counts.selected does not match the key's row count")
    order = [r.get("sheet_row") for r in rows.values()]
    if order != list(range(1, len(rows) + 1)):
        problems.append("key rows are not numbered 1..N in export order")

    if problems:
        raise LabelSheetError("private manifest rejected:\n  " + "\n  ".join(problems))


def _recorded_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path)


def _validate_sources(manifest: dict) -> None:
    """Refuse to score labels against a capture that changed after the export."""
    problems = []
    for item in manifest.get("inputs") or []:
        recorded = item.get("selected_file")
        digest = item.get("sha256")
        if not recorded or not digest:
            continue
        path = _recorded_path(recorded)
        if not path.exists():
            problems.append(f"{recorded} is no longer present, so its hash cannot be checked")
        elif sha256_file(path) != digest:
            problems.append(f"{recorded} changed after the export (sha256 mismatch)")
    if problems:
        raise LabelSheetError(
            "source captures no longer match the export:\n  " + "\n  ".join(problems))


def score_sheet(sheet: Path, key_path: Path, *, guide: Path | None = None) -> dict:
    key = load_key(key_path)
    if not (key.get("guide") or {}).get("sha256"):
        raise LabelSheetError(
            "this batch records no guide hash; modern labels cannot be scored "
            "without the frozen rules. Re-export with --guide.")
    batch_dir = Path(key_path).parent.parent
    if guide is None:
        copied = batch_dir / "GUIDE.md"
        if not copied.exists():
            raise LabelSheetError(
                "the batch has a frozen guide hash but no GUIDE.md to verify; "
                "pass --guide with the original file")
        guide = copied
    rows = read_sheet(sheet)
    manifest_path = Path(key_path).parent / "manifest.json"
    if not manifest_path.exists():
        raise LabelSheetError(
            f"no private manifest at {manifest_path}; a modern batch cannot be "
            "scored without it (re-export rather than reconstructing the key)")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LabelSheetError(f"private manifest is not valid JSON: {exc}") from exc
    _validate_manifest(manifest, key, Path(key_path))
    _validate_sources(manifest)
    selection = manifest.get("selection")
    exclusions = manifest.get("exclusions") or []
    unresolved = manifest.get("unresolved") or []
    pairs, unsure, meta = join_sheet(rows, key, guide=guide)

    # join_sheet refuses missing, blank, duplicated, injected or altered rows, so
    # reaching this point means every exported row carries a valid verdict. The
    # receipt is explicit rather than implied by the absence of an error.
    labelled = len(pairs) + unsure
    if labelled != len(key["rows"]):
        raise LabelSheetError(
            f"label completeness check failed: {labelled} labelled rows for "
            f"{len(key['rows'])} exported rows")
    result = summarize(pairs=pairs, unsure=unsure, recognized=meta["recognized"],
                       exclusions=exclusions, unresolved=unresolved, selection=selection,
                       unsure_detail=meta["unsure_detail"],
                       extra={
                           "batch": key.get("batch"),
                           "labels_complete": True,
                           "guide_sha256": (key.get("guide") or {}).get("sha256"),
                           "source_manifest_sha256": content_hash(manifest_path),
                           "row_counts": {
                               "expected": len(key["rows"]),
                               "scored": len(pairs),
                               "unsure": unsure,
                               "blank": 0,
                               "missing": 0,
                               "invalid": 0,
                           },
                           "key_sha256": content_hash(key_path),
                           # The frozen export digest (the blank sheet the
                           # labeller received) and the digest of what came back
                           # are different objects; keep both explicit.
                           "sheet_sha256": key.get("sheet_sha256"),
                           "returned_sheet_sha256": content_hash(sheet),
                           "returned_out_of_order": meta["returned_out_of_order"],
                       })
    return result


# --------------------------------------------------------------------------
# legacy paths (explicitly not arm-blind)
# --------------------------------------------------------------------------

LEGACY_COLUMNS = ["row", "scenario", "arm", "customer_says", "business_rules",
                  "agent_reply", "your_verdict_PASS_or_FAIL", "notes"]
LEGACY_VERDICT_COL = "your_verdict_PASS_or_FAIL"


def score_legacy_blind(directory: Path) -> dict:
    """Score the historical evals/blind sheet.

    This path is NOT arm-blind and NOT anonymous: the legacy sheet shows the
    scenario id and the arm to the labeller. It exists only to reproduce the
    historical exercise without touching those files.
    """
    directory = Path(directory)
    sheet_path, key_path = directory / "sheet.csv", directory / "key.json"
    if not sheet_path.exists() or not key_path.exists():
        raise LabelSheetError(f"no legacy sheet+key in {directory}")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    with sheet_path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        rows = list(reader)
    if header != LEGACY_COLUMNS:
        raise LabelSheetError(f"legacy sheet header is {header!r}; expected {LEGACY_COLUMNS!r}")
    if len(rows) != len(key):
        raise LabelSheetError(f"legacy sheet has {len(rows)} rows, key has {len(key)}")
    pairs = []
    unsure = 0
    unsure_detail = []
    errors = []
    for row in rows:
        rid = (row.get("row") or "").strip()
        if rid not in key:
            errors.append(f"row {rid} is not in the legacy key")
            continue
        value = (row.get(LEGACY_VERDICT_COL) or "").strip().upper()
        if value == "":
            errors.append(f"row {rid}: blank verdict")
            continue
        if value not in VERDICTS:
            errors.append(f"row {rid}: verdict {value!r} is not PASS, FAIL or UNSURE")
            continue
        entry = key[rid]
        detail = {"row": rid, "arm": entry.get("arm"), "id": entry.get("id"),
                  "trial": entry.get("trial"), "grader_verdict": entry.get("my_verdict"),
                  "human_verdict": value, "notes": row.get("notes", "")}
        if value == "UNSURE":
            unsure += 1
            unsure_detail.append(detail)
        else:
            pairs.append((value, entry["my_verdict"], detail))
    if errors:
        raise LabelSheetError("legacy sheet rejected:\n  " + "\n  ".join(errors[:20]))
    return summarize(pairs=pairs, unsure=unsure, unsure_detail=unsure_detail,
                     recognized={"legacy_sheet_has_no_recognized_column": len(rows)},
                     exclusions=[], unresolved=[], extra={"legacy_mode": True,
                     "arm_blind": False,
                     "warning": "legacy sheet exposes scenario and arm; not arm-blind"})
