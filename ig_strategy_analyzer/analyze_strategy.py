#!/usr/bin/env python3
"""
analyze_strategy.py — turn trading-strategy videos into backtest-ready artifacts.

For each video: sample chart frames + transcribe the trader's audio, extract a
precise strategy spec (instrument, timeframe, indicators, entry/exit, risk, and
crucially which parameters are SPECIFIED vs need OPTIMIZATION), then — depending
on how codable the strategy is — generate a compilable MQL5 EA scaffold and/or a
parameter map.

The 'to_optimize' parameters are the genes your MT5 DNA system sweeps in the
backtest; fitness = real backtest P&L (via OnTester -> gold_dna_memory.csv). The
video gives the *shape* of the strategy; the optimizer finds the *numbers*.

    set ANTHROPIC_API_KEY=sk-ant-...
    python analyze_strategy.py --videos ./videos --out ./strategies

Per-video output in ./strategies:
    <video>.spec.json     the extracted strategy (always)
    <video>.mq5           MQL5 EA scaffold (when codability == standalone)
    <video>.params.json   parameter map (when standalone or needs_parametric_ea)
"""

import re
import json
import base64
import argparse
from pathlib import Path

import cv2
from faster_whisper import WhisperModel

# reuse transcription + client/config from analyze_reels.py (same folder)
from analyze_reels import transcribe, client, MODEL, LANGUAGE, WHISPER_SIZE

CHART_FRAMES = 14        # charts carry detail -> sample more, evenly across the clip
CHART_WIDTH = 1024       # higher res than content frames so indicator values stay legible


EXTRACT_SPEC_SYSTEM = (
    "You are a quantitative trading analyst. You receive the AUDIO TRANSCRIPT of a "
    "trading video (a trader explaining a strategy) and FRAMES from it (chart "
    "screenshots showing indicators, entries, and patterns). Extract the strategy as "
    "precisely as the video allows.\n\n"
    "Be rigorous and honest: capture only what is actually stated or clearly shown. For "
    "anything left vague (exact thresholds, indicator periods, SL/TP distances), DO NOT "
    "invent a fixed value — instead list it under parameters.to_optimize with a sensible "
    "suggested range. Those become the search space for backtest optimization.\n\n"
    "Return ONLY a JSON object with this exact schema:\n"
    "{\n"
    '  "name": "short ASCII slug, e.g. RSI_Support_Bounce",\n'
    '  "instrument": "symbol if stated, else \\"unspecified\\"",\n'
    '  "timeframe": "M1|M5|M15|M30|H1|H4|D1 or \\"unspecified\\"",\n'
    '  "direction": "long | short | both",\n'
    '  "indicators": [{"name": "e.g. RSI", "params": "e.g. period=14 (stated) or to_optimize", "role": "entry|exit|filter"}],\n'
    '  "entry_rules": ["precise conditions, in order"],\n'
    '  "exit_rules": ["take-profit / stop-loss / trailing / time-based rules"],\n'
    '  "risk": {"stop_loss": "...", "take_profit": "...", "lot_or_risk": "...", "risk_reward": "..."},\n'
    '  "filters": ["session/time, trend, news, spread, etc., or empty"],\n'
    '  "parameters": {\n'
    '    "specified": [{"name": "ASCII_identifier", "value": <number or string>}],\n'
    '    "to_optimize": [{"name": "ASCII_identifier", "default": <number>, "min": <number>, "max": <number>, "step": <number>}]\n'
    "  },\n"
    '  "codability": "standalone | needs_parametric_ea | underspecified",\n'
    '  "ambiguities": ["what the video left unclear or assumed"],\n'
    '  "confidence": <integer 0-100>\n'
    "}\n\n"
    "Every parameter 'name' MUST be a valid MQL5 identifier (ASCII, no spaces). "
    "'codability' = standalone if the rules are complete enough to code a self-contained "
    "EA; needs_parametric_ea if it is a variation that maps onto an existing parametric "
    "EA; underspecified if too vague to code. "
    f"Write 'entry_rules', 'exit_rules', 'filters', and 'ambiguities' in {LANGUAGE}; keep "
    "identifiers, symbols, timeframes, and indicator names in English."
)


GEN_MQL5_SYSTEM = (
    "You are an expert MQL5 developer. Given a strategy spec (JSON), write a COMPLETE, "
    "COMPILABLE MetaTrader 5 Expert Advisor that implements it and is ready for the "
    "Strategy Tester and optimization.\n\n"
    "Requirements:\n"
    "- #include <Trade/Trade.mqh> and use CTrade for all order operations.\n"
    "- Declare EVERY spec parameter as an `input`. 'specified' params use their value as "
    "default; 'to_optimize' params use 'default' as the input value and put the suggested "
    "min/max/step in a trailing // comment so the Strategy Tester optimizer can sweep them.\n"
    "- OnInit(): create all needed indicator handles (iRSI, iMA, iATR, etc.), validate "
    "them, return INIT_SUCCEEDED / INIT_FAILED appropriately.\n"
    "- OnTick(): implement entry and exit logic exactly per the rules using CopyBuffer; "
    "respect the filters; do one clean position-management pass; handle SL/TP.\n"
    "- Include basic lot/risk sizing consistent with the spec's risk section.\n"
    "- OnTester(): compute a fitness value from TesterStatistics (e.g. net profit adjusted "
    "by drawdown) and APPEND a row (the input params + the fitness) to the common file "
    "\"gold_dna_memory.csv\" using FileOpen(..., FILE_COMMON|FILE_READ|FILE_WRITE|FILE_CSV). "
    "Add a clear comment that the columns should be aligned with the user's existing "
    "gold_dna_memory.csv schema.\n"
    "- A header comment block: strategy name, instrument, timeframe, a one-line summary, "
    "and a TODO list built from the spec's 'ambiguities'.\n"
    "- Where the spec is ambiguous, pick a reasonable, clearly-commented default rather "
    "than leaving the code broken, and note the assumption in the header TODO.\n\n"
    "Output ONLY the raw MQL5 source code. No markdown, no code fences, no commentary."
)


def extract_chart_frames(video_path, max_frames=CHART_FRAMES, max_width=CHART_WIDTH):
    """Sample frames evenly across the whole video (chart context can be anywhere)."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total / fps if fps else 0.0
    timestamps = ([duration * (i + 0.5) / max_frames for i in range(max_frames)]
                  if duration > 0 else [0.0])

    frames = []
    for t in timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        if w > max_width:
            scale = max_width / w
            frame = cv2.resize(frame, (max_width, int(h * scale)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            frames.append(base64.b64encode(buf).decode("utf-8"))
    cap.release()
    return frames, duration


def extract_spec(frames, transcript, duration):
    content = [{
        "type": "text",
        "text": (
            f"Trading video. Duration {duration:.0f}s.\n"
            f'Audio transcript (the trader explaining the setup):\n'
            f'"{transcript or "(no speech detected)"}"\n\n'
            f"{len(frames)} chart frames sampled across the video are attached. "
            "Extract the strategy spec as JSON."
        ),
    }]
    for b in frames:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b},
        })

    resp = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=EXTRACT_SPEC_SYSTEM,
        messages=[
            {"role": "user", "content": content},
            {"role": "assistant", "content": "{"},  # prefill -> JSON
        ],
    )
    text = "".join(x.text for x in resp.content if getattr(x, "type", "") == "text")
    raw = ("{" + text).strip()
    return json.loads(raw[: raw.rfind("}") + 1])


def _strip_code(text):
    text = text.strip()
    text = re.sub(r"^```[A-Za-z0-9_+-]*\n", "", text)
    text = re.sub(r"\n```$", "", text)
    return text.strip()


def generate_mql5(spec):
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=GEN_MQL5_SYSTEM,
        messages=[{
            "role": "user",
            "content": "Generate the MQL5 EA for this strategy spec:\n"
                       + json.dumps(spec, ensure_ascii=False, indent=2),
        }],
    )
    text = "".join(x.text for x in resp.content if getattr(x, "type", "") == "text")
    return _strip_code(text)


def write_outputs(spec, out_dir, stem):
    """Write spec.json always; params.json + .mq5 depending on codability."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [out_dir / f"{stem}.spec.json"]
    written[0].write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    cod = spec.get("codability", "underspecified")
    if cod in ("standalone", "needs_parametric_ea"):
        pp = out_dir / f"{stem}.params.json"
        pp.write_text(json.dumps(spec.get("parameters", {}), ensure_ascii=False, indent=2),
                      encoding="utf-8")
        written.append(pp)
    if cod == "standalone":
        mp = out_dir / f"{stem}.mq5"
        mp.write_text(generate_mql5(spec), encoding="utf-8")
        written.append(mp)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", default="./videos")
    ap.add_argument("--out", default="./strategies")
    args = ap.parse_args()

    vids_dir = Path(args.videos)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    exts = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    videos = sorted(p for p in vids_dir.glob("*") if p.suffix.lower() in exts)
    if not videos:
        print(f"No videos found in {vids_dir.resolve()}")
        return

    print(f"Loading Whisper ({WHISPER_SIZE})...")
    whisper = WhisperModel(WHISPER_SIZE, device="auto", compute_type="int8")

    made = 0
    for i, vf in enumerate(videos, 1):
        spec_path = out_dir / f"{vf.stem}.spec.json"
        if spec_path.exists():  # resumable
            print(f"[{i}/{len(videos)}] {vf.name} -> cached")
            continue

        print(f"[{i}/{len(videos)}] {vf.name} -> extracting strategy")
        try:
            frames, duration = extract_chart_frames(vf)
            if not frames:
                print("   skipped (could not read frames)")
                continue
            transcript = transcribe(vf, whisper)
            spec = extract_spec(frames, transcript, duration)
            write_outputs(spec, out_dir, vf.stem)

            made += 1
            cod = spec.get("codability", "underspecified")
            n_opt = len(spec.get("parameters", {}).get("to_optimize", []))
            print(f"   {spec.get('name', '?')} | {spec.get('instrument', '?')} "
                  f"{spec.get('timeframe', '')} | {cod} | {n_opt} params to optimize "
                  f"| confidence {spec.get('confidence', '?')}")
        except Exception as e:
            print(f"   error: {e}")

    print(f"\nDone. {made} strategies -> {out_dir.resolve()}")


if __name__ == "__main__":
    main()
