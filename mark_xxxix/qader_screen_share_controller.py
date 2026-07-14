# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import ctypes
import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass
class ScreenSource:
    source_id: str
    label: str
    kind: str
    meta: Dict[str, Any]


def _ollama_host() -> str:
    return os.getenv("JARVIS_OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _vision_model() -> str:
    return os.getenv("JARVIS_OLLAMA_VISION_MODEL", "llava:latest").strip() or "llava:latest"


def _timeout() -> float:
    try:
        return float(os.getenv("JARVIS_OLLAMA_TIMEOUT", "600"))
    except Exception:
        return 600.0


def _safe_window_title(hwnd: int) -> str:
    try:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value.strip()
    except Exception:
        return ""


def _window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    try:
        rect = ctypes.wintypes.RECT()
    except Exception:
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]
        rect = RECT()

    try:
        ok = ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if not ok:
            return None

        left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

        if right <= left or bottom <= top:
            return None

        if right - left < 80 or bottom - top < 80:
            return None

        return left, top, right, bottom
    except Exception:
        return None


def _is_window_visible(hwnd: int) -> bool:
    try:
        return bool(ctypes.windll.user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def _foreground_window() -> Optional[int]:
    try:
        hwnd = int(ctypes.windll.user32.GetForegroundWindow())
        return hwnd if hwnd else None
    except Exception:
        return None


def _enumerate_windows(max_items: int = 80) -> List[ScreenSource]:
    sources: List[ScreenSource] = []

    if os.name != "nt":
        return sources

    try:
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    except Exception:
        return sources

    seen_titles = set()

    def callback(hwnd, _lparam):
        try:
            hwnd_int = int(hwnd)

            if not _is_window_visible(hwnd_int):
                return True

            title = _safe_window_title(hwnd_int)

            if not title:
                return True

            lowered = title.lower()

            if title in seen_titles:
                return True

            if "qader screen control" in lowered:
                return True

            if "program manager" in lowered:
                return True

            rect = _window_rect(hwnd_int)

            if rect is None:
                return True

            left, top, right, bottom = rect
            width = right - left
            height = bottom - top

            seen_titles.add(title)

            label = f"Window: {title[:70]}  [{width}x{height}]"

            sources.append(
                ScreenSource(
                    source_id=f"window:{hwnd_int}",
                    label=label,
                    kind="window",
                    meta={
                        "hwnd": hwnd_int,
                        "title": title,
                        "bbox": [left, top, right, bottom],
                        "width": width,
                        "height": height,
                    },
                )
            )

            if len(sources) >= max_items:
                return False

            return True
        except Exception:
            return True

    try:
        EnumWindows(EnumWindowsProc(callback), 0)
    except Exception:
        pass

    return sources


def list_screen_sources() -> List[ScreenSource]:
    sources: List[ScreenSource] = []

    try:
        import mss

        with mss.mss() as sct:
            monitors = list(sct.monitors or [])

            if monitors:
                full = monitors[0]
                sources.append(
                    ScreenSource(
                        source_id="desktop:all",
                        label=f"Entire Desktop  [{full.get('width')}x{full.get('height')}]",
                        kind="desktop",
                        meta=dict(full),
                    )
                )

            for idx, monitor in enumerate(monitors[1:], start=1):
                sources.append(
                    ScreenSource(
                        source_id=f"monitor:{idx}",
                        label=f"Monitor {idx}  [{monitor.get('width')}x{monitor.get('height')}]",
                        kind="monitor",
                        meta=dict(monitor),
                    )
                )

    except Exception:
        pass

    hwnd = _foreground_window()
    if hwnd:
        title = _safe_window_title(hwnd) or "Foreground Window"
        rect = _window_rect(hwnd)
        if rect:
            left, top, right, bottom = rect
            sources.append(
                ScreenSource(
                    source_id=f"foreground:{hwnd}",
                    label=f"Foreground Window: {title[:55]}",
                    kind="foreground",
                    meta={
                        "hwnd": hwnd,
                        "title": title,
                        "bbox": [left, top, right, bottom],
                        "width": right - left,
                        "height": bottom - top,
                    },
                )
            )

    sources.extend(_enumerate_windows())

    dedup: Dict[str, ScreenSource] = {}

    for item in sources:
        if item.source_id not in dedup:
            dedup[item.source_id] = item

    return list(dedup.values())


def _find_source(source_id: str) -> ScreenSource:
    sources = list_screen_sources()

    for source in sources:
        if source.source_id == source_id:
            return source

    if sources:
        return sources[0]

    raise RuntimeError("No screen sources found.")


def capture_png(source_id: str) -> bytes:
    source = _find_source(source_id)

    try:
        import mss
        import mss.tools
    except Exception as exc:
        raise RuntimeError(f"mss is required. Run: pip install mss. Details: {exc}") from exc

    with mss.mss() as sct:
        if source.kind in {"desktop", "monitor"}:
            monitor = dict(source.meta)
            shot = sct.grab(monitor)
            return mss.tools.to_png(shot.rgb, shot.size)

        if source.kind in {"window", "foreground"}:
            bbox = source.meta.get("bbox")

            if not bbox or len(bbox) != 4:
                raise RuntimeError("Window bounding box not available.")

            left, top, right, bottom = [int(x) for x in bbox]

            monitor = {
                "left": left,
                "top": top,
                "width": max(1, right - left),
                "height": max(1, bottom - top),
            }

            shot = sct.grab(monitor)
            return mss.tools.to_png(shot.rgb, shot.size)

    raise RuntimeError(f"Unsupported screen source: {source.source_id}")


def analyze_source(
    source_id: str,
    prompt: str,
    *,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
) -> str:
    source = _find_source(source_id)
    png = capture_png(source.source_id)

    model = model or _vision_model()
    timeout = timeout or _timeout()

    image_b64 = base64.b64encode(png).decode("ascii")

    full_prompt = (
        f"Screen source: {source.label}\n\n"
        f"{prompt}\n\n"
        "Respond concisely. If you see an error, mention the exact visible error and the next practical action."
    )

    payload = {
        "model": model,
        "prompt": full_prompt,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 2048,
        },
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        f"{_ollama_host()}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        started = time.perf_counter()

        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")

        elapsed = time.perf_counter() - started

        parsed = json.loads(raw)
        result = str(parsed.get("response", "")).strip()

        if not result:
            result = str(parsed).strip()

        return f"{result}\n\n[source={source.label}, model={model}, elapsed={elapsed:.2f}s]"

    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Ollama vision is not reachable. Make sure Ollama is running and the vision model exists. "
            "Run: ollama serve  and  ollama pull llava:latest"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Vision analysis failed: {exc}") from exc


def sources_as_tuples() -> List[Tuple[str, str]]:
    return [(item.source_id, item.label) for item in list_screen_sources()]
