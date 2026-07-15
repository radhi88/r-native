"""edge_governor.py — 🚦 حاكم الحافّة: الإصلاح المنظوميّ للنزيف (طلب المستخدم 2026-07-15).

الفكرة («إصلاح منظوميّ بدل الإيقاف اليدويّ»): بدل أن نلاحق كل محرّك نازف بأيدينا،
هذا الحاكم يقرأ الصافي الحقيقيّ لكل ماجيك من desk_scoreboard.json (المحسوب من
history_deals الفعليّ)، وأيّ محرّك دخولٍ يتجاوز أرضيّة الخسارة بعد عددٍ كافٍ من الصفقات
⇒ يقلب enabled=false في ملفّ إعداده تلقائياً. المحرّكات تقرأ enabled كل دورة ⇒ تخمد
فوراً بلا قتل عمليّة ولا لمس الوصيّ.

جدرانٌ صارمة:
  • قراءة/كتابة ملفّات فقط — لا MT5، لا أوامر، لا تداول. لا يفتح صفقةً أبداً.
  • تقاعدٌ أحاديّ الاتّجاه: لا يُعيد التفعيل تلقائياً (يمنع الرفرفة). الإحياء يدويّ.
  • احترام التثبيت اليدويّ: gov_override=true في إعداد المحرّك ⇒ الحاكم لا يلمسه أبداً.
  • بياناتٌ بائتة (السبّورة أقدم من stale_s) ⇒ لا حكم — لا نُقاعد على معلومةٍ قديمة.
  • magic 0 (يد المستخدم/الخارجيّ) لا يُحكَم أبداً.

الأرضيّتان (كلاهما يحمي):
  • ليّنة: net_3d ≤ net_floor_3d  مع  n_today ≥ min_n_today  (يطابق desk_scoreboard).
  • صلبة: net_3d ≤ net_floor_3d_hard مهما كان العدد (يمسك النازف البطيء العميق).

يكتب: data/r_native/edge_governor_status.json (نبض) + edge_governor_retired.json (سجلّ).
إيقافه: enabled=false في edge_governor_config.json (أو kill_switch العامّ).
"""
from __future__ import annotations
import io, json, os, sys, time
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")

# stdout/stderr → ملفّ (pythonw بلا كونسول)
try:
    os.makedirs(_RN, exist_ok=True)
    _log_f = open(os.path.join(_RN, "edge_governor.out.log"), "a", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = _log_f
    if sys.stderr is None:
        sys.stderr = _log_f
except Exception:
    pass

# قفل مفرد — كباقي المحرّكات (يمنع نسختين تتسابقان على الإعدادات)
try:
    import engine_lock
    engine_lock.claim("edge_governor")
except SystemExit:
    raise
except Exception:
    pass

CFG_F    = os.path.join(_RN, "edge_governor_config.json")
BOARD_F  = os.path.join(_RN, "desk_scoreboard.json")
STATUS_F = os.path.join(_RN, "edge_governor_status.json")
LEDGER_F = os.path.join(_RN, "edge_governor_retired.json")
KILL1    = os.path.join(_RN, "kill_switch.txt")
KILL2    = os.path.join(_BASE, "kill_switch.txt")

# ماجيك ⇒ مسار ملفّ إعداده (نسبةً لجذر MT5). فقط محرّكات الدخول التي تقرأ enabled كل دورة
# وتكتب إعدادها عند الغياب فقط (فتحقّقنا أنّ enabled=false يثبت ويُحترم).
DEFAULT_GOVERNED = {
    "20260701": os.path.join("data", "r_native", "gold_sentinel_config.json"),   # الحارس (gold_level_sentinel)
    "20260703": os.path.join("data", "r_native", "radhi_mimic_config.json"),     # محاكي راضي
    "20260706": os.path.join("data", "r_native", "brain_trader_config.json"),    # R Core (brain_trader)
    "20260714": os.path.join("data", "r_native", "boundary_pilot_config.json"),  # هجوم اللحظات (boundary_pilot)
    "20260709": "level_sentinel_multi_config.json",                              # حارس العملات (جذر MT5)
    "20260716": os.path.join("data", "r_native", "fabio_orb_config.json"),       # نموذج Fabio ORB (fabio_orb)
}

DEFAULTS = {
    "enabled": True,
    "net_floor_3d": -20.0,        # ليّنة: صافي 3أيام ≤ هذا مع صفقاتٍ كافية ⇒ تقاعد
    "net_floor_3d_hard": -40.0,   # صلبة: صافي 3أيام ≤ هذا مهما كان العدد ⇒ تقاعد
    "min_n_today": 10,
    "loop_s": 120,
    "stale_s": 900,               # سبّورة أقدم من هذا ⇒ لا حكم
    "governed": DEFAULT_GOVERNED,
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path, obj):
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[write] فشل {path}: {e}")
        return False


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def _load_cfg():
    cfg = _read_json(CFG_F)
    if not isinstance(cfg, dict):
        _atomic_write(CFG_F, DEFAULTS)   # أنشئه بالقيَم الافتراضيّة عند الغياب
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    out.update(cfg)
    if not isinstance(out.get("governed"), dict) or not out["governed"]:
        out["governed"] = DEFAULT_GOVERNED
    return out


def _append_ledger(entry):
    led = _read_json(LEDGER_F)
    if not isinstance(led, list):
        led = []
    led.append(entry)
    _atomic_write(LEDGER_F, led[-500:])   # نحتفظ بآخر 500 تقاعد


def _retire(magic, cfg_path, row, cfg):
    """يقلب enabled=false في إعداد المحرّك — أحاديّ الاتّجاه، محترمٌ للتثبيت اليدويّ."""
    full = cfg_path if os.path.isabs(cfg_path) else os.path.join(_BASE, cfg_path)
    ec = _read_json(full)
    if not isinstance(ec, dict):
        # لا نُنشئ إعداداً من عدم — قد يكون المسار خطأً؛ نُبلّغ ولا نُصمت
        print(f"[retire] ⚠ إعداد مفقود لـ {magic}: {full} — تخطّي")
        return False
    if ec.get("gov_override") is True:
        return False                       # تثبيتٌ يدويّ صريح — لا نلمسه
    if ec.get("enabled", True) is False:
        return False                       # مُطفأ أصلاً — لا شيء نفعله
    ec["enabled"] = False
    ec["retired_by"] = "edge_governor"
    ec["retired_at"] = _now_iso()
    ec["retired_reason"] = (f"net_3d={row.get('net_3d')} n_today={row.get('n_today')} "
                            f"(أرضيّة ليّنة {cfg['net_floor_3d']} / صلبة {cfg['net_floor_3d_hard']})")
    if not _atomic_write(full, ec):
        return False
    _append_ledger({
        "magic": int(magic), "name": row.get("name", str(magic)),
        "net_3d": row.get("net_3d"), "n_today": row.get("n_today"),
        "ts": _now_iso(), "cfg": full,
    })
    print(f"[retire] 🚦 قوعدت {magic} ({row.get('name')}): {ec['retired_reason']}")
    return True


def governor_pass(cfg):
    """دورةٌ واحدة: يقرأ السبّورة ويُقاعد النازفين المحكومين. يعيد ملخّص الحالة."""
    board = _read_json(BOARD_F)
    if not isinstance(board, dict) or "magics" not in board:
        return {"ok": False, "reason": "no_board", "retired_now": [], "watching": []}
    age = time.time() - float(board.get("updated", 0) or 0)
    if age > float(cfg["stale_s"]):
        return {"ok": False, "reason": f"stale_board_{int(age)}s",
                "retired_now": [], "watching": []}

    rows = {int(r["magic"]): r for r in board.get("magics", []) if "magic" in r}
    floor = float(cfg["net_floor_3d"])
    hard = float(cfg["net_floor_3d_hard"])
    min_n = int(cfg["min_n_today"])

    retired_now, watching = [], []
    for mstr, cfg_path in cfg["governed"].items():
        try:
            m = int(mstr)
        except Exception:
            continue
        if m == 0:                          # اليد/الخارجيّ — لا يُحكَم
            continue
        row = rows.get(m)
        if not row:
            continue                        # لا صفقات لهذا الماجيك بعد ⇒ لا حكم
        net3d = float(row.get("net_3d", 0.0))
        n_today = int(row.get("n_today", 0))
        breach = (net3d <= floor and n_today >= min_n) or (net3d <= hard)
        watching.append({"magic": m, "name": row.get("name"), "net_3d": net3d,
                         "n_today": n_today, "breach": breach})
        if breach and _retire(m, cfg_path, row, cfg):
            retired_now.append({"magic": m, "name": row.get("name"),
                                "net_3d": net3d, "n_today": n_today})
    return {"ok": True, "reason": "", "retired_now": retired_now,
            "watching": watching, "board_age_s": int(age)}


def main():
    print(f"\n[edge_governor] بدء {_now_iso()} — إصلاحٌ منظوميّ (قراءة/كتابة ملفّات فقط، لا تداول)")
    while True:
        t0 = time.time()
        cfg = _load_cfg()
        try:
            if os.path.exists(KILL1) or os.path.exists(KILL2):
                res = {"ok": False, "reason": "kill_switch", "retired_now": [], "watching": []}
            elif not cfg.get("enabled", True):
                res = {"ok": False, "reason": "disabled", "retired_now": [], "watching": []}
            else:
                res = governor_pass(cfg)
        except Exception as e:
            import traceback
            print(f"[loop] خطأ: {e}\n{traceback.format_exc()}")
            res = {"ok": False, "reason": "error", "retired_now": [], "watching": []}
        _atomic_write(STATUS_F, {
            "ts": time.time(), "iso": _now_iso(),
            "net_floor_3d": cfg["net_floor_3d"], "net_floor_3d_hard": cfg["net_floor_3d_hard"],
            "min_n_today": cfg["min_n_today"],
            "governed_magics": sorted(int(k) for k in cfg["governed"]),
            **res,
        })
        elapsed = time.time() - t0
        time.sleep(max(5.0, float(cfg["loop_s"]) - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        print(f"[fatal] {e}\n{traceback.format_exc()}")
