#!/usr/bin/env python3
"""
extract_web.py — written trading strategies (web pages / text) -> the same
strategy spec (+ MQL5 / params) as the video pipeline. Completes the
"multi-source" requirement: text and video both produce one interchangeable spec.

    python extract_web.py --url https://site.com/article --out ./strategies
    python extract_web.py --file ./notes.txt --out ./strategies
"""

import re
import json
import argparse
from pathlib import Path
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from analyze_reels import client, MODEL
from analyze_strategy import EXTRACT_SPEC_SYSTEM, write_outputs


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            t = data.strip()
            if t:
                self.parts.append(t)


def fetch_text(url, limit=20000):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="ignore")
    p = _TextExtractor()
    p.feed(html)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(p.parts))
    return text[:limit]


def extract_spec_from_text(text, source=""):
    label = f" from {source}" if source else ""
    user = (f"This is a WRITTEN trading-strategy source (no video){label}. "
            f"Extract the strategy spec from the text below.\n\n{text}")
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=EXTRACT_SPEC_SYSTEM,
        messages=[
            {"role": "user", "content": user},
            {"role": "assistant", "content": "{"},  # prefill -> JSON
        ],
    )
    out = "".join(x.text for x in resp.content if getattr(x, "type", "") == "text")
    raw = ("{" + out).strip()
    return json.loads(raw[: raw.rfind("}") + 1])


def _slug(s):
    return (re.sub(r"[^A-Za-z0-9_]+", "_", s or "strategy").strip("_")[:50]) or "strategy"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--out", default="./strategies")
    args = ap.parse_args()

    if args.url:
        text, source = fetch_text(args.url), args.url
    elif args.file:
        text, source = Path(args.file).read_text(encoding="utf-8"), args.file
    else:
        raise SystemExit("Provide --url or --file")

    spec = extract_spec_from_text(text, source)
    base = spec.get("name") or (Path(args.file).stem if args.file else "strategy")
    files = write_outputs(spec, args.out, _slug(base))
    print(f"{spec.get('name', '?')} | {spec.get('codability')} -> "
          + ", ".join(p.name for p in files))


if __name__ == "__main__":
    main()
