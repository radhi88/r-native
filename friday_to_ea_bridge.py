"""
friday_to_ea_bridge.py — Bridge Swarm Decisions → MT5 EA Live Control

يقرأ:  friday_agents.json  (مخرجات السرب)
يكتب:  claude_live_control.csv  (Live Control الذي يقرأه EA كل 5 ثوانٍ)

طبقات الأمان (Vetoes):
  • قارئ السوق ≥80% + "توقف/خطر"  → lot_factor = 0.25
  • حارس المخاطر ≥70% + "حذر/خطر" → lot_factor ×= 0.5
  • المنسق يقول "تنبيه/خطر"        → confidence = 49 (تحت عتبة EA = 50 → يتجاهل)

التشغيل:
    python friday_to_ea_bridge.py
"""

import json
import time
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────
MT5_COMMON  = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
SWARM_JSON  = MT5_COMMON / "friday_agents.json"
CONTROL_CSV = MT5_COMMON / "claude_live_control.csv"
BRIDGE_LOG  = Path(r"C:\Users\Radhi\MT5\friday_bridge_state.json")

# EA reads exactly 18 fields per row (skips first 18 = header, then reads 18 = data)
HEADER = [
    "epoch", "bar", "action", "confidence", "gap", "tp", "sl",
    "lock_start", "lock_giveback", "secure_start", "secure_lock",
    "modify_step", "lot_factor", "grid_factor",
    "profit_factor", "drawdown_pct", "spread_points", "reason_code",
]

# ── Helpers ───────────────────────────────────────────────────────────────

def find_agent(swarm: dict, role: str):
    for a in swarm.get("agents", []):
        if a.get("role") == role:
            return a
    return None


def clean(text: str, n: int = 40) -> str:
    """Make a string CSV-safe: no commas, no newlines, length-limited."""
    if not text:
        return "-"
    return str(text).replace(",", ";").replace("\n", " ")[:n].strip()


# ── Core synthesis ────────────────────────────────────────────────────────

def synthesize_control(swarm: dict) -> dict:
    """Translate swarm output → Live Control vector for EA."""
    coord = swarm.get("coordinator", {}) or {}
    gap_a = find_agent(swarm, "محلل الفجوة")
    mkt_a = find_agent(swarm, "قارئ السوق")
    risk  = find_agent(swarm, "حارس المخاطر")
    dna   = find_agent(swarm, "مطور الجينات")

    # Start with coordinator's stance
    confidence = int(coord.get("confidence", 0) or 0)
    action     = clean(coord.get("decision", "—"), 30)
    reason     = clean(coord.get("thought", "—"), 50)

    # Default values: 0 = "don't change" (EA ignores 0 for most fields)
    out = {
        "epoch":         int(time.time()),
        "bar":           int(swarm.get("bar_count", 0)),
        "action":        action,
        "confidence":    confidence,
        "gap":           0,
        "tp":            0.0,
        "sl":            0.0,
        "lock_start":    0.0,
        "lock_giveback": 0.0,
        "secure_start":  0.0,
        "secure_lock":   0.0,
        "modify_step":   0,
        "lot_factor":    1.0,
        "grid_factor":   1.0,
        "profit_factor": 0.0,
        "drawdown_pct":  0.0,
        "spread_points": 0.0,
        "reason_code":   reason,
    }

    vetoes = []

    # ── From Gap Analyst → target gap distance ────────────────────────
    if gap_a:
        p = gap_a.get("params") or {}
        if p.get("gap"):
            out["gap"] = max(50, min(1000, int(p["gap"])))

    # ── From DNA Developer → TP / SL targets ──────────────────────────
    if dna:
        p = dna.get("params") or {}
        if p.get("tp"):
            out["tp"] = max(0.5, min(20.0, float(p["tp"])))
        if p.get("sl"):
            out["sl"] = max(1.0, min(50.0, float(p["sl"])))
        if p.get("lock_start"):
            out["lock_start"] = float(p["lock_start"])
        if p.get("lock_giveback"):
            out["lock_giveback"] = float(p["lock_giveback"])

    # ── From Market Reader → spread + RSI ─────────────────────────────
    if mkt_a:
        p = mkt_a.get("params") or {}
        if p.get("atr"):
            # send ATR as advisory; EA can clamp gap relative to it
            pass

    # ═══════════════════════════════════════════════════════════════════
    # SAFETY LAYER — Agent vetoes (these REDUCE risk, never increase it)
    # ═══════════════════════════════════════════════════════════════════

    # 1) Market Reader veto: high-confidence "stop / danger"
    if mkt_a:
        dec = mkt_a.get("decision", "") or ""
        c   = int(mkt_a.get("confidence", 0) or 0)
        if c >= 80 and any(k in dec for k in ("توقف", "خطر", "خطير")):
            out["lot_factor"] = 0.25
            vetoes.append(f"mkt:{c}%")

    # 2) Risk Guardian veto: "caution / danger"
    if risk:
        dec = risk.get("decision", "") or ""
        c   = int(risk.get("confidence", 0) or 0)
        if c >= 70 and any(k in dec for k in ("حذر", "خطر", "خطير", "توقف")):
            out["lot_factor"] *= 0.5
            vetoes.append(f"risk:{c}%")

    # 3) Coordinator alarm: drop below EA's confidence threshold (50)
    if any(k in action for k in ("تنبيه", "إيقاف", "خطر", "توقف")):
        out["confidence"] = 49  # EA skips this row entirely
        vetoes.append("coord-alarm")

    if vetoes:
        out["reason_code"] = clean(f"[{'+'.join(vetoes)}] {reason}", 50)

    out["_vetoes"] = vetoes
    return out


# ── CSV writer (matches EA's read pattern) ────────────────────────────────

def write_csv(ctrl: dict) -> None:
    """Write 18-field header row + 18-field data row. EA skips the header."""
    fields = [
        ctrl["epoch"], ctrl["bar"], ctrl["action"], ctrl["confidence"],
        ctrl["gap"],
        f"{ctrl['tp']:.2f}", f"{ctrl['sl']:.2f}",
        f"{ctrl['lock_start']:.2f}", f"{ctrl['lock_giveback']:.2f}",
        f"{ctrl['secure_start']:.2f}", f"{ctrl['secure_lock']:.2f}",
        ctrl["modify_step"],
        f"{ctrl['lot_factor']:.2f}", f"{ctrl['grid_factor']:.2f}",
        f"{ctrl['profit_factor']:.2f}", f"{ctrl['drawdown_pct']:.2f}",
        f"{ctrl['spread_points']:.2f}",
        ctrl["reason_code"],
    ]
    # ANSI (not UTF-8) since EA opens with FILE_ANSI
    body = ",".join(HEADER) + "\n" + ",".join(str(v) for v in fields) + "\n"
    try:
        CONTROL_CSV.write_text(body, encoding="cp1252", errors="replace")
    except Exception:
        # Arabic chars may not fit cp1252; fall back to ASCII-only reason
        ctrl_safe = dict(ctrl)
        ctrl_safe["action"]      = "alert"
        ctrl_safe["reason_code"] = "non-ansi reason stripped"
        write_csv(ctrl_safe)


def write_bridge_state(ctrl: dict, swarm: dict) -> None:
    """Mirror for dashboard / brain_server consumption."""
    state = {
        "ts":          datetime.now().isoformat(),
        "control":     {k: v for k, v in ctrl.items() if not k.startswith("_")},
        "vetoes":      ctrl.get("_vetoes", []),
        "coordinator": swarm.get("coordinator", {}),
        "agent_count": len(swarm.get("agents", [])),
    }
    BRIDGE_LOG.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Main loop ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  FRIDAY → MT5 EA Bridge")
    print("=" * 60)
    print(f"  Reads:  {SWARM_JSON.name}")
    print(f"  Writes: {CONTROL_CSV.name}")
    print(f"  State:  {BRIDGE_LOG.name}")
    print("  Frequency: every 5s")
    print("=" * 60)
    print()

    last_epoch_written = 0

    while True:
        try:
            if not SWARM_JSON.exists():
                print(f"[{datetime.now():%H:%M:%S}] waiting for swarm JSON…")
                time.sleep(5)
                continue

            swarm = json.loads(SWARM_JSON.read_text(encoding="utf-8"))
            ctrl  = synthesize_control(swarm)
            write_csv(ctrl)
            write_bridge_state(ctrl, swarm)

            veto_str = ",".join(ctrl.get("_vetoes", [])) or "—"
            arrow = "→ EA" if ctrl["confidence"] >= 50 else "✗ IGNORED"
            print(
                f"[{datetime.now():%H:%M:%S}] {arrow:9s} "
                f"conf={ctrl['confidence']:3d}  lotF={ctrl['lot_factor']:.2f}  "
                f"gap={ctrl['gap']:4d}  tp={ctrl['tp']:.2f}  sl={ctrl['sl']:.2f}  "
                f"veto={veto_str}"
            )
            last_epoch_written = ctrl["epoch"]

        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] ERROR: {e}")

        time.sleep(5)


if __name__ == "__main__":
    main()
