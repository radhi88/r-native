# -*- coding: utf-8 -*-
"""engine_gov.py — قارئ مضاعِف حوكمة المايسترو لكل محرّك (مُهدّأ بالـmtime). fail-safe = 1.0
(الملفّ مفقود/تالف/قديم ⇒ بلا أثر). يُستهلَك من المنفّذين كي يخنق المايسترو النزّاف صافي-التكلفة."""
from __future__ import annotations
import json
from pathlib import Path

_F = Path(r"C:\Users\Radhi\MT5\data\r_native\engine_governance.json")
_C = {"mt": -1.0, "m": {}, "paused": set()}


def _refresh():
    mt = _F.stat().st_mtime
    if mt != _C["mt"]:
        d = json.load(open(_F, encoding="utf-8"))
        _C["m"] = d.get("mults", {})
        _C["paused"] = set(int(x) for x in d.get("paused", []))
        _C["mt"] = mt


def gov_mult(magic, lo=0.1, hi=1.5):
    """مضاعِف حوكمة هذا المجيك ضمن [lo, hi]. 1.0 إن غاب الملفّ (آمن)."""
    try:
        _refresh()
        return max(lo, min(hi, float(_C["m"].get(str(magic), 1.0))))
    except Exception:
        return 1.0


def is_paused(magic):
    """🔥 هل أقال المايسترو هذا المحرّك (نزّاف كارثيّ)؟ ⇒ لا يفتح صفقات جديدة (يدير القائم فقط). آمن=False."""
    try:
        _refresh()
        return int(magic) in _C["paused"]
    except Exception:
        return False
