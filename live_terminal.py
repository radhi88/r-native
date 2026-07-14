"""live_terminal.py — الترمنال الجنوني: لوحة كونسول حيّة كل ثانيتين.

يجمّع في شاشة واحدة، لحظيًا:
  • الحساب (رصيد/إكويتي/هامش)
  • الصفقات المفتوحة + العائم
  • آخر حالة من gold_live (السكالبر)
  • جيش الوكلاء (كم حيّ / أخطاء) + آخر نبضاتهم + رؤاهم (insights)

Run:  python live_terminal.py            # حيّ، يحدّث كل 2s (Ctrl-C يوقف)
      python live_terminal.py --frames 3 # يطبع 3 لقطات ثم يخرج
"""
from __future__ import annotations
import argparse, json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BS = "http://127.0.0.1:5055"
GLOG = Path(r"C:\Users\Radhi\MT5\logs\gold_live_run.out")
MAGICS = {99791: "gold_live", 99782: "unified", 20260605: "r_exec", 20260600: "EA"}


def _get(path, timeout=3.0):
    try:
        with urllib.request.urlopen(BS + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _last_log_line():
    try:
        lines = GLOG.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
        return lines[-1] if lines else "(no log)"
    except Exception:
        return "(no log)"


def frame(mt5):
    out = []
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    out.append(f"╔══════════ FRIDAY LIVE · {now} UTC ══════════╗")
    acc = mt5.account_info()
    if acc:
        out.append(f" ACCT  bal ${acc.balance:.2f}  eq ${acc.equity:.2f}  "
                   f"margin {acc.margin_level:.0f}%  free ${acc.margin_free:.2f}")
    pos = mt5.positions_get() or []
    if pos:
        tot = sum(p.profit for p in pos)
        out.append(f" POS   {len(pos)} open · float ${tot:+.2f}")
        for p in pos[:6]:
            side = "BUY " if p.type == 0 else "SELL"
            who = MAGICS.get(p.magic, str(p.magic))
            out.append(f"        {who:9} {side} {p.volume} @ {p.price_open:.2f} "
                       f"sl {p.sl:.2f} tp {p.tp:.2f}  ${p.profit:+.2f}")
    else:
        out.append(" POS   (لا صفقات مفتوحة)")
    out.append(f" SCALP {_last_log_line()[:70]}")
    # agents
    al = _get("/api/r/agents/list")
    if al and al.get("agents"):
        ags = al["agents"]
        alive = sum(1 for a in ags if a.get("thread_alive"))
        errs = sum(int(a.get("error_count", 0)) for a in ags)
        ticks = sum(int(a.get("tick_count", 0)) for a in ags)
        out.append(f" AGENTS {len(ags)} · حيّ {alive} · أخطاء {errs} · نبضات {ticks}")
        # the 3 most recently-ticked agents
        rec = sorted([a for a in ags if a.get("last_tick_at")],
                     key=lambda a: a.get("last_tick_at", ""), reverse=True)[:4]
        names = "  ".join(f"{a['name']}({a.get('last_tick_ms',0)}ms)" for a in rec)
        if names:
            out.append(f"        آخر نبض: {names}")
    else:
        out.append(" AGENTS (brain_server غير متاح على :5055)")
    ins = _get("/api/r/agents/insights")
    items = (ins or {}).get("insights") or (ins if isinstance(ins, list) else [])
    if items:
        out.append(" INSIGHTS:")
        for it in items[:4]:
            if isinstance(it, dict):
                who = it.get("agent") or it.get("name") or "?"
                msg = str(it.get("message") or it.get("text") or it.get("insight") or it)[:60]
                out.append(f"   • [{who}] {msg}")
    out.append("╚" + "═" * 48 + "╝")
    return "\n".join(out)


def main():
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)  # 0 = loop forever
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args()
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    try:
        n = 0
        while True:
            print("\033[2J\033[H", end="")        # clear screen
            print(frame(mt5), flush=True)
            n += 1
            if a.frames and n >= a.frames:
                break
            time.sleep(a.interval)
    except KeyboardInterrupt:
        pass
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
