from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from _bootstrap import bootstrap
bootstrap()

from mt5_ai.config import DATA_DIR

# ── Directories ───────────────────────────────────────────────────────────────
RESEARCH_DIR      = DATA_DIR / "research"
INBOX_DIR         = RESEARCH_DIR / "inbox"
PROCESSED_DIR     = RESEARCH_DIR / "processed"
LEARNINGS_FILE    = RESEARCH_DIR / "learnings.json"
INSTRUCTIONS_FILE = RESEARCH_DIR / "agent_instructions.json"

for d in (INBOX_DIR, PROCESSED_DIR):
    d.mkdir(parents=True, exist_ok=True)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"}

OLLAMA_URL   = "http://localhost:11434/api/generate"
VISION_MODEL = "llava"  # جرّب: llava:13b | bakllava | llava-phi3

# ═══════════════════════════════════════════════════════════════════════════════
# 📚 SMC KNOWLEDGE BASE — مستخرج من فيديوهات Smart Risk + ICT
# ═══════════════════════════════════════════════════════════════════════════════
SMC_KNOWLEDGE = """
You are analyzing a trading education video frame. The frame may show:
1. REAL candlestick charts (XAUUSD Gold, 2000-3000 price range)
2. SCHEMATIC diagrams (line drawings showing HH, HL, LH, LL, BOS, CHOCH, Demand/Supply zones)

FOR SCHEMATIC FRAMES (line drawings):
- Green/cyan lines usually = bullish price action
- Red/magenta lines usually = bearish price action  
- Boxes labeled "Demand" = bullish order block zones
- Boxes labeled "Supply" = bearish order block zones
- "BOS" text = Break of Structure (continuation signal)
- "CHOCH" text = Change of Character (reversal signal)
- "INF" = Imbalance/FVG (Fair Value Gap)
- Dotted lines with "$" = Liquidity sweep levels
- HH = Higher High, HL = Higher Low, LH = Lower High, LL = Lower Low

FOR REAL CHART FRAMES:
- Look for: Order Blocks (strong candle before impulse), FVG (3-candle gap), 
  liquidity sweeps (wick beyond level then reversal), BOS/CHOCH breaks
- Gold prices are realistic between 2000-3000

NEWS/INTRO FRAMES:
- If you see "Disclaimer", "FastBull", economic calendar, faces, logos → pattern=none, confidence<0.2
"""

# ═══════════════════════════════════════════════════════════════════════════════
# 🎯 FEW-SHOT PROMPT — أمثلة حقيقية للنموذج
# ═══════════════════════════════════════════════════════════════════════════════
FEW_SHOT_EXAMPLES = """
EXAMPLE 1 (Schematic - Bullish Order Flow):
Image shows: line chart with HH, HL, LH, LL, then CHOCH, then BOS, Demand zones in green boxes
Output: {
  "pattern": "choch",
  "bias": "bullish",
  "key_levels": [2345.50, 2760.00],
  "instruction": "Wait for price to reach 15m Demand Zone near 2345.50. On 1m, confirm CHOCH (break above last lower high) then BOS. Enter BUY at retest of new 1m Demand Zone. SL below LL at 2310.00. TP at next BOS level 2760.00 (1:3 RR).",
  "confidence": 0.85,
  "applies_to": ["BUY"],
  "tags": ["smc", "gold", "choch", "demand_zone"]
}

EXAMPLE 2 (Real Chart - Liquidity Sweep + Reversal):
Image shows: candlestick chart, price wicking below support then reversing up strongly
Output: {
  "pattern": "liquidity_sweep",
  "bias": "bullish",
  "key_levels": [2612.25, 2587.50, 2697.75],
  "instruction": "Liquidity sweep detected below 2612.25. Wait for 1m candle close back above 2612.25. Enter BUY at 2612.25 with SL at 2587.50 (below sweep low). TP at 2697.75 (previous high / 1:2 RR).",
  "confidence": 0.75,
  "applies_to": ["BUY"],
  "tags": ["smc", "gold", "liquidity_sweep", "reversal"]
}

EXAMPLE 3 (Schematic - Bearish):
Image shows: red line going down, Supply zones in red boxes, CHOCH downward
Output: {
  "pattern": "choch",
  "bias": "bearish",
  "key_levels": [2900.50, 2789.75],
  "instruction": "Price at 15m Supply Zone 2900.50. On 1m, CHOCH downward confirmed (broke below last higher low). Enter SELL at retest of new 1m Supply. SL above 2920.00. TP at 2789.75 (next demand zone).",
  "confidence": 0.80,
  "applies_to": ["SELL"],
  "tags": ["smc", "gold", "choch", "supply_zone"]
}

EXAMPLE 4 (Intro/Logo/News):
Image shows: 'Smart Risk' logo, black screen, disclaimer text, or economic calendar
Output: {
  "pattern": "none",
  "bias": "neutral",
  "key_levels": [],
  "instruction": "None",
  "confidence": 0.1,
  "applies_to": ["NONE"],
  "tags": ["smc", "gold"]
}
"""

ANALYSIS_PROMPT = f"""{SMC_KNOWLEDGE}

{FEW_SHOT_EXAMPLES}

Now analyze the provided image frame carefully. Determine if it's a schematic diagram, real chart, or intro/news frame.

Respond ONLY with valid JSON (absolutely no markdown, no explanation, no code blocks):

{{
  "pattern": "order_block|fvg|bos|choch|liquidity_sweep|none",
  "bias": "bullish|bearish|neutral",
  "key_levels": [<realistic gold prices, e.g. 2345.50>],
  "instruction": "<specific actionable instruction with exact entry, SL, TP>",
  "confidence": <0.0 to 1.0>,
  "applies_to": ["BUY"] or ["SELL"] or ["BOTH"] or ["NONE"],
  "tags": ["smc", "gold", "<pattern>"]
}}

RULES:
- Schematic frames ARE valid if they show clear structure (BOS, CHOCH, zones). Give them high confidence if structure is clear.
- Real chart frames: identify actual price levels from candles/y-axis if visible.
- If frame shows only text, logo, face, disclaimer, or calendar → confidence MUST be <0.2
- If structure is unclear → confidence <0.3
- Key levels: 2000-3000 range for Gold. Use approximate levels for schematics.
- Instruction MUST be specific and actionable."""


# ── JSON Cleaner ──────────────────────────────────────────────────────────────
def _clean_json_text(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.replace('"ONE"', '["NONE"]').replace('"one"', '["NONE"]')
    raw = raw.replace('"BUYSELL"', '["BOTH"]').replace('"buy_sell"', '["BOTH"]')
    raw = raw.replace('"ALL"', '["BOTH"]')
    raw = raw.replace("'BUY'", '"BUY"').replace("'SELL'", '"SELL"')
    raw = raw.replace("'BOTH'", '"BOTH"').replace("'NONE'", '"NONE"')
    raw = raw.replace('""BUY""', '"BUY"').replace('""SELL""', '"SELL"')
    raw = raw.replace('""NONE""', '"NONE"').replace('""BOTH""', '"BOTH"')
    raw = raw.replace('„', '"').replace('"', '"').replace('"', '"')
    raw = raw.replace("'", '"')
    # Fix common llava mistakes
    raw = re.sub(r'"\s*"', '","', raw)
    raw = re.sub(r',\s*}', '}', raw)
    raw = re.sub(r',\s*]', ']', raw)
    return raw.strip()


# ── Video Download ────────────────────────────────────────────────────────────
def is_url(text: str) -> bool:
    parsed = urlparse(text.strip())
    return bool(parsed.scheme and parsed.netloc)


def download_video(url: str, output_dir: Path) -> Path | None:
    url = url.strip()
    url_hash = str(hash(url) % 10000000)
    existing = list(output_dir.glob(f"*{url_hash}*.mp4"))
    if existing:
        print(f"[Download] ✅ Found existing: {existing[0].name}")
        return existing[0]

    try:
        subprocess.run(["yt-dlp", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[Download] ❌ yt-dlp not found. pip install yt-dlp")
        return None

    print(f"[Download] ⬇️  Downloading from: {url[:60]}...")
    try:
        cmd = [
            "yt-dlp",
            "-f", "best[height<=720]/best",
            "--no-playlist",
            "-o", str(output_dir / f"video_{url_hash}_%(title).50s_%(id)s.%(ext)s"),
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = sorted(output_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files:
            if f.suffix.lower() in VIDEO_EXTS and f.stat().st_mtime > time.time() - 60:
                print(f"[Download] ✅ Saved: {f.name}")
                return f
        print("[Download] ⚠️  File not found after download.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"[Download] ❌ Failed:\n{e.stderr[:500]}")
        return None


# ── Ollama Vision ─────────────────────────────────────────────────────────────
def _ollama_vision(image_path: Path, model: str) -> dict | None:
    try:
        import requests
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()

        payload = {
            "model": model,
            "prompt": ANALYSIS_PROMPT,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.05, "num_predict": 800},
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        raw = _clean_json_text(raw)

        # Try to find JSON object
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
            if isinstance(data.get("applies_to"), str):
                data["applies_to"] = [data["applies_to"].upper()]
            # Validate structure
            if "pattern" not in data:
                data["pattern"] = "none"
            if "confidence" not in data:
                data["confidence"] = 0.1
            if "bias" not in data:
                data["bias"] = "neutral"
            return data
    except json.JSONDecodeError as jde:
        print(f"[Vision] JSON parse error: {jde}")
    except Exception as exc:
        print(f"[Vision] Ollama error: {exc}")
    return None


def _pil_basic(image_path: Path) -> dict:
    try:
        from PIL import Image
        img = Image.open(image_path)
        w, h = img.size
        mode = img.mode
        
        # Advanced color analysis for schematic detection
        if mode == "RGB":
            pixels = list(img.getdata())
            total = len(pixels)
            greenish = sum(1 for r, g, b in pixels if g > r + 20 and g > b)
            reddish = sum(1 for r, g, b in pixels if r > g + 20 and r > b)
            
            green_ratio = greenish / total
            red_ratio = reddish / total
            
            if green_ratio > 0.15:
                bias = "bullish"
            elif red_ratio > 0.15:
                bias = "bearish"
            else:
                bias = "neutral"
        else:
            bias = "neutral"
            
        return {
            "pattern": "none",
            "bias": bias,
            "key_levels": [],
            "instruction": f"PIL fallback ({w}x{h}, bias:{bias}).",
            "confidence": 0.15,
            "applies_to": ["NONE"],
            "tags": ["pil_fallback"],
        }
    except ImportError:
        return {
            "pattern": "none",
            "bias": "neutral",
            "key_levels": [],
            "instruction": "No vision library available.",
            "confidence": 0.0,
            "applies_to": ["NONE"],
            "tags": ["no_vision_library"],
        }


# ── ENHANCED Smart Frame Selection ────────────────────────────────────────────
def _extract_smart_frames(video_path: Path, max_frames: int = 20,
                          similarity_threshold: float = 0.85) -> list[Path]:
    """
    Extracts frames with content detection:
    - Skips black/intro frames
    - Skips duplicate frames  
    - Prefers frames with structural content (lines, text, charts)
    """
    frames = []
    try:
        import cv2
        import numpy as np
        
        cap = cv2.VideoCapture(str(video_path))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = total / fps if fps > 0 else 0

        print(f"[Video] Duration: {duration:.0f}s | Total frames: {total} | FPS: {fps:.0f}")

        if total <= 0:
            cap.release()
            return frames

        frame_dir = PROCESSED_DIR / f"_frames_{video_path.stem}"
        frame_dir.mkdir(exist_ok=True)

        prev_hist = None
        saved = 0
        check_interval = max(1, total // (max_frames * 8))  # Check more frames
        
        frame_scores = []  # (score, frame_idx, frame_data, timestamp)

        for i in range(0, total, check_interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                continue

            # Skip near-black frames (intros/outros)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean_brightness = np.mean(gray)
            if mean_brightness < 25:  # Too dark
                continue

            # Content score: edges + colors = more likely to have chart info
            edges = cv2.Canny(gray, 50, 150)
            edge_score = np.sum(edges > 0) / (gray.shape[0] * gray.shape[1])
            
            # Color variance (charts have more color variety than static scenes)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            color_variance = np.std(hsv[:,:,1])  # Saturation variance
            
            content_score = edge_score * 100 + color_variance * 0.1

            # Histogram for similarity
            small = cv2.resize(frame, (320, 180))
            gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray_small], [0], None, [32], [0, 256])
            cv2.normalize(hist, hist)

            # Check similarity with last saved
            if prev_hist is not None:
                similarity = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if similarity > similarity_threshold:
                    continue

            timestamp_sec = i / fps if fps > 0 else 0
            frame_scores.append((content_score, i, frame, timestamp_sec, hist))
            prev_hist = hist

        # Sort by content score and take top frames
        frame_scores.sort(key=lambda x: x[0], reverse=True)
        
        for idx, (score, frame_idx, frame, timestamp_sec, _) in enumerate(frame_scores[:max_frames]):
            out = frame_dir / f"frame_{idx:03d}_at_{timestamp_sec:05.1f}s.jpg"
            cv2.imwrite(str(out), frame)
            frames.append(out)
            print(f"[Video] Frame {idx+1}: t={timestamp_sec:.0f}s, content_score={score:.1f}")

        cap.release()
        frames.sort(key=lambda p: float(re.search(r'at_([\d.]+)s', p.name).group(1)))
        print(f"[Video] ✅ Extracted {len(frames)} high-content frames.")
    except ImportError:
        print("[Video] ❌ OpenCV not installed. pip install opencv-python")
    except Exception as exc:
        print(f"[Video] Error: {exc}")
    return frames


# ── Legacy frame extraction ───────────────────────────────────────────────────
def _extract_video_frames(video_path: Path, max_frames: int = 20) -> list[Path]:
    frames = []
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = total / fps if fps > 0 else 0

        print(f"[Video] Duration: {duration:.0f}s | Frames: {total} | FPS: {fps:.0f}")

        if total <= 0:
            cap.release()
            return frames

        step = max(1, total // max_frames)
        frame_dir = PROCESSED_DIR / f"_frames_{video_path.stem}"
        frame_dir.mkdir(exist_ok=True)

        for i in range(max_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(i * step, total - 1))
            ret, frame = cap.read()
            if not ret:
                break
            out = frame_dir / f"frame_{i:03d}.jpg"
            cv2.imwrite(str(out), frame)
            frames.append(out)
        cap.release()
        print(f"[Video] Extracted {len(frames)} frames.")
    except ImportError:
        print("[Video] ❌ OpenCV not installed. pip install opencv-python")
    except Exception as exc:
        print(f"[Video] Error: {exc}")
    return frames


# ── Learnings persistence ─────────────────────────────────────────────────────
def _load_learnings() -> dict:
    if LEARNINGS_FILE.exists():
        try:
            return json.loads(LEARNINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"learnings": [], "rule_counter": 0}


def _save_learnings(data: dict):
    LEARNINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _save_instructions(learnings: list[dict]):
    rules = []
    for item in learnings:
        analysis = item.get("analysis", {})
        if not analysis:
            continue
        # Lower threshold for educational videos (schematics can be valuable)
        if analysis.get("confidence", 0) < 0.15:
            continue
        if analysis.get("applies_to") == ["NONE"] and analysis.get("confidence", 0) < 0.3:
            continue
            
        rules.append({
            "id":           item["id"],
            "source":       item.get("source_file", ""),
            "source_url":   item.get("source_url", ""),
            "learned_at":   item.get("timestamp", ""),
            "instruction":  analysis.get("instruction", ""),
            "bias":         analysis.get("bias", "neutral"),
            "key_levels":   analysis.get("key_levels", []),
            "confidence":   analysis.get("confidence", 0.5),
            "applies_to":   analysis.get("applies_to", ["BOTH"]),
            "pattern":      analysis.get("pattern", ""),
            "tags":         analysis.get("tags", []),
            "active":       True,
        })

    instructions = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "rule_count":   len(rules),
        "rules":        rules,
    }
    INSTRUCTIONS_FILE.write_text(
        json.dumps(instructions, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return instructions


# ── Process a single file ─────────────────────────────────────────────────────
def process_file(file_path: Path, model: str, source_url: str = "",
                 max_frames: int = 20, smart: bool = True) -> dict | None:
    suffix = file_path.suffix.lower()
    analyses = []
    frame_details = []

    if suffix in IMAGE_EXTS:
        print(f"[Vision] 🖼️  Analyzing image: {file_path.name}")
        result = _ollama_vision(file_path, model)
        if result is None:
            result = _pil_basic(file_path)
        analyses.append(result)
        frame_details.append({"frame": "image", "analysis": result})

    elif suffix in VIDEO_EXTS:
        print(f"[Vision] 🎬 Analyzing video: {file_path.name}")
        if smart:
            frames = _extract_smart_frames(video_path=file_path, max_frames=max_frames)
        else:
            frames = _extract_video_frames(video_path=file_path, max_frames=max_frames)

        if not frames:
            print(f"[Vision] ⚠️  No frames extracted.")
            return None

        for idx, frame in enumerate(frames, 1):
            print(f"[Vision] Frame {idx}/{len(frames)}...", end=" ")
            r = _ollama_vision(frame, model)
            if r is None:
                r = _pil_basic(frame)
                print("PIL fallback")
            else:
                conf = r.get("confidence", 0)
                pat = r.get("pattern", "none")
                bias = r.get("bias", "neutral")
                print(f"OK (conf: {conf:.0%}, pattern: {pat}, bias: {bias})")
            analyses.append(r)
            frame_details.append({
                "frame_index": idx,
                "frame_path": str(frame.name),
                "analysis": r
            })
    else:
        print(f"[Vision] ⏭️  Skipping unsupported: {file_path.name}")
        return None

    if not analyses:
        return None

    # Smart merging: weight by confidence
    valid_analyses = [a for a in analyses if a.get("confidence", 0) > 0.15]
    if not valid_analyses:
        valid_analyses = analyses

    # Weighted bias selection
    bias_scores = {"bullish": 0, "bearish": 0, "neutral": 0}
    for a in valid_analyses:
        conf = a.get("confidence", 0.5)
        bias = a.get("bias", "neutral")
        bias_scores[bias] += conf
    merged_bias = max(bias_scores, key=bias_scores.get)

    avg_conf = sum(a.get("confidence", 0.5) for a in valid_analyses) / len(valid_analyses)

    all_levels = sorted(set(
        float(lv) for a in valid_analyses for lv in a.get("key_levels", [])
        if isinstance(lv, (int, float)) and 1800 <= float(lv) <= 3500
    ))

    all_tags = list(set(t for a in valid_analyses for t in a.get("tags", [])))
    applies_to = list(set(s for a in valid_analyses for s in a.get("applies_to", ["BOTH"])))
    
    # Best instruction: highest confidence with actual content
    instructions = [
        (a.get("instruction", ""), a.get("confidence", 0))
        for a in valid_analyses
        if a.get("instruction") and a.get("instruction") != "None" and len(a.get("instruction", "")) > 15
    ]
    best_instr = ""
    if instructions:
        best_instr = max(instructions, key=lambda x: x[1])[0]
    elif instructions:
        best_instr = max([i[0] for i in instructions], key=len)

    patterns = [a.get("pattern", "none") for a in valid_analyses if a.get("pattern", "none") != "none"]
    best_pattern = patterns[0] if patterns else "none"

    return {
        "bias":        merged_bias,
        "confidence":  round(avg_conf, 3),
        "key_levels":  all_levels[:10],
        "instruction": best_instr,
        "applies_to":  applies_to,
        "tags":        all_tags,
        "pattern":     best_pattern,
        "frame_count": len(analyses),
        "frame_details": frame_details,
        "source_url":  source_url,
    }


def _record_learning(file_path: Path, analysis: dict, data: dict) -> dict:
    data["rule_counter"] = data.get("rule_counter", 0) + 1
    rule_id = f"rule_{data['rule_counter']:04d}"

    learning_record = {
        "id":          rule_id,
        "source_file": file_path.name,
        "source_url":  analysis.get("source_url", ""),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "analysis":    analysis,
    }
    data["learnings"].append(learning_record)
    _save_learnings(data)

    instructions = _save_instructions(data["learnings"])

    print(f"\n{'='*60}")
    print(f"✅ [{rule_id}] ANALYSIS COMPLETE")
    print(f"{'='*60}")
    print(f"   Source:       {file_path.name}")
    print(f"   URL:          {analysis.get('source_url', 'local file')}")
    print(f"   Bias:         {analysis['bias']}")
    print(f"   Pattern:      {analysis.get('pattern', '—')}")
    print(f"   Instruction:  {analysis['instruction'][:120]}...")
    print(f"   Confidence:   {analysis['confidence']:.1%}")
    print(f"   Key Levels:   {analysis['key_levels'][:5]}")
    print(f"   Applies to:   {analysis['applies_to']}")
    print(f"   Frames:       {analysis.get('frame_count', 1)}")
    print(f"   Active Rules: {instructions['rule_count']}")
    print(f"{'='*60}")

    dest = PROCESSED_DIR / file_path.name
    if dest.exists():
        dest = PROCESSED_DIR / f"{file_path.stem}_{int(time.time())}{file_path.suffix}"
    shutil.move(str(file_path), str(dest))
    print(f"   → Moved to: {dest.name}")
    return data


# ── Interactive Input ─────────────────────────────────────────────────────────
def ask_user_for_input() -> str:
    print("\n" + "="*60)
    print("🎥 FRIDAY VISION RESEARCHER — Interactive Mode")
    print("="*60)
    print("Enter one of the following:")
    print("  • Video URL (YouTube, Twitter, TikTok, Instagram, etc.)")
    print("  • Local file path (e.g. C:\\Videos\\chart.mp4)")
    print("  • Press Enter to watch inbox/ folder instead")
    print("-"*60)
    user_input = input("🔗 Enter video URL or path: ").strip()
    return user_input


# ── Main researcher loop ──────────────────────────────────────────────────────
def run_researcher(interval: int = 30, model: str = VISION_MODEL,
                   user_input: str | None = None, max_frames: int = 20,
                   smart: bool = True):
    print("=" * 60)
    print("🔬 FRIDAY VISION RESEARCHER")
    print("=" * 60)
    print(f"   Inbox:      {INBOX_DIR}")
    print(f"   Model:      {model}")
    print(f"   Frames:     {max_frames}")
    print(f"   Smart Mode: {'ON' if smart else 'OFF'}")
    print(f"   Interval:   {interval}s")
    print("-" * 60)

    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        has_ollama = any(model in m for m in models)
        print(f"   Ollama: {'✓ available (' + model + ')' if has_ollama else '✗ not found — PIL fallback'}")
    except Exception:
        print("   Ollama: ✗ not reachable — PIL fallback")

    data = _load_learnings()

    if user_input is None:
        user_input = ask_user_for_input()

    if user_input:
        video_path = None
        source_url = ""

        if is_url(user_input):
            source_url = user_input
            print(f"\n🌐 URL detected: {user_input}")
            video_path = download_video(user_input, INBOX_DIR)
        elif Path(user_input).exists():
            local_path = Path(user_input)
            print(f"\n📁 Local file: {local_path}")
            dest = INBOX_DIR / local_path.name
            shutil.copy2(str(local_path), str(dest))
            video_path = dest
        else:
            print(f"\n❌ Not found: {user_input}")
            return

        if video_path:
            try:
                analysis = process_file(
                    video_path, model,
                    source_url=source_url,
                    max_frames=max_frames,
                    smart=smart
                )
                if analysis:
                    data = _record_learning(video_path, analysis, data)
                    print(f"\n💾 Full details: {LEARNINGS_FILE}")
                    print(f"📋 Active rules: {INSTRUCTIONS_FILE}")
                else:
                    print("[Vision] ⚠️  Could not analyze.")
            except Exception as exc:
                print(f"[Vision] Error: {exc}")
        else:
            print("[Download] ❌ Failed.")
        print("\n🏁 Done.")
        return

    # ── Folder Watch Mode ─────────────────────────────────────────────────────
    print("\n👁️  Watching folder. Ctrl+C to stop.\n")
    while True:
        inbox_files = [f for f in INBOX_DIR.iterdir()
                       if f.is_file() and f.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS]

        for file_path in inbox_files:
            try:
                analysis = process_file(file_path, model, max_frames=max_frames, smart=smart)
                if analysis is None:
                    continue
                data = _record_learning(file_path, analysis, data)
            except Exception as exc:
                print(f"[Vision] Error: {exc}")

        if not inbox_files:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"\r[{ts}] Watching ({len(data['learnings'])} learnings) ...", end="", flush=True)

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="FRIDAY Vision Researcher")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--model", type=str, default=VISION_MODEL)
    parser.add_argument("--url", type=str, default=None, help="Direct URL")
    parser.add_argument("--file", type=str, default=None, help="Direct local file path")
    parser.add_argument("--frames", type=int, default=20, help="Number of frames to analyze (default: 20)")
    parser.add_argument("--no-smart", action="store_true", help="Disable smart frame selection")
    args = parser.parse_args()

    user_input = None
    if args.url:
        user_input = args.url
    elif args.file:
        user_input = args.file

    try:
        run_researcher(
            interval=args.interval,
            model=args.model,
            user_input=user_input,
            max_frames=args.frames,
            smart=not args.no_smart
        )
    except KeyboardInterrupt:
        print("\n🛑 Stopped.")


if __name__ == "__main__":
    main()