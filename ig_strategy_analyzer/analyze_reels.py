#!/usr/bin/env python3
"""
Instagram Reels -> Strategy Analysis pipeline.

Takes a folder of video files (.mp4/.mov/...) and produces a structured JSON
analysis of each one (hook, content, CTA, editing, replicable takeaways) using
a Whisper transcript of the audio + Claude's vision on sampled frames.

Usage:
    set ANTHROPIC_API_KEY=sk-ant-...        (Windows)   or
    export ANTHROPIC_API_KEY=sk-ant-...     (mac/Linux)
    python analyze_reels.py --videos ./videos --out ./out

Output:
    ./out/<video_name>.json   one file per video (resumable: re-runs skip these)
    ./out/analyses.json       combined list -> this is what the app reads
"""

import json
import base64
import argparse
from pathlib import Path

import cv2
from faster_whisper import WhisperModel
from anthropic import Anthropic

# ---- config -------------------------------------------------------------
MODEL = "claude-sonnet-4-6"   # bump to "claude-opus-4-8" for deeper analysis
WHISPER_SIZE = "base"         # tiny / base / small / medium / large-v3
LANGUAGE = "Arabic"           # language for the human-readable text fields
MAX_FRAMES = 12               # total frames sent to Claude per video
FRAME_MAX_WIDTH = 768         # downscale frames to keep token cost low
# ------------------------------------------------------------------------

client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

SYSTEM_PROMPT = f"""You are a senior short-form video strategist analyzing an \
Instagram Reel for a content team. You receive the audio transcript and a set \
of frames sampled across the video (the first few frames are from the opening \
3 seconds, where the hook lives).

Pay special attention to the HOOK (first 3 seconds) and the CTA, since these \
are the team's priorities, then cover everything else in detail.

Respond with ONLY a JSON object (no markdown, no commentary) using exactly \
this schema:
{{
  "hook": {{
    "type": "one of: question | bold_claim | shock | curiosity_gap | story | problem | pattern_interrupt | relatable | other",
    "first_3s": "what literally happens in the first 3 seconds",
    "spoken_opening": "the first spoken words, or empty string",
    "on_screen_text": "opening on-screen text, or empty string",
    "why_it_works": "why this hook does or doesn't grab attention",
    "score": <integer 1-10>
  }},
  "content": {{
    "format": "one of: tutorial | listicle | story | talking_head | demo | skit | tips | reaction | other",
    "main_message": "the core message in one sentence",
    "key_points": ["the main points covered"],
    "value": "one of: educational | entertaining | emotional | inspirational | promotional",
    "pacing": "one of: slow | medium | fast"
  }},
  "cta": {{
    "present": true,
    "type": "one of: follow | comment | save | share | link_in_bio | dm | none",
    "wording": "the exact CTA wording, or empty string",
    "placement": "one of: start | middle | end | none",
    "score": <integer 1-10>
  }},
  "editing": {{
    "techniques": ["e.g. jump_cuts, captions, zoom, b_roll, text_overlay, transitions"],
    "audio": "one of: trending_sound | voiceover | music | original_audio | none",
    "notes": "notable editing or production choices"
  }},
  "overall_strategy": "2-3 sentences on the overall strategy of this video",
  "takeaways": ["concrete, copyable tactics we can apply to our own videos"]
}}

Write every human-readable text value in {LANGUAGE}. Keep the JSON keys and \
the enum-style type/format/value/audio/placement values in English."""


def extract_frames(video_path):
    """Sample frames: dense in the first 3s (the hook), spread across the rest."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total / fps if fps else 0.0

    hook_ts = [t for t in (0.0, 0.6, 1.2, 1.8, 2.4) if t < max(duration, 0.1)]
    remaining = max(MAX_FRAMES - len(hook_ts), 0)
    rest_ts = []
    if duration > 3 and remaining > 0:
        step = (duration - 3) / (remaining + 1)
        rest_ts = [3 + step * (i + 1) for i in range(remaining)]

    frames = []
    for t in hook_ts + rest_ts:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        if w > FRAME_MAX_WIDTH:
            scale = FRAME_MAX_WIDTH / w
            frame = cv2.resize(frame, (FRAME_MAX_WIDTH, int(h * scale)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            frames.append(base64.b64encode(buf).decode("utf-8"))
    cap.release()
    return frames, duration


def transcribe(video_path, model):
    """Transcribe the spoken audio (captures hooks/CTAs that are said, not shown)."""
    segments, _ = model.transcribe(str(video_path), vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


def analyze(frames_b64, transcript, duration):
    content = [{
        "type": "text",
        "text": (
            f"Analyze this Instagram Reel. Duration: {duration:.0f}s.\n"
            f'Audio transcript: "{transcript or "(no speech detected)"}"\n\n'
            f"Below are {len(frames_b64)} frames sampled across the video "
            f"(the first few are from the opening 3 seconds). "
            f"Return the JSON analysis."
        ),
    }]
    for b64 in frames_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": content},
            {"role": "assistant", "content": "{"},  # prefill -> forces JSON output
        ],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    raw = ("{" + text).strip()
    return json.loads(raw[: raw.rfind("}") + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", default="./videos")
    ap.add_argument("--out", default="./out")
    args = ap.parse_args()

    videos_dir = Path(args.videos)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    exts = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    video_files = sorted(p for p in videos_dir.glob("*") if p.suffix.lower() in exts)
    if not video_files:
        print(f"No videos found in {videos_dir.resolve()}")
        return

    print(f"Loading Whisper ({WHISPER_SIZE})...")
    whisper = WhisperModel(WHISPER_SIZE, device="auto", compute_type="int8")

    results = []
    for i, vf in enumerate(video_files, 1):
        per_file = out_dir / f"{vf.stem}.json"
        if per_file.exists():  # resumable
            print(f"[{i}/{len(video_files)}] {vf.name} -> cached")
            results.append(json.loads(per_file.read_text(encoding="utf-8")))
            continue

        print(f"[{i}/{len(video_files)}] {vf.name} -> analyzing")
        try:
            frames, duration = extract_frames(vf)
            if not frames:
                print("   skipped (could not read frames)")
                continue
            transcript = transcribe(vf, whisper)
            data = {"video": vf.name, "duration_sec": round(duration, 1),
                    **analyze(frames, transcript, duration)}
            per_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            results.append(data)
        except Exception as e:  # keep going if one video fails
            print(f"   error: {e}")

    (out_dir / "analyses.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone. {len(results)} analyses -> {(out_dir / 'analyses.json').resolve()}")


if __name__ == "__main__":
    main()
