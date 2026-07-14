# -*- coding: utf-8 -*-
"""chart_signal_reader.py — قارئ لوحة إشارات بثّ dailytrading.tips للذهب (XAU) بصرياً، بكشف اللون فقط
(محليّ، بلا LLM، بلا OCR). اللوحة جدولٌ ثابت 12 صفّاً: Current Position / Current Trend / 1m..Daily،
خليّةُ القيمة خضراء (Bullish/Buy) أو حمراء (Bearish/Sell).

نلتقط إطاراً (yt-dlp+ffmpeg) → نقصّ عمود الخلايا المُعايَر → نقسمه 12 نطاقاً متساوياً (التخطيط ثابت)
→ كل نطاق: أخضر أم أحمر. الإشارة = الصفّ الأوّل (Current Position) + اتّفاق المؤطّرات (للثقة).

قراءة-فقط، آمن. يُستعمل من youtube_analyst_agent عبر get_signal_from_stream(url)."""
from __future__ import annotations
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

_NOWIN = 0x08000000   # CREATE_NO_WINDOW: يمنع وميض نوافذ الكونسول (yt-dlp/ffmpeg كانت تومض كل ~20ث)

LABELS = ["position", "trend", "1m", "3m", "5m", "15m", "30m", "1H", "2H", "4H", "8H", "Daily"]
TF_KEYS = ["1m", "3m", "5m", "15m", "30m", "1H", "2H", "4H", "8H", "Daily"]
# مُعايَرٌ على تخطيط هذا البثّ بدقّة 1920×1080 (عمود خلايا القيمة + امتداد الجدول العموديّ)
CELL_X = (1444, 1496)
TABLE_Y = (600, 828)


def grab_frame(url, out_png, timeout=120):
    """يلتقط إطاراً واحداً من البثّ الحيّ. يرجع True عند النجاح."""
    try:
        g = subprocess.run(["yt-dlp", "-g", "-f", "bestvideo[height=1080]/bestvideo[height<=1080]/best", url],
                           capture_output=True, text=True, timeout=90, creationflags=_NOWIN)
        lines = [l for l in g.stdout.strip().splitlines() if l.strip()]
        media = lines[-1] if lines else ""
        if not media:
            return False
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", media, "-frames:v", "1", "-q:v", "2", out_png],
                       capture_output=True, timeout=timeout, creationflags=_NOWIN)
        return Path(out_png).exists() and Path(out_png).stat().st_size > 5000
    except Exception:
        return False


def read_panel(png):
    """يقرأ الـ12 صفّاً ⇒ {label: 'bull'|'bear'|None}. None إن تعذّر الكشف."""
    try:
        a = np.asarray(Image.open(png).convert("RGB"))
    except Exception:
        return None
    if a.shape[0] < TABLE_Y[1] or a.shape[1] < CELL_X[1]:
        return None
    sub = a[TABLE_Y[0]:TABLE_Y[1], CELL_X[0]:CELL_X[1]]
    R, G, B = sub[:, :, 0].astype(int), sub[:, :, 1].astype(int), sub[:, :, 2].astype(int)
    green = (G > 100) & (G - R > 35) & (G - B > 25)
    red = (R > 110) & (R - G > 45) & (R - B > 25)
    colored = green | red
    ys = np.where(colored.sum(axis=1) > 8)[0]
    if len(ys) < 20:
        return None
    ytop = int(ys.min())            # أعلى الجدول (خليّة Current Position) — ثابتٌ في تخطيط البثّ
    PITCH = 18.0                     # مُعايَر: 6 صفوف بين y=609 و y=717 ⇒ 18px/صفّ (نتجاهل ybot المتلوّث بالأفاتار)
    rows = {}
    for i, lbl in enumerate(LABELS):
        cy = ytop + i * PITCH + PITCH / 2.0          # مركز الخليّة (يتجنّب الفجوات وذيل الأفاتار)
        ya = int(cy - 6); yb = int(cy + 6)
        g = int(green[ya:yb].sum()); r = int(red[ya:yb].sum())
        rows[lbl] = None if (g + r) < 15 else ("bull" if g > r else "bear")
    return rows


def signal_from_panel(rows):
    """الإشارة المنظَّمة من الجدول: اتجاه + اتّفاق المؤطّرات (ثقة)."""
    if not rows or not rows.get("position"):
        return None
    pos = rows["position"]
    tf = [rows[k] for k in TF_KEYS if rows.get(k)]
    bulls = tf.count("bull"); bears = tf.count("bear")
    agree = bulls if pos == "bull" else bears
    return {"direction": "buy" if pos == "bull" else "sell",
            "trend": rows.get("trend"),
            "mtf_bull": bulls, "mtf_bear": bears, "agree": agree, "total": len(tf),
            "rows": rows}


def get_signal_from_stream(url, tmp_png):
    """التقاط + قراءة ⇒ إشارة منظَّمة أو None."""
    if not grab_frame(url, tmp_png):
        return None
    return signal_from_panel(read_panel(tmp_png))


# ── قراءة خطّة القناة الصريحة (Entry/SL/TP1/TP2/TP3) من ملصقات الشارت عبر OCR ──
import re as _re
_LABEL_X = (1030, 1335)        # شريط ملصقات المستويات (يمين الشارت) — مُعايَر على 1920×1080
_LABEL_Y = (115, 910)
_OCR = None


def _ocr_engine():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def read_levels(png):
    """يقرأ ملصقات القناة عبر OCR ⇒ {'Entry':..,'SL':..,'TP1':..,'TP2':..,'TP3':..} أو None."""
    try:
        im = Image.open(png).convert("RGB")
        tp = str(png) + ".labels.png"
        im.crop((_LABEL_X[0], _LABEL_Y[0], _LABEL_X[1], _LABEL_Y[1])).save(tp)
        res, _ = _ocr_engine()(tp)
    except Exception:
        return None
    lv = {}
    for item in (res or []):
        m = _re.match(r"\s*(SL|Entry|TP1|TP2|TP3)\b\D*([0-9]{2,7}\.?[0-9]*)", str(item[1]))
        if m:
            try:
                lv[m.group(1)] = float(m.group(2))
            except Exception:
                pass
    return lv or None


def plan_from_levels(lv, ref_price=None):
    """يحوّل المستويات لخطّةٍ متّسقة + يتحقّق من منطقيّتها. يرجع dict أو None.
       الاتجاه من العلاقة: الوقف فوق الدخول ⇒ بيع، تحته ⇒ شراء."""
    if not lv or "Entry" not in lv or "SL" not in lv or "TP1" not in lv:
        return None
    entry, sl = lv["Entry"], lv["SL"]
    if entry <= 0 or sl <= 0 or abs(sl - entry) < 1e-9:
        return None
    direction = "sell" if sl > entry else "buy"
    tps = [lv[k] for k in ("TP1", "TP2", "TP3") if k in lv]
    if direction == "sell":
        tps = sorted([t for t in tps if t < entry], reverse=True)   # الأقرب أولاً
    else:
        tps = sorted([t for t in tps if t > entry])
    if not tps:
        return None
    # 🛡️ تحقّق النطاق: قريبٌ من السعر المرجعيّ (وإلا قراءةٌ خاطئة) + الوقف معقول (≤2% من الدخول)
    if ref_price and abs(entry - ref_price) / ref_price > 0.05:
        return None
    if abs(sl - entry) / entry > 0.02:
        return None
    return {"direction": direction, "entry": round(entry, 3), "sl": round(sl, 3),
            "tps": [round(t, 3) for t in tps]}


def get_plan_from_stream(url, frame_png, ref_price=None):
    """التقاط + قراءة اللوحة (الاتجاه/الاتّفاق) + خطّة القناة (Entry/SL/TPs).
       يرجع {'panel': sig, 'plan': plan} (أيّهما قد يكون None)."""
    if not grab_frame(url, frame_png):
        return None
    panel = signal_from_panel(read_panel(frame_png))
    plan = plan_from_levels(read_levels(frame_png), ref_price)
    return {"panel": panel, "plan": plan}


if __name__ == "__main__":
    import sys, json
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/live/3H4IVQejlDE"
    tmp = sys.argv[2] if len(sys.argv) > 2 else "_chart_test.png"
    print(json.dumps(get_plan_from_stream(url, tmp), ensure_ascii=False, indent=1))
