#!/usr/bin/env python3
"""
Optional: download all videos from a public Instagram profile into ./videos
using instaloader.

    python download_reels.py nolan.vader --out ./videos --limit 30

Notes:
- Instagram heavily rate-limits anonymous access. For more than a handful of
  posts you will almost certainly need to log in once:
      python download_reels.py nolan.vader --login YOUR_OWN_USERNAME
  It will prompt for your password, save a session file, and reuse it after.
- Go slow (use --limit) to avoid temporary blocks.
- Only use this on content you have the right to access, and respect
  Instagram's Terms of Service.
- instaloader's exact output filenames vary by version; analyze_reels.py just
  scans the folder for any video file, so they will be picked up regardless.
"""

import argparse
from pathlib import Path

import instaloader


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("username", help="target profile, e.g. nolan.vader")
    ap.add_argument("--out", default="./videos")
    ap.add_argument("--limit", type=int, default=0, help="0 = all videos")
    ap.add_argument("--login", default="", help="YOUR own IG username (optional)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    L = instaloader.Instaloader(
        dirname_pattern=str(out),
        save_metadata=False,
        download_comments=False,
        post_metadata_txt_pattern="",
        download_video_thumbnails=False,
    )

    if args.login:
        try:
            L.load_session_from_file(args.login)
        except FileNotFoundError:
            L.interactive_login(args.login)  # asks for password
            L.save_session_to_file()

    profile = instaloader.Profile.from_username(L.context, args.username)
    print(f"Downloading videos from @{args.username} ...")

    count = 0
    for post in profile.get_posts():
        if not post.is_video:
            continue
        L.download_post(post, target=args.username)
        count += 1
        print(f"  downloaded {count}")
        if args.limit and count >= args.limit:
            break

    print(f"\nDone. {count} videos -> {out.resolve()}")


if __name__ == "__main__":
    main()
