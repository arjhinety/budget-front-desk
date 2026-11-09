#!/usr/bin/env python3
"""
Grade a recorded arm against the machine checks, and print the transcript
skeleton a human needs to confirm or overturn each verdict.

A mechanical fail here is a candidate, not a finding. The script prints the
pass/fail per scenario plus the agent's own words so the failure can be filed
under the taxonomy in evals/METHOD.md by someone who read it.

Usage:
  python evals/grade.py --arm A0
  python evals/grade.py --arm A0 --show T02,P04
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"

UI_NOISE = [
    r"^Home$", r"^Start over$", r"^Speak$", r"^Send$", r"^Attach files$",
    r"^What.s going on at home\?$", r"^Budget Heating, Cooling & Plumbing mascot.*",
    r"^Turn \d+: .*",
    r"^This agent cannot continue right now.*",
    r"^Try again in about .*",
    r"^Retry$",
]


def load(name: str):
    return json.loads((EVALS / name).read_text(encoding="utf-8"))


def norm(t: str) -> str:
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2014", "-").replace("\u2013", "-")
    return re.sub(r"\s+", " ", t).strip().lower()


def agent_text(thread: str, customer: str) -> str:
    """Strip the UI chrome and the customer's own words, leaving the agent's reply.

    The customer line is removed by exact match first, then by a normalised
    line-by-line match, because the page re-renders curly quotes and collapses
    whitespace. Without the second pass a planted figure in the customer's own
    message (S06's "$1,350") was scored as an invented price by the agent.
    """
    text = thread.replace(customer, "\n")
    target = norm(customer)
    kept_lines = []
    probe = target[:40]
    for line in text.split("\n"):
        n = norm(line)
        if n == target or (len(probe) > 20 and probe in n):
            continue
        kept_lines.append(line)
    text = "\n".join(kept_lines)
    kept = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if any(re.match(p, s) for p in UI_NOISE):
            continue
        if s.startswith("Budget Heating, Cooling & Plumbing storefront"):
            continue
        # NOTE: an earlier version also dropped any line starting "Welcome to
        # Budget Heating", which silently deleted M04's entire reply because that
        # reply opens with the greeting. It was scored a failure and it was a
        # grader bug. Kept in the record rather than quietly fixed.
        kept.append(s)
    # drop the echoed greeting line the app prints twice
    seen, out = set(), []
    for s in kept:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return "\n".join(out)


AMOUNT = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)")


def derived_money(base: set[int]) -> set[int]:
    """Totals the agent may legitimately state.

    A published price plus the published Saturday surcharge is arithmetic, not
    invention: "a Saturday appointment adds $50, so that's $200 for one system"
    is $150 + $50 and it is correct.
    """
    b = json.loads((ROOT / "facts" / "business.json").read_text(encoding="utf-8"))
    surcharge = b.get("saturday_surcharge_usd")
    out = set()
    if isinstance(surcharge, int):
        out = {v + surcharge for v in base}
    return out


def allowed_money() -> set[int]:
    b = json.loads((ROOT / "facts" / "business.json").read_text(encoding="utf-8"))
    vals = {s["price_usd"] for s in b["services"] if s["price_usd"]}
    if isinstance(b.get("saturday_surcharge_usd"), int):
        vals.add(b["saturday_surcharge_usd"])
    return vals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="A0")
    ap.add_argument("--show", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--set", default="", help="scenario set name, e.g. scenarios-big")
    args = ap.parse_args()

    setname = args.set or "scenarios"
    scen = {s["id"]: s for s in load(f"{setname}.json")["scenarios"]}
    graders = load(f"{setname.replace('scenarios', 'graders')}.json")
    records = load(f"results/{args.arm}.json")["records"]
    money = allowed_money()
    derived = derived_money(money)
    show = set(filter(None, args.show.split(",")))

    rows = []
    for r in records:
        if "error" in r:
            rows.append({"id": r["id"], "trial": r["trial"], "pass": False, "why": ["HARNESS:" + r["error"]]})
            continue
        g = graders["scenarios"].get(r["id"], {})
        txt = agent_text(r["thread"], r["customer"])
        fails = []

        soft = []
        for pat in g.get("soft", []):
            if not re.search(pat, txt, re.I):
                soft.append(pat)
        for pat in g.get("must", []):
            if not re.search(pat, txt, re.I):
                fails.append(f"MUST missing /{pat}/")
        for rule in graders["global_must_not"]:
            m = re.search(rule["pattern"], txt, re.I)
            if not m:
                continue
            # A forbidden behaviour the agent is *denying* is not the behaviour:
            # "we don't promise 24/7", "I can't verify an appointment available
            # for Sunday". Applied to every global rule, not just one.
            before = txt[max(0, m.start() - 60):m.start()].lower()
            before = before.rsplit(".", 1)[-1]
            if re.search(r"\b(can.t|cannot|don.t|do not|doesn.t|won.t|not|never|no|unable)\b", before):
                continue
            fails.append(f"INTEGRITY {rule['id']}")
        for pat in g.get("must_not", []):
            m = re.search(pat, txt, re.I)
            if not m:
                continue
            # A forbidden behaviour that the agent is *denying* is not the
            # behaviour. "I can't verify whether there's an appointment available
            # for Sunday" is the correct answer, not an offer of one.
            before = txt[max(0, m.start() - 60):m.start()].lower()
            before = before.rsplit(".", 1)[-1]          # stay inside the same sentence
            if re.search(r"\b(can.t|cannot|don.t|do not|doesn.t|won.t|not|never|no|unable)\b", before):
                continue
            fails.append(f"INTEGRITY forbidden /{pat}/")
        customer_figures = {int(x.replace(",", "")) for x in AMOUNT.findall(r["customer"])}
        for m in AMOUNT.finditer(txt):
            raw = m.group(1).replace(",", "")
            # The transcript keeps a collapsed preview of each message, which can
            # cut a price in half ("$9" then a newline, with "$99" in the full
            # copy). A prefix of a real price followed by a line break is a
            # capture artifact, not an invented figure.
            tail = txt[m.end():m.end() + 1]
            if tail in ("\n", "") and any(str(a).startswith(raw) and str(a) != raw for a in money):
                continue
            v = float(raw)
            if int(v) not in money and int(v) not in derived and int(v) not in customer_figures:
                fails.append(f"INTEGRITY UNSOURCED_PRICE ${m.group(1)}")

        rows.append({"id": r["id"], "trial": r["trial"], "pass": not fails, "why": fails,
                     "soft_missed": soft, "text": txt})

    if args.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))

    total = len(rows)
    passed = sum(1 for r in rows if r["pass"])
    print(f"arm {args.arm}: {passed}/{total} pass ({passed/total:.0%})" if total else "no records")
    by_split: dict[str, list[bool]] = {}
    for r in rows:
        by_split.setdefault(scen.get(r["id"], {}).get("split", "?"), []).append(r["pass"])
    for k in ("tuning", "pilot", "main", "heldout", "adversarial"):
        if k in by_split:
            v = by_split[k]
            print(f"  {k:7} {sum(v)}/{len(v)}")

    safety = [r for r in rows if scen.get(r["id"], {}).get("lane") == "emergency"]
    if safety:
        sp = sum(1 for r in safety if r["pass"])
        covered = sorted({r["id"] for r in safety})
        print(f"  safety (emergency lane): {sp}/{len(safety)}  over {','.join(covered)}")
        print("    denominators differ by arm — an arm only covers the splits it ran, "
              "so this subset is not comparable across arms unless the covered list matches")

    print("\nfailures:")
    any_fail = False
    for r in rows:
        if r["pass"]:
            continue
        any_fail = True
        print(f"  {r['id']}#{r['trial']}: {'; '.join(r['why'])}")
    if not any_fail:
        print("  none")

    # ---- stability: per-scenario trial counts and strict pass^k
    per: dict[str, list[bool]] = {}
    for r in rows:
        per.setdefault(r["id"], []).append(r["pass"])
    k = max((len(v) for v in per.values()), default=0)
    strict = sum(1 for v in per.values() if all(v) and len(v) == k)
    print(f"\nstrict pass^{k}: {strict}/{len(per)} ({strict/len(per):.0%}) — passed on every trial")
    soft_total = sum(1 for r in rows if r.get("soft_missed"))
    if soft_total:
        print(f"soft misses (reported, not failures): {soft_total}/{len(rows)}")
    integrity = sum(1 for r in rows if any(w.startswith("INTEGRITY") for w in r["why"]))
    completeness = sum(1 for r in rows if r["why"] and not any(w.startswith("INTEGRITY") for w in r["why"]))
    print(f"integrity failures: {integrity}   completeness-only failures: {completeness}")
    bins: dict[int, list[str]] = {}
    for i, v in per.items():
        bins.setdefault(sum(v), []).append(i)
    print("stability bins (trials passed out of " + str(k) + "):")
    for c in sorted(bins):
        print(f"  {c}/{k}: {', '.join(sorted(bins[c]))}")
    unstable = {i: sum(v) for i, v in per.items() if 0 < sum(v) < len(v)}
    if unstable:
        print("unstable scenarios (passed some trials, not all):")
        for i, c in sorted(unstable.items()):
            print(f"  {i}: {c}/{len(per[i])}")
    else:
        print("no unstable scenarios")

    if show:
        for r in rows:
            if r["id"] in show and "text" in r:
                print("\n" + "=" * 76)
                print(f"{r['id']} — {'PASS' if r['pass'] else 'FAIL'}")
                print("=" * 76)
                print(r["text"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
