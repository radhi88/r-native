"""One-time logo downloader -> assets/logos/<TICKER>.<ext>.

Sources tried in order per ticker (best wins: svg preferred, else largest):
  1. simple-icons via jsdelivr CDN (SVG, recolored #ffffff for dark mode)
  2. vectorlogo.zone icon SVG
  3. apple-touch-icon from the company domain
  4. Google faviconV2 at size=256
  5. DuckDuckGo icons

Run manually:  python scripts/fetch_logos.py
"""
from __future__ import annotations

import pathlib
import re
import sys
import time

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib.logos import ASSETS_DIR, TICKER_DOMAINS  # noqa: E402

TIMEOUT = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (logo-fetcher; personal research app)"}


def _slug(domain: str) -> str:
    return domain.split(".")[0].lower().replace("-", "")


def _get(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:
        pass
    return None


def _candidates(domain: str) -> list[tuple[str, str]]:
    s = _slug(domain)
    return [
        (f"https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/{s}.svg", "svg"),
        (f"https://www.vectorlogo.zone/logos/{s}/{s}-icon.svg", "svg"),
        (f"https://{domain}/apple-touch-icon.png", "png"),
        ("https://t0.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON"
         f"&fallback_opts=TYPE,SIZE,URL&url=https://{domain}&size=256", "png"),
        (f"https://icons.duckduckgo.com/ip3/{domain}.ico", "ico"),
    ]


def _score(data: bytes, ext: str) -> int:
    if len(data) < 1024:          # tiny placeholder — reject
        return -1
    return 1_000_000 + len(data) if ext == "svg" else len(data)


def fetch_one(ticker: str, domain: str) -> str | None:
    best: tuple[int, bytes, str] | None = None
    for url, ext in _candidates(domain):
        data = _get(url)
        if not data:
            continue
        if ext == "svg":
            if b"<svg" not in data[:512]:
                continue
            data = re.sub(rb'fill="#[0-9a-fA-F]{3,8}"', b'fill="#ffffff"', data)
            if b"fill=" not in data:
                data = data.replace(b"<svg ", b'<svg fill="#ffffff" ', 1)
        sc = _score(data, ext)
        if sc > 0 and (best is None or sc > best[0]):
            best = (sc, data, ext)
        if best and best[2] == "svg":
            break                  # svg found — good enough
    if not best:
        return None
    out = ASSETS_DIR / f"{ticker.upper()}.{best[2]}"
    out.write_bytes(best[1])
    return out.name


_MIMES = (".svg", ".png", ".ico", ".jpg", ".jpeg")


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    done = skip = fail = 0
    for i, (ticker, domain) in enumerate(sorted(TICKER_DOMAINS.items()), 1):
        if any((ASSETS_DIR / f"{ticker}{e}").exists() for e in _MIMES):
            skip += 1
            continue
        name = fetch_one(ticker, domain)
        if name:
            done += 1
            print(f"[{i}/{len(TICKER_DOMAINS)}] ✓ {ticker} -> {name}")
        else:
            fail += 1
            print(f"[{i}/{len(TICKER_DOMAINS)}] ✗ {ticker} ({domain})")
        time.sleep(0.2)
    print(f"done={done} skipped={skip} failed={fail} -> {ASSETS_DIR}")


if __name__ == "__main__":
    main()
