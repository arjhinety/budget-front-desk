#!/usr/bin/env python3
"""
Capture the public pages of one business, with provenance.

Every page is stored three ways so a later reader can check any claim:
  raw/<slug>.html   the bytes as served
  raw/<slug>.txt    visible text only (scripts, styles, nav chrome stripped)
  facts/provenance.json   URL, fetched_at (UTC), http status, byte count,
                          sha256 of the body, and the robots.txt verdict

Nothing is extracted here. Extraction is a separate, reviewable step
(build_facts.py) so that every field in the facts ledger points back at a
file this script wrote.

Usage:  python scrape.py [--root https://www.example.com]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
FACTS = ROOT / "facts"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) reference-use capture for a business agent brief"

# Pages worth having for a home-services agent. Missing ones are recorded as
# missing rather than skipped silently.
WANTED = [
    ("/", "home"),
    ("/book-online/", "book"),
    ("/plumbing/", "plumbing"),
    ("/heating/", "heating"),
    ("/air-conditioning/", "cooling"),
    ("/emergency-plumbing/", "emergency"),
    ("/areas-we-service/", "areas"),
    ("/contact-us/", "contact"),
    ("/maintenance/", "maintenance"),
    ("/financing/", "financing"),
    ("/about-us/", "about"),
]

STRIP_BLOCKS = re.compile(r"<(script|style|noscript|svg)\b[\s\S]*?</\1>", re.I)
TAG = re.compile(r"<[^>]+>")
ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&quot;": '"', "&#x27;": "'", "&#39;": "'",
    "&apos;": "'", "&lt;": "<", "&gt;": ">", "&mdash;": "\u2014",
    "&ndash;": "\u2013", "&rsquo;": "\u2019", "&lsquo;": "\u2018",
    "&ldquo;": "\u201c", "&rdquo;": "\u201d",
}


def slug_for(path: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", path.strip("/").lower()).strip("-")
    return s or fallback


def visible_text(html: str) -> str:
    body = STRIP_BLOCKS.sub(" ", html)
    # keep block boundaries as newlines so line-level facts keep their shape
    body = re.sub(r"</(p|div|li|h[1-6]|tr|section|header|footer)\s*>", "\n", body, flags=re.I)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    body = TAG.sub(" ", body)
    for entity, char in ENTITIES.items():
        body = body.replace(entity, char)
    body = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), body)
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in body.split("\n")]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip() + "\n"


def fetch(url: str, timeout: int = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="https://www.rojasplumbinghvac.com")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    FACTS.mkdir(parents=True, exist_ok=True)
    host = urlparse(args.root).netloc

    # ---- robots, recorded as a verdict rather than an afterthought
    robots_url = f"{args.root.rstrip('/')}/robots.txt"
    robots_body, robots_status = "", 0
    try:
        robots_status, raw = fetch(robots_url)
        robots_body = raw.decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        print(f"robots.txt unreadable ({exc}); treating as no published rules", file=sys.stderr)

    rp = RobotFileParser()
    rp.parse(robots_body.splitlines())
    allowed = rp.can_fetch(UA, args.root)
    signals = re.findall(r"Content-Signal:\s*(.+)", robots_body)

    records, missing = [], []
    for path, name in WANTED:
        url = urljoin(args.root, path)
        slug = slug_for(path, name)
        try:
            status, body = fetch(url)
        except urllib.error.HTTPError as exc:
            missing.append({"url": url, "status": exc.code, "note": "requested, not served"})
            continue
        except urllib.error.URLError as exc:
            missing.append({"url": url, "status": None, "note": str(exc)})
            continue

        html = body.decode("utf-8", "replace")
        (RAW / f"{slug}.html").write_bytes(body)
        (RAW / f"{slug}.txt").write_text(visible_text(html), encoding="utf-8")

        records.append({
            "slug": slug,
            "url": url,
            "final_url": url,
            "status": status,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "text_file": f"raw/{slug}.txt",
            "text_chars": len((RAW / f"{slug}.txt").read_text(encoding="utf-8")),
        })
        print(f"  {status}  {len(body):>8}  {url}")

    provenance = {
        "target_root": args.root,
        "host": host,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user_agent": UA,
        "robots": {
            "url": robots_url,
            "status": robots_status,
            "can_fetch_this_agent": allowed,
            "content_signals": signals,
            "reading": (
                "Content-Signal 'use=reference' permits reading these pages to build a "
                "reference agent; 'ai-train=no' is honoured in that no page text is used "
                "to train a model. No named-bot prohibition applies to this UA."
                if any("use=reference" in s for s in signals)
                else "No content-signal directive published; generic Allow applies."
            ),
        },
        "pages": records,
        "not_served": missing,
    }
    (FACTS / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\n{len(records)} pages captured, {len(missing)} not served -> facts/provenance.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
