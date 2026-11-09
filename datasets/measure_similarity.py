#!/usr/bin/env python3
"""
Measure how much an agent's replies vary between runs.

This exists because it decided a design question. A sealed validation set was
planned as "the same scenarios, run again, producing replies the graders have
never been fitted to". That only works if the agent says something different the
second time. It mostly does not.

  python datasets/measure_similarity.py --arm A5

Reports the cosine similarity between two trials of the same scenario, using the
same embedding model the contamination check uses, so the two numbers are
comparable.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "BAAI/bge-small-en-v1.5"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="A5")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--threshold", type=float, default=0.95)
    args = ap.parse_args()

    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    data = json.loads((ROOT / "evals" / "results" / f"{args.arm}.json").read_text(encoding="utf-8"))
    by: dict[str, dict[int, str]] = defaultdict(dict)
    for r in data.get("records", []):
        if "thread" in r:
            by[r["id"]][r["trial"]] = r["thread"]

    pairs = [(sid, t[1], t[2]) for sid, t in by.items() if 1 in t and 2 in t]
    if not pairs:
        print(f"no scenario in {args.arm} has two trials")
        return 2

    tok = AutoTokenizer.from_pretrained(args.model)
    mdl = AutoModel.from_pretrained(args.model).eval()

    def embed(texts: list[str]) -> "np.ndarray":
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), 32):
                enc = tok(texts[i:i + 32], padding=True, truncation=True,
                          max_length=512, return_tensors="pt")
                cls = mdl(**enc).last_hidden_state[:, 0]
                out.append(torch.nn.functional.normalize(cls, p=2, dim=1).cpu().numpy())
        return np.vstack(out)

    a = embed([p[1] for p in pairs])
    b = embed([p[2] for p in pairs])
    sims = (a * b).sum(axis=1)

    print(f"{args.arm}: {len(pairs)} scenarios with two trials")
    print(f"  median cosine {np.median(sims):.3f}   min {sims.min():.3f}   max {sims.max():.3f}")
    print(f"  above {args.threshold}: {(sims >= args.threshold).sum()}/{len(sims)}")
    print()
    print("  A sealed set built from fresh replies on these scenarios would be roughly")
    print(f"  {100 * (sims >= args.threshold).mean():.0f}% near-duplicate of the corpus the graders were fitted to.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
