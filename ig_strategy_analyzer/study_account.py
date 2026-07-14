#!/usr/bin/env python3
"""
study_account.py — point it at an Instagram profile and it goes through the
videos one by one: fetches a reel, "watches" it (frames + audio transcript),
understands it with Claude, saves the analysis, DELETES the file, and moves to
the next — then synthesizes everything it learned into a strategy playbook.

    set ANTHROPIC_API_KEY=sk-ant-...
    python study_account.py nolan.vader --login YOUR_USERNAME --limit 20

Nothing is stored long-term: each video is deleted right after it's understood.
What remains is ./out/<id>.json per video, ./out/analyses.json, and
./out/playbook.(json|md).

Reality check: to *understand* a video, its frames + audio must be fetched —
"watching" is fetching the bytes, whether a human's browser or this script does
it. Instagram also blocks anonymous automation, so a login session is required
and the script goes at a throttled pace.
"""

import json
import time
import argparse
import tempfile
from pathlib import Path

import instaloader
from faster_whisper import WhisperModel

# reuse the analysis logic from analyze_reels.py (same folder)
from analyze_reels import (
    extract_frames, transcribe, analyze, client, MODEL, WHISPER_SIZE, LANGUAGE,
)


def _safe(post, attr):
    """instaloader metric properties can raise; return None instead of crashing."""
    try:
        return getattr(post, attr)
    except Exception:
        return None


def build_playbook(analyses):
    """One synthesis pass over all videos -> the recurring strategy of the account."""
    compact = [{
        "hook_type": (a.get("hook") or {}).get("type"),
        "hook_score": (a.get("hook") or {}).get("score"),
        "content_format": (a.get("content") or {}).get("format"),
        "value": (a.get("content") or {}).get("value"),
        "cta_type": (a.get("cta") or {}).get("type"),
        "overall": a.get("overall_strategy"),
    } for a in analyses]

    prompt = (
        f"You studied {len(analyses)} Instagram videos from a single account. "
        f"Here are the per-video summaries:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        "Synthesize what this account CONSISTENTLY does across its videos. "
        "Return ONLY a JSON object (no markdown) with this schema:\n"
        "{\n"
        '  "dominant_hooks": ["hook patterns they rely on, most common first"],\n'
        '  "content_formats": ["formats they favor"],\n'
        '  "cta_patterns": ["how they drive action"],\n'
        '  "what_makes_it_work": ["the core reasons this account performs"],\n'
        '  "recommendations": ["concrete moves we can copy for our own content"]\n'
        "}\n"
        f"Write all text values in {LANGUAGE}. Keep the JSON keys in English."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "{"},  # prefill -> JSON
        ],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    raw = ("{" + text).strip()
    return json.loads(raw[: raw.rfind("}") + 1])


def write_playbook_md(pb, path):
    sections = [
        ("Dominant hooks", "dominant_hooks"),
        ("Content formats", "content_formats"),
        ("CTA patterns", "cta_patterns"),
        ("What makes it work", "what_makes_it_work"),
        ("Recommendations for us", "recommendations"),
    ]
    lines = ["# Strategy Playbook", ""]
    for title, key in sections:
        lines.append(f"## {title}")
        for item in (pb.get(key) or []):
            lines.append(f"- {item}")
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("username", help="target profile, e.g. nolan.vader")
    ap.add_argument("--out", default="./out")
    ap.add_argument("--login", default="",
                    help="YOUR own IG username (needed for more than a few videos)")
    ap.add_argument("--limit", type=int, default=0, help="0 = all videos")
    ap.add_argument("--sleep", type=float, default=2.0,
                    help="pause between videos, seconds (be gentle with IG)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading Whisper ({WHISPER_SIZE})...")
    whisper = WhisperModel(WHISPER_SIZE, device="auto", compute_type="int8")

    L = instaloader.Instaloader(
        save_metadata=False,
        download_comments=False,
        post_metadata_txt_pattern="",
        download_video_thumbnails=False,
        quiet=True,
    )
    if args.login:
        try:
            L.load_session_from_file(args.login)
        except FileNotFoundError:
            L.interactive_login(args.login)  # prompts for password
            L.save_session_to_file()

    profile = instaloader.Profile.from_username(L.context, args.username)
    print(f"Studying @{args.username} — going through the videos one by one...\n")

    results = []
    count = 0
    for post in profile.get_posts():
        if not post.is_video:
            continue

        shortcode = post.shortcode
        per_file = out_dir / f"{shortcode}.json"
        if per_file.exists():  # already learned on a previous run
            results.append(json.loads(per_file.read_text(encoding="utf-8")))
            count += 1
            print(f"[{count}] {shortcode} -> already learned, skipping")
            if args.limit and count >= args.limit:
                break
            continue

        # fetch into a temp dir that is auto-deleted when the block ends
        with tempfile.TemporaryDirectory() as td:
            L.dirname_pattern = td
            try:
                L.download_post(post, target=shortcode)
            except Exception as e:
                print(f"[{count + 1}] {shortcode} -> couldn't fetch ({e})")
                continue

            mp4s = list(Path(td).glob("**/*.mp4"))
            if not mp4s:
                print(f"[{count + 1}] {shortcode} -> no video stream found")
                continue

            try:
                frames, duration = extract_frames(mp4s[0])
                transcript = transcribe(mp4s[0], whisper)
                metrics = {
                    "likes": _safe(post, "likes"),
                    "comments": _safe(post, "comments"),
                    "views": _safe(post, "video_view_count"),
                }
                data = {
                    "video": shortcode,
                    "url": f"https://www.instagram.com/p/{shortcode}/",
                    "duration_sec": round(duration, 1),
                    "metrics": metrics,
                    **analyze(frames, transcript, duration),
                }
                per_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
                results.append(data)
                count += 1
                hook = (data.get("hook") or {}).get("type", "?")
                print(f"[{count}] {shortcode} -> watched & understood "
                      f"(hook: {hook}) — moving on")
            except Exception as e:
                print(f"[{count + 1}] {shortcode} -> analysis error ({e})")
        # the downloaded file is gone here (temp dir deleted)

        if args.limit and count >= args.limit:
            break
        time.sleep(args.sleep)

    if not results:
        print("\nNothing was analyzed — Instagram likely blocked access, or the "
              "profile has no videos. Try --login and a small --limit.")
        return

    (out_dir / "analyses.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nLearned from {len(results)} videos. Building the playbook...")
    try:
        pb = build_playbook(results)
        (out_dir / "playbook.json").write_text(
            json.dumps(pb, ensure_ascii=False, indent=2), encoding="utf-8")
        write_playbook_md(pb, out_dir / "playbook.md")
        print(f"Done -> {out_dir.resolve()}  "
              f"(analyses.json, playbook.json, playbook.md)")
    except Exception as e:
        print(f"Playbook synthesis failed ({e}); per-video analyses are still saved.")


if __name__ == "__main__":
    main()
