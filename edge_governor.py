"""edge_governor.py — 🩺 مُعالِج الحافّة: «ما نقتل — نعالج» (أمر المستخدم 2026-07-15).

الفلسفة (نسخة 2 — كانت تقاعداً نهائياً): أيّ محرّك دخولٍ ينزف يتجاوز أرضيّة الخسارة
لا يُقتَل — يُعطى **استراحةً علاجيّة مؤقّتة** (enabled=false + موعد إفاقة) ثم يُعاد
للميدان تلقائياً. تكرار النزيف ⇒ استراحة أطول (سُلّم 6س → 12س → 24س كحدّ أقصى)،
لكنّه يعود دائماً — جميع العملات تبقى مغطّاة، ولا محرّك يُقصى للأبد.

يقرأ الصافي الحقيقيّ لكل ماجيك من desk_scoreboard.json (المحسوب من history_deals
الفعليّ) ويكتب العلاج في ملفّ إعداد المحرّك نفسه (المحرّكات تقرأ enabled كلّ دورة
فتخمد وتفيق بلا قتل عمليّة ولا لمس الوصيّ).

جدرانٌ صارمة:
  • قراءة/كتابة ملفّات فقط — لا MT5، لا أوامر، لا تداول.
  • علاجٌ مؤقّت دائماً: revive_at إلزاميّ مع كلّ استراحة، والإفاقة تلقائيّة.
  • احترام التثبيت اليدويّ: gov_override=true في إعداد المحرّك ⇒ لا يُلمَس أبداً.
  • بياناتٌ بائتة (السبّورة أقدم من stale_s) ⇒ لا حكم.
  • magic 0 (يد المستخدم/الخارجيّ) لا يُحكَم أبداً.

الأرضيّتان (كلاهما يبدأ الاستراحة):
  • ليّنة: net_3d ≤ net_floor_3d  مع  n_today ≥ min_n_today.
  • صلبة: net_3d ≤ net_floor_3d_hard مهما كان العدد.

يكتب: edge_governor_status.json (نبض) + edge_governor_ledger.json (سجلّ علاج/إفاقة).
إيقافه: enabled=false في edge_governor_config.json (أو kill_switch العامّ).
"""
from __future__ import annotations
import json, os, sys, time
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
LEDGER_F = os.path.join(_RN, "edge_governor_ledger.json")
KILL1    = os.path.join(_RN, "kill_switch.txt")
KILL2    = os.path.join(_BASE, "kill_switch.txt")

# ماجيك ⇒ ملفّ إعداده. محرّكات الدخول التي تقرأ enabled كلّ دورة وتكتب إعدادها
# عند الغياب فقط (تحقّقنا: قيَمنا تثبت وتُحترم).
DEFAULT_GOVERNED = {
    "20260701": os.path.join("data", "r_native", "gold_sentinel_config.json"),
    "20260703": os.path.join("data", "r_native", "radhi_mimic_config.json"),
    "20260706": os.path.join("data", "r_native", "brain_trader_config.json"),
    "20260714": os.path.join("data", "r_native", "boundary_pilot_config.json"),
    "20260709": "level_sentinel_multi_config.json",
    "20260716": os.path.join("data", "r_native", "fabio_orb_config.json"),
}

DEFAULTS = {
    "enabled": True,
    "net_floor_3d": -20.0,        # ليّنة: صافي 3أيام ≤ هذا مع صفقاتٍ كافية ⇒ استراحة
    "net_floor_3d_hard": -40.0,   # صلبة: ≤ هذا مهما كان العدد ⇒ استراحة
    "min_n_today": 10,
    "rest_hours_base": 6.0,       # أوّل استراحة 6س، تتضاعف مع التكرار
    "rest_hours_max": 24.0,       # سقف الاستراحة — يعود دائماً خلال يوم
    "loop_s": 60,                 # ⚡ دورة أسرع (كانت 120)
    "stale_s": 900,
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
        _atomic_write(CFG_F, DEFAULTS)
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
    _atomic_write(LEDGER_F, led[-800:])


def _cfg_path(rel):
    return rel if os.path.isabs(rel) else os.path.join(_BASE, rel)


def _revive_pass(governed):
    """🌅 الإفاقة: أيّ محرّك عالجناه وحان موعده ⇒ enabled=true ويعود للميدان."""
    revived = []
    now = time.time()
    for mstr, rel in governed.items():
        ec = _read_json(_cfg_path(rel))
        if not isinstance(ec, dict):
            continue
        if ec.get("treated_by") != "edge_governor" or ec.get("enabled", True):
            continue
        try:
            at = datetime.fromisoformat(str(ec.get("gov_revive_at"))).timestamp()
        except Exception:
            at = 0            # علاجٌ بلا موعد (نسخة قديمة) ⇒ أفِقه الآن
        if now >= at:
            ec["enabled"] = True
            ec.pop("gov_revive_at", None)
            ec["revived_at"] = _now_iso()
            if _atomic_write(_cfg_path(rel), ec):
                revived.append(int(mstr))
                _append_ledger({"action": "revive", "magic": int(mstr), "ts": _now_iso()})
                print(f"[revive] 🌅 أفقت {mstr} — يعود للميدان (علاجات سابقة: "
                      f"{ec.get('gov_treatments', 0)})")
    return revived


def _treat(magic, rel, row, cfg):
    """🩺 الاستراحة العلاجيّة: enabled=false + موعد إفاقة متدرّج — أبداً ليست نهائيّة."""
    full = _cfg_path(rel)
    ec = _read_json(full)
    if not isinstance(ec, dict):
        print(f"[treat] ⚠ إعداد مفقود لـ {magic}: {full} — تخطّي")
        return False
    if ec.get("gov_override") is True:
        return False                      # تثبيتٌ يدويّ صريح — لا نلمسه
    if ec.get("enabled", True) is False:
        return False                      # يستريح أصلاً / مُطفأ يدوياً
    n_prev = int(ec.get("gov_treatments", 0) or 0)
    hours = min(float(cfg["rest_hours_max"]),
                float(cfg["rest_hours_base"]) * (2 ** n_prev))
    revive_at = datetime.fromtimestamp(time.time() + hours * 3600, timezone.utc)
    ec["enabled"] = False
    ec["treated_by"] = "edge_governor"
    ec["gov_treatments"] = n_prev + 1
    ec["gov_revive_at"] = revive_at.isoformat()
    ec["treated_reason"] = (f"net_3d={row.get('net_3d')} n_today={row.get('n_today')} "
                            f"(ليّنة {cfg['net_floor_3d']} / صلبة {cfg['net_floor_3d_hard']}) "
                            f"⇒ استراحة {hours:g}س")
    if not _atomic_write(full, ec):
        return False
    _append_ledger({"action": "rest", "magic": int(magic), "name": row.get("name", str(magic)),
                    "net_3d": row.get("net_3d"), "n_today": row.get("n_today"),
                    "hours": hours, "revive_at": ec["gov_revive_at"], "ts": _now_iso()})
    print(f"[treat] 🩺 استراحة {magic} ({row.get('name')}) لمدّة {hours:g}س: "
          f"{ec['treated_reason']}")
    return True


def governor_pass(cfg):
    """دورةٌ واحدة: أفِق مَن حان موعده، ثم عالِج النازف. يعيد ملخّص الحالة."""
    revived = _revive_pass(cfg["governed"])

    board = _read_json(BOARD_F)
    if not isinstance(board, dict) or "magics" not in board:
        return {"ok": False, "reason": "no_board", "treated_now": [],
                "revived_now": revived, "watching": []}
    age = time.time() - float(board.get("updated", 0) or 0)
    if age > float(cfg["stale_s"]):
        return {"ok": False, "reason": f"stale_board_{int(age)}s", "treated_now": [],
                "revived_now": revived, "watching": []}

    rows = {int(r["magic"]): r for r in board.get("magics", []) if "magic" in r}
    floor = float(cfg["net_floor_3d"])
    hard = float(cfg["net_floor_3d_hard"])
    min_n = int(cfg["min_n_today"])

    treated_now, watching = [], []
    for mstr, rel in cfg["governed"].items():
        try:
            m = int(mstr)
        except Exception:
            continue
        if m == 0:
            continue
        row = rows.get(m)
        if not row:
            continue
        net3d = float(row.get("net_3d", 0.0))
        n_today = int(row.get("n_today", 0))
        breach = (net3d <= floor and n_today >= min_n) or (net3d <= hard)
        watching.append({"magic": m, "name": row.get("name"), "net_3d": net3d,
                         "n_today": n_today, "breach": breach})
        if breach and _treat(m, rel, row, cfg):
            treated_now.append({"magic": m, "name": row.get("name"),
                                "net_3d": net3d, "n_today": n_today})
    return {"ok": True, "reason": "", "treated_now": treated_now,
            "revived_now": revived, "watching": watching, "board_age_s": int(age)}


def main():
    print(f"\n[edge_governor] بدء {_now_iso()} — 🩺 مُعالِج لا قاتل (ملفّات فقط، لا تداول)")
    while True:
        t0 = time.time()
        cfg = _load_cfg()
        try:
            if os.path.exists(KILL1) or os.path.exists(KILL2):
                res = {"ok": False, "reason": "kill_switch", "treated_now": [],
                       "revived_now": [], "watching": []}
            elif not cfg.get("enabled", True):
                res = {"ok": False, "reason": "disabled", "treated_now": [],
                       "revived_now": [], "watching": []}
            else:
                res = governor_pass(cfg)
        except Exception as e:
            import traceback
            print(f"[loop] خطأ: {e}\n{traceback.format_exc()}")
            res = {"ok": False, "reason": "error", "treated_now": [],
                   "revived_now": [], "watching": []}
        _atomic_write(STATUS_F, {
            "ts": time.time(), "iso": _now_iso(), "mode": "healer",
            "net_floor_3d": cfg["net_floor_3d"], "net_floor_3d_hard": cfg["net_floor_3d_hard"],
            "min_n_today": cfg["min_n_today"], "rest_hours_base": cfg["rest_hours_base"],
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
