"""agents/streak_detector.py — surface hot/cold runs per genome.

Every 15 min, walks the trailing-48h R-magic close deals and groups them
by their opening genome (parsed from the R-<gid>-<side> comment on the
OPEN deal, same attribution path the live HoF tracker uses). For each
genome, counts the current consecutive-win or consecutive-loss streak.

Emits:
  🔥 hot streak  — ≥3 consecutive wins for a genome
  🥶 cold streak — ≥3 consecutive losses (rotation candidate)

Both with dedup so a single 3-win streak doesn't fire every 15 min.
A streak only re-emits if it GROWS (4→5→6 …) or the genome flips
direction (cold → hot or hot → cold).

State persisted to data/r_native/streak_state.json so the dedup
survives brain restarts.

This is pure visibility — no actions, no config changes. Compliments
auto_rotator (which uses absolute pnl edge) by showing MOMENTUM
patterns the rotator's snapshot-only logic misses (e.g. a genome
on a 4-win run that hasn't yet built enough pnl edge to trigger
rotation, but is clearly trending the right way).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


STATE_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\streak_state.json")
R_MAGIC    = 20260605


class StreakDetector(Agent):
    name = "streak_detector"
    description = "Detects hot/cold trade streaks per genome"
    interval_seconds = 900     # 15 min
    default_enabled = True

    HOT_STREAK_MIN  = 3   # ≥3 wins in a row to fire
    COLD_STREAK_MIN = 3   # ≥3 losses in a row to fire
    EVICT_ON_COLD_STREAK = 4  # ≥4 losses in a row: actively REMOVE from
                               # symbol's competitor list (cycle 34 → tightened
                               # to 4 in cycle 35 — 8CE50E on BTCUSDm was at
                               # 4 losses + $-7.48 still bleeding; lower
                               # threshold catches earlier).
    LOOKBACK_HOURS  = 48

    def _load_state(self) -> dict:
        if not STATE_PATH.exists(): return {}
        try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception: return {}

    def _save_state(self, state: dict):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                               encoding="utf-8")

    def _compute_streaks(self, mt5) -> dict:
        """Walk closes, group by opener-genome, compute current streak."""
        since = datetime.now() - timedelta(hours=self.LOOKBACK_HOURS)
        deals = mt5.history_deals_get(since, datetime.now()) or []
        r_deals = [d for d in deals if int(getattr(d, "magic", 0)) == R_MAGIC]

        # Build ticket → opener_gid from OPENS
        ticket_gid = {}
        ticket_sym = {}
        for d in r_deals:
            if int(d.entry) != 0: continue
            m = re.match(r"R-([A-F0-9]{6})-", d.comment or "")
            if not m: continue
            pid = int(getattr(d, "position_id", None) or d.order)
            ticket_gid[pid] = m.group(1)
            ticket_sym[pid] = d.symbol

        # Walk CLOSES chronologically per genome
        closes_by_gid: dict[str, list] = {}
        for d in sorted([x for x in r_deals if int(x.entry) == 1],
                         key=lambda x: int(x.time)):
            pid = int(getattr(d, "position_id", None) or d.order)
            gid = ticket_gid.get(pid)
            if not gid: continue
            net = float(d.profit) + float(d.swap) + float(d.commission)
            closes_by_gid.setdefault(gid, []).append({
                "pnl":    net,
                "sym":    ticket_sym.get(pid, "?"),
                "ts":     int(d.time),
                "is_win": net > 0,
            })

        # Compute trailing streak per genome
        out = {}
        for gid, closes in closes_by_gid.items():
            if not closes: continue
            # Most-recent first
            tail = list(reversed(closes))
            last_is_win = tail[0]["is_win"]
            run = 0
            for c in tail:
                if c["is_win"] == last_is_win:
                    run += 1
                else:
                    break
            out[gid] = {
                "direction":      "WIN" if last_is_win else "LOSS",
                "length":         run,
                "symbol":         tail[0]["sym"],
                "last_pnl":       round(tail[0]["pnl"], 2),
                "total_closes":   len(closes),
                "trailing_pnl":   round(sum(c["pnl"] for c in tail[:run]), 2),
            }
        return out

    def _evict_from_competitors(self, gid: str, symbol: str,
                                  streak_len: int, trailing_pnl: float):
        """Remove cold-streak genome from the symbol's competitor list.
        Doesn't touch primary slot (auto_rotator handles that). Skips
        pinned genomes."""
        try:
            from r_native.hall_of_fame import load_index
            hof_entry = (load_index() or {}).get(gid) or {}
            if hof_entry.get("pinned"):
                return   # never evict pinned
            from pathlib import Path
            import json as _j
            cfg_path = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs") / f"{symbol}.json"
            if not cfg_path.exists(): return
            cfg = _j.loads(cfg_path.read_text(encoding="utf-8"))
            if (cfg.get("deployed_genome") or {}).get("id") == gid:
                return   # primary slot — auto_rotator's responsibility
            comps = cfg.get("competitors") or []
            new_comps = [c for c in comps
                          if (c.get("id") if isinstance(c, dict) else c) != gid]
            if len(new_comps) == len(comps):
                return   # not a competitor on this symbol
            cfg["competitors"] = new_comps
            tmp = cfg_path.with_suffix(".json.tmp")
            tmp.write_text(_j.dumps(cfg, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            tmp.replace(cfg_path)
            emit_insight(self.name, "ACT",
                f"⏏ EVICTED {gid} from {symbol} competitors "
                f"({streak_len}-loss streak, ${trailing_pnl:+.2f} run)",
                data={"gid": gid, "symbol": symbol, "streak": streak_len,
                       "trailing_pnl": trailing_pnl},
                action="cold_streak_evicted")
        except Exception as _e:
            emit_insight(self.name, "WARN",
                f"evict failed for {gid} on {symbol}: {_e}")

    def tick(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
        except Exception as e:
            emit_insight(self.name, "WARN", f"mt5 init failed: {e}")
            return

        streaks  = self._compute_streaks(mt5)
        prev     = self._load_state().get("streaks", {})
        new_state = dict(prev)

        # Look up nicknames for friendly insight text
        try:
            from r_native.hall_of_fame import load_index
            hof = load_index() or {}
        except Exception:
            hof = {}

        notable_changes = []
        for gid, info in streaks.items():
            # Skip killed genomes — their streaks are historical, not
            # actionable. They're no longer firing entries.
            hof_entry = hof.get(gid) or {}
            if hof_entry.get("killed"): continue
            direction = info["direction"]
            length    = info["length"]
            min_len = self.HOT_STREAK_MIN if direction == "WIN" else self.COLD_STREAK_MIN
            if length < min_len: continue

            prev_info = prev.get(gid) or {}
            prev_dir  = prev_info.get("direction")
            prev_len  = int(prev_info.get("length") or 0)

            # Fire only on direction-flip OR growth
            grew_or_flipped = (direction != prev_dir) or (length > prev_len)

            # Cycle 35 fix: eviction must run even when length is unchanged.
            # If a cold streak hits threshold and persists, we want eviction
            # to fire EVERY tick until the genome is gone — not just on
            # the one tick where it grew.
            should_evict_now = (direction == "LOSS"
                                and length >= self.EVICT_ON_COLD_STREAK
                                and not hof_entry.get("killed"))
            if should_evict_now:
                self._evict_from_competitors(gid, info["symbol"], length,
                                              info["trailing_pnl"])

            if not grew_or_flipped:
                new_state[gid] = info
                continue

            nick = (hof.get(gid) or {}).get("nickname", gid)[:35]
            if direction == "WIN":
                emit_insight(self.name, "ACT",
                    f"🔥 hot streak: {nick} ({gid}) {length} wins in a row on "
                    f"{info['symbol']} (+${info['trailing_pnl']:+.2f} run)",
                    data={"id": gid, **info},
                    action=f"hot_streak_{gid}")
            else:
                emit_insight(self.name, "WARN",
                    f"🥶 cold streak: {nick} ({gid}) {length} losses in a row on "
                    f"{info['symbol']} (${info['trailing_pnl']:+.2f} run) — "
                    f"rotation candidate")
                # Cycle 34: take action on persistent cold streaks. If
                # genome has lost EVICT_ON_COLD_STREAK+ in a row, REMOVE it
                # from any symbol's competitor list. Stops it firing more
                # trades until it gets re-added via deploy_assistant later.
                if length >= self.EVICT_ON_COLD_STREAK:
                    self._evict_from_competitors(gid, info["symbol"], length,
                                                  info["trailing_pnl"])
            notable_changes.append((gid, direction, length))
            new_state[gid] = info

        # Save full state so future ticks can detect growth/flip
        self._save_state({
            "streaks":    {gid: s for gid, s in streaks.items()},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
