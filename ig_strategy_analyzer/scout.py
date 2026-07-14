#!/usr/bin/env python3
"""
scout.py — continuous strategy-discovery orchestrator.

Keeps running. Each cycle it (1) discovers new strategy sources from the web
(Claude API + web_search), (2) routes each new source to the text or video
extractor to produce a backtest-ready spec/EA, (3) hands new strategies to your
MT5 backtest hook, and (4) surfaces backtested winners through a deploy gate. A
registry de-dupes sources so each is processed once across cycles.

Runs on YOUR machine as a service (same pattern as ea_monitor.py), with the
Claude API as its brain. The MT5 backtest + deploy steps are HOOKS you wire to
your existing DNA system (see backtest_hook / deploy_gate).

    set ANTHROPIC_API_KEY=sk-ant-...
    python scout.py --once      # single cycle, for testing
    python scout.py             # run continuously

Requires the web_search tool to be enabled for your API key. The tool version
string below may need updating to the current one.
"""

import json
import time
import tempfile
import subprocess
import argparse
from pathlib import Path

from analyze_reels import client, MODEL, transcribe, WHISPER_SIZE
from analyze_strategy import extract_chart_frames, extract_spec, write_outputs
from extract_web import fetch_text, extract_spec_from_text, _slug

# ---- config: edit to your niche / cadence ----
SEARCH_QUERIES = [
    "XAUUSD scalping strategy explained",
    "gold trading strategy indicator rules",
    "price action support resistance breakout strategy",
]
POLL_INTERVAL_SEC = 3600        # how often to look for new strategies
MAX_NEW_PER_CYCLE = 5
MIN_CONFIDENCE = 50             # skip thin extractions below this
OUT_DIR = Path("./strategies")
VIDEO_DIR = Path("./videos")
REGISTRY = Path("./strategies/registry.json")
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}
# ----------------------------------------------

_whisper = None


def whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(WHISPER_SIZE, device="auto", compute_type="int8")
    return _whisper


def load_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}


def save_registry(reg):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def discover(known_urls):
    """Use Claude + web_search to find new candidate strategy sources."""
    prompt = (
        "Find recent, concrete trading-strategy sources (articles or videos) for these "
        f"topics: {SEARCH_QUERIES}. Prefer sources that actually spell out rules "
        "(indicators, entries, exits), not generic overviews. Return ONLY a JSON array; "
        'each item: {"url": "...", "type": "text" or "video", "title": "..."}. '
        f"Exclude these already-seen URLs: {list(known_urls)[:50]}."
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=1500, tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    try:
        s, e = text.find("["), text.rfind("]")
        items = json.loads(text[s:e + 1]) if s >= 0 else []
    except Exception:
        items = []
    return [it for it in items if it.get("url") and it["url"] not in known_urls]


def process_text(url):
    spec = extract_spec_from_text(fetch_text(url), url)
    return spec, write_outputs(spec, OUT_DIR, _slug(spec.get("name") or url))


def process_video(url):
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        out_tmpl = str(Path(td) / "%(id)s.%(ext)s")
        subprocess.run(["yt-dlp", "-f", "mp4", "-o", out_tmpl, url],
                       check=True, capture_output=True)
        mp4s = list(Path(td).glob("*.mp4"))
        if not mp4s:
            raise RuntimeError("download produced no mp4")
        frames, duration = extract_chart_frames(mp4s[0])
        transcript = transcribe(mp4s[0], whisper())
        spec = extract_spec(frames, transcript, duration)
    return spec, write_outputs(spec, OUT_DIR, _slug(spec.get("name") or url))


# ---- HOOKS into your main trading system (wire to your MT5 / DNA setup) ----
def backtest_hook(new_strategies):
    """new_strategies: list of (url, spec, files).
    Wire this to your MT5 backtest: compile each .mq5 (MetaEditor CLI), run the
    Strategy Tester / optimizer over the to_optimize params, and let OnTester
    write fitness to gold_dna_memory.csv. For now it only logs — fill in once you
    share how you trigger a backtest."""
    for url, spec, files in new_strategies:
        print(f"   [backtest TODO] {spec.get('name')} ({spec.get('codability')})")


def deploy_gate(reg):
    """Rank backtested winners (from gold_dna_memory.csv) and hold them for your
    manual approval before live deployment. Deliberately a no-op for safety —
    never auto-deploy to real money unreviewed."""
    return
# ----------------------------------------------------------------------------


def cycle():
    reg = load_registry()
    found = discover(set(reg.keys()))[:MAX_NEW_PER_CYCLE]
    print(f"Discovered {len(found)} new candidate(s).")

    new_strategies = []
    for it in found:
        url, typ = it["url"], it.get("type", "text")
        entry = {"type": typ, "title": it.get("title", ""),
                 "added_at": time.time(), "status": "processing"}
        reg[url] = entry
        try:
            spec, files = process_video(url) if typ == "video" else process_text(url)
            conf = spec.get("confidence", 0) or 0
            entry.update(name=spec.get("name"), codability=spec.get("codability"),
                         confidence=conf, spec_file=str(files[0]))
            if conf < MIN_CONFIDENCE:
                entry["status"] = "skipped_low_confidence"
                print(f"   ~ skipped (confidence {conf}) {url}")
            else:
                entry["status"] = "extracted"
                new_strategies.append((url, spec, files))
                print(f"   + {spec.get('name')} | {spec.get('codability')} <- {url}")
        except Exception as e:
            entry["status"] = f"error: {e}"
            print(f"   ! failed {url}: {e}")
        save_registry(reg)

    if new_strategies:
        backtest_hook(new_strategies)
    deploy_gate(reg)
    save_registry(reg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run a single cycle then exit")
    args = ap.parse_args()

    print("Strategy scout started.")
    while True:
        try:
            cycle()
        except Exception as e:
            print(f"cycle error: {e}")
        if args.once:
            break
        print(f"Sleeping {POLL_INTERVAL_SEC}s...\n")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
