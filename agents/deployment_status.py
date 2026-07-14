"""agents/deployment_status.py — single source of truth for the multi-genome race.

Each symbol has a primary + competitor genomes that all trade in parallel.
The user needs a one-glance view of "who's deployed where and how are
they doing?" — currently they'd have to read 12 symbol configs and
cross-reference HoF live_pnl manually.

This agent runs every 15 min and:

  • Walks all deployed symbol_configs
  • For each: looks up primary + competitors in HoF
  • Builds a compact per-symbol summary with score + live data
  • Writes data/r_native/deployment_status.json (UI can render a table)
  • Emits ONE consolidated INFO insight every 30 min:
      "🏁 slots: BTC=0446F1[76📌|0t] +3comps · XAU=4F5F59[72|7t+$5.79] +2 · ..."

The character budget per symbol is ~30 chars so 12 symbols fits in an
insight line. Read on wake = instant understanding of who's racing
who and who's winning.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


SYMBOL_CFG_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
OUT_PATH       = Path(r"C:\Users\Radhi\MT5\data\r_native\deployment_status.json")


class DeploymentStatus(Agent):
    name = "deployment_status"
    description = "Per-symbol primary/competitors snapshot with live P/L"
    interval_seconds = 900       # 15 min
    default_enabled = True

    _last_summary_ts: float = 0.0
    SUMMARY_EVERY_SECONDS = 1800   # emit consolidated insight every 30 min

    def _short(self, gid: str) -> str:
        return (gid or "?")[:6]

    def _genome_brief(self, hof: dict, gid: str, is_primary: bool = False) -> dict:
        g = hof.get(gid) or {}
        return {
            "id":          gid,
            "short":       self._short(gid),
            "score":       round(float(g.get("score") or 0), 1),
            "pinned":      bool(g.get("pinned")),
            "killed":      bool(g.get("killed")),
            "live_trades": int(g.get("live_trades") or 0),
            "live_pnl":    round(float(g.get("live_pnl") or 0), 2),
            "live_wr":     round(float(g.get("live_wr_pct") or 0), 0),
            "is_primary":  is_primary,
        }

    def _load_regimes(self) -> dict:
        """Pull current regime per symbol from market_scan.json (written
        every 90s by market_scanner). Returns {symbol: 'TREND_UP'|'DEAD'|…}.
        Missing file = empty dict, callers tolerate it."""
        scan_path = Path(r"C:\Users\Radhi\MT5\data\r_native\market_scan.json")
        if not scan_path.exists(): return {}
        try:
            import json as _j
            scan = _j.loads(scan_path.read_text(encoding="utf-8"))
            return {sym: data.get("regime", "?")
                    for sym, data in (scan.get("symbols") or {}).items()}
        except Exception:
            return {}

    def tick(self):
        if not SYMBOL_CFG_DIR.exists(): return
        try:
            from r_native.hall_of_fame import load_index
            hof = load_index() or {}
        except Exception: return
        regimes = self._load_regimes()

        by_symbol = {}
        for path in SYMBOL_CFG_DIR.glob("*.json"):
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
            except Exception: continue

            primary_gid = (cfg.get("deployed_genome") or {}).get("id")
            comps = cfg.get("competitors") or []
            if not primary_gid: continue

            primary_brief = self._genome_brief(hof, primary_gid, is_primary=True)
            comp_briefs = []
            for c in comps:
                cid = c.get("id") if isinstance(c, dict) else c
                if not cid or cid == primary_gid: continue
                comp_briefs.append(self._genome_brief(hof, cid))

            by_symbol[path.stem] = {
                "primary":     primary_brief,
                "competitors": comp_briefs,
                "comp_count":  len(comp_briefs),
                "max_comps":   3,
                "regime":      regimes.get(path.stem, "?"),
            }

        out = {
            "symbols":    by_symbol,
            "total_syms": len(by_symbol),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                             encoding="utf-8")

        # Emit consolidated insight every 30 min
        import time as _t
        now_s = _t.time()
        if (now_s - self._last_summary_ts) < self.SUMMARY_EVERY_SECONDS:
            return

        # Build compact one-line summary with regime hint per symbol.
        # Format: BTC[TRND]=4F5F59[72📌|7t+5.79] +3
        notable = []
        regime_short = {"TREND_UP": "↑", "TREND_DOWN": "↓",
                         "RANGE": "↔", "DEAD": "·"}
        for sym, data in by_symbol.items():
            p = data["primary"]
            tag = "📌" if p["pinned"] else ""
            pnl_str = (f"+{p['live_pnl']}" if p["live_pnl"] >= 0
                        else f"{p['live_pnl']}")
            short_sym = sym.replace("USDm", "").replace("m", "")[:4]
            r_glyph = regime_short.get(data.get("regime"), "?")
            notable.append(
                f"{short_sym}{r_glyph}={p['short']}[{p['score']:.0f}{tag}"
                f"|{p['live_trades']}t {pnl_str}] +{data['comp_count']}"
            )

        # Total live trades + pnl across all primaries (a quick health number)
        total_live_trades = sum(d["primary"]["live_trades"] for d in by_symbol.values())
        total_live_pnl   = sum(d["primary"]["live_pnl"]   for d in by_symbol.values())

        emit_insight(self.name, "INFO",
            f"🏁 deployments ({len(by_symbol)} symbols, "
            f"{total_live_trades}t primary-live ${total_live_pnl:+.2f}): "
            + " · ".join(notable[:8])
            + (" …" if len(notable) > 8 else ""),
            data={"summary": by_symbol})
        self._last_summary_ts = now_s
