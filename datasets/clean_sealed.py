#!/usr/bin/env python3
"""
Clean the sealed set deterministically.

The independent evaluator's objection was that a model doing the cleaning makes
the sealed set a second opinion rather than a sealed set. So the cleaning is a
script: fixed rules, a frozen embedding model, a fixed threshold, and an output
file anyone can re-derive.

Nothing here decides pass or fail. It removes artefacts and measures whether the
sealed replies are too close to the replies the graders were tuned on.

  python datasets/clean_sealed.py --sealed evals/results/SEALED-A5.json \
                                  --tuned evals/results/A5.json evals/results/BIG-A2.json

Writes datasets/sealed/exclusions.json and datasets/sealed/contamination.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "datasets" / "sealed"

ARTEFACTS = [
    "cannot continue right now",
    "Something went wrong loading this page",
    "The answer could not be displayed",
]
MIN_REPLY_CHARS = 200
NEAR_DUP_THRESHOLD = 0.95
CONTAMINATION_CEILING = 0.20
MODEL = "BAAI/bge-small-en-v1.5"   # cached locally; bge-large works too if it is available


def replies_of(rec: dict) -> list[str]:
    if "replies" in rec:
        return [r for r in rec["replies"] if r]
    if "thread" in rec:
        return [rec["thread"]]
    return []


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")).get("records", [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sealed", nargs="+", required=True)
    ap.add_argument("--tuned", nargs="+", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--dry", action="store_true", help="exclusions only, no embeddings")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    sealed, tuned = [], []
    for f in args.sealed:
        sealed += load(ROOT / f)
    for f in args.tuned:
        tuned += load(ROOT / f)

    # ---- deterministic exclusions
    exclusions, kept = [], []
    for rec in sealed:
        key = f"{rec.get('id')}#{rec.get('trial')}"
        rs = replies_of(rec)
        reason = None
        if "error" in rec:
            reason = f"HARNESS: {rec['error']}"
        elif not rs:
            reason = "NO_REPLY"
        elif any(a in r for r in rs for a in ARTEFACTS):
            reason = "ARTEFACT: quota or render message in the transcript"
        elif all(len(r) < MIN_REPLY_CHARS for r in rs):
            reason = f"SHORT_REPLY: every reply under {MIN_REPLY_CHARS} chars"
        if reason:
            exclusions.append({"record": key, "reason": reason})
        else:
            kept.append(rec)

    (OUT / "exclusions.json").write_text(
        json.dumps({"policy": {"artefacts": ARTEFACTS, "min_reply_chars": MIN_REPLY_CHARS},
                    "excluded": exclusions, "kept": len(kept), "total": len(sealed)},
                   indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"excluded {len(exclusions)} of {len(sealed)} records -> datasets/sealed/exclusions.json")
    if args.dry or not kept:
        return 0

    # ---- contamination: nearest neighbour in the tuned-on corpus
    #
    # transformers + torch directly, not sentence-transformers: the latter fails to
    # import on this machine (a multiprocess/resource_tracker incompatibility) and a
    # cleaning step that cannot run is not a cleaning step.
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.model)
    mdl = AutoModel.from_pretrained(args.model).eval()

    def embed(texts: list[str], batch: int = 32) -> "np.ndarray":
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), batch):
                enc = tok(texts[i:i + batch], padding=True, truncation=True,
                          max_length=512, return_tensors="pt")
                cls = mdl(**enc).last_hidden_state[:, 0]      # BGE pools the CLS token
                cls = torch.nn.functional.normalize(cls, p=2, dim=1)
                out.append(cls.cpu().numpy())
        return np.vstack(out) if out else np.zeros((0, 1))

    tuned_texts = [r for rec in tuned for r in replies_of(rec)]
    sealed_texts = [r for rec in kept for r in replies_of(rec)]

    tuned_emb = embed(tuned_texts)
    sealed_emb = embed(sealed_texts)

    sims = sealed_emb @ tuned_emb.T
    best = sims.max(axis=1)
    flagged = int((best >= NEAR_DUP_THRESHOLD).sum())
    rate = flagged / len(best) if len(best) else 0.0

    report = {
        "model": args.model,
        "threshold": NEAR_DUP_THRESHOLD,
        "contamination_ceiling": CONTAMINATION_CEILING,
        "sealed_replies": len(sealed_texts),
        "tuned_on_replies": len(tuned_texts),
        "near_duplicates": flagged,
        "rate": round(rate, 4),
        "similarity": {"min": float(best.min()), "p50": float(np.median(best)),
                       "p95": float(np.percentile(best, 95)), "max": float(best.max())},
        "verdict": ("SEALED SET IS NOT TESTING NEW WORDING" if rate > CONTAMINATION_CEILING
                    else "sealed set is distinct enough to test new wording"),
        "note": "Flagged pairs are reported, not deleted. Deleting them would remove the "
                "cases most likely to expose a fitted rule.",
    }
    (OUT / "contamination.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")

    print(f"nearest-neighbour similarity against {len(tuned_texts)} tuned-on replies")
    print(f"  p50 {report['similarity']['p50']:.3f}   p95 {report['similarity']['p95']:.3f}   max {report['similarity']['max']:.3f}")
    print(f"  {flagged} of {len(best)} sealed replies above {NEAR_DUP_THRESHOLD} ({rate:.1%})")
    print(f"  {report['verdict']}")
    if rate > CONTAMINATION_CEILING:
        print("  stop: report this before collecting labels, not after")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
