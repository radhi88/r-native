"""
friday_v3.py — Main daemon for FRIDAY v3 Genetic Dip Buyer.

Architecture:
  • Every 3s: run dip detector
  • If quality >= MEDIUM: ask gene pool which genes approve
  • Best-fitness approving gene executes a paper or live trade
  • Manages open positions: exit at gene's profit_target OR SL OR max_hold
  • On close: record result → gene learns → pool may evolve

Paper mode by default. Use --live to execute real orders.
"""
from __future__ import annotations
import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

from friday_v3.indicators.dip_detector import detect_dip
from friday_v3.core.gene_pool import GenePool

# ─────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────

ROOT      = Path(r"C:\Users\Radhi\MT5\friday_v3")
SYMBOL    = "XAUUSDm"
MAGIC     = 20260603        # v3 fresh magic
KILL_FILE = Path(r"C:\Users\Radhi\MT5\kill_switch.txt")

CYCLE_S            = 3            # check every 3 seconds (fast scalper)
MAX_DAILY_LOSS_USD = 3.0          # hard daily cap (5% of $58 starting)
MAX_OPEN_POSITIONS = 3            # gene-pool can hold up to 3 concurrent
MAX_SPREAD_POINTS  = 500          # don't trade if spread above this
MIN_FREE_MARGIN    = 10.0         # need at least $10 free margin

LIVE_LOG  = ROOT / "data" / "v3_trades.csv"
EVENT_LOG = ROOT / "data" / "v3_events.log"
STATE     = ROOT / "data" / "v3_state.json"


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[v3 {ts}] {msg}"
    print(line, flush=True)
    try:
        EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(EVENT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception: pass


def log_trade_csv(row: dict):
    LIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not LIVE_LOG.exists()
    with open(LIVE_LOG, "a", encoding="utf-8") as f:
        if new:
            f.write(",".join(row.keys()) + "\n")
        f.write(",".join(str(v) for v in row.values()) + "\n")


def is_killed() -> bool:
    return KILL_FILE.exists()


def daily_pl_today() -> float:
    """Sum of v3 trade PLs from CSV for today (UTC)."""
    if not LIVE_LOG.exists(): return 0.0
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        total = 0.0
        with open(LIVE_LOG, encoding="utf-8") as f:
            lines = f.read().strip().split("\n")[1:]
            for line in lines:
                parts = line.split(",")
                if len(parts) < 10: continue
                ts = parts[0]
                pl = float(parts[-2]) if parts[-2] not in ("None", "") else 0
                if ts.startswith(today): total += pl
        return round(total, 2)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────
# Trade execution
# ─────────────────────────────────────────────────────────────────────────

class Executor:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        if not mt5.initialize():
            log(f"[INIT] MT5 init failed: {mt5.last_error()}")

    def open_positions(self) -> list:
        return [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]

    def buy_market(self, lot: float, sl: float, tp: float, comment: str) -> tuple[bool, int, str]:
        """Open BUY at market. Returns (ok, ticket, msg)."""
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if not tick or not info: return False, 0, "no tick"

        # Clamp lot to broker limits
        lot = max(info.volume_min, min(info.volume_max, lot))
        lot = round(lot / info.volume_step) * info.volume_step

        if self.dry_run:
            log(f"[DRY-BUY] lot={lot} @ {tick.ask:.2f}  SL={sl:.2f} TP={tp:.2f}")
            return True, 0, "dry-run"

        ascii_comment = "".join(ch for ch in comment if 32 <= ord(ch) < 127)[:20]
        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       SYMBOL,
            "volume":       float(lot),
            "type":         mt5.ORDER_TYPE_BUY,
            "price":        float(tick.ask),
            "sl":           float(sl),
            "tp":           float(tp),
            "deviation":    50,
            "magic":        MAGIC,
            "comment":      f"v3 {ascii_comment}",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            log(f"[LIVE-BUY] ticket={r.order} lot={lot} @ {tick.ask:.2f}  SL={sl:.2f} TP={tp:.2f}")
            return True, int(r.order), "OK"
        return False, 0, f"retcode={r.retcode if r else 'None'}: {r.comment if r else ''}"

    def close_position(self, ticket: int) -> bool:
        positions = mt5.positions_get(ticket=ticket)
        if not positions: return False
        p = positions[0]
        tick = mt5.symbol_info_tick(SYMBOL)
        close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
        price = tick.bid if p.type == 0 else tick.ask
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "position": int(ticket),
            "symbol": SYMBOL, "volume": p.volume, "type": close_type,
            "price": float(price), "deviation": 50, "magic": MAGIC,
            "comment": "v3 exit", "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if self.dry_run:
            log(f"[DRY-CLOSE] #{ticket}")
            return True
        r = mt5.order_send(req)
        return r and r.retcode == mt5.TRADE_RETCODE_DONE


# ─────────────────────────────────────────────────────────────────────────
# Main daemon
# ─────────────────────────────────────────────────────────────────────────

class FridayV3:
    def __init__(self, live: bool = False):
        self.pool = GenePool()
        self.exec = Executor(dry_run=not live)
        # Map open ticket -> {gene_id, dna, entry_time, entry_price, sl, tp, expected_target}
        self.live_positions: dict[int, dict] = {}
        self.next_dry_ticket = 1

    def _write_state(self):
        s = self.pool.summary()
        s["mode"]               = "LIVE" if not self.exec.dry_run else "PAPER"
        s["live_positions"]     = len(self.live_positions)
        s["daily_pl"]           = daily_pl_today()
        s["killed"]             = is_killed()
        s["positions_detail"]   = list(self.live_positions.values())
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")

    def _can_trade(self) -> tuple[bool, str]:
        if is_killed(): return False, "kill_switch.txt active"
        dpl = daily_pl_today()
        if dpl <= -MAX_DAILY_LOSS_USD: return False, f"daily loss cap ${dpl} <= -${MAX_DAILY_LOSS_USD}"
        if len(self.live_positions) >= MAX_OPEN_POSITIONS: return False, "max positions"
        info = mt5.account_info()
        if info and info.margin_free < MIN_FREE_MARGIN: return False, f"margin {info.margin_free} < {MIN_FREE_MARGIN}"
        sym = mt5.symbol_info(SYMBOL)
        if sym and sym.spread > MAX_SPREAD_POINTS: return False, f"spread {sym.spread} > {MAX_SPREAD_POINTS}"
        return True, "ok"

    def _try_open(self):
        # 1. Detect dip
        sig = detect_dip(SYMBOL)
        if not sig.is_actionable():
            return

        # 2. Pool vote
        approvers = self.pool.vote_on_signal(sig)
        if not approvers:
            return

        gene = self.pool.select_executor(approvers)
        if not gene:
            return

        # 3. Hard safety
        ok, why = self._can_trade()
        if not ok:
            log(f"[BLOCK] {why}")
            return

        # 4. Compute SL/TP from gene DNA
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        atr_pt = sig.drop_pt / max(0.1, sig.drop_atr)   # back out ATR
        sl_pt   = atr_pt * gene.dna.sl_atr_mult
        sl      = tick.ask - sl_pt * info.point
        # TP set wide; we'll exit at $profit_target manually
        tp      = tick.ask + sl_pt * 3 * info.point   # safety TP at 3R

        lot = gene.dna.lot_base * sig.suggested_lot_factor

        ok, ticket, msg = self.exec.buy_market(
            lot=lot, sl=sl, tp=tp,
            comment=f"{gene.id[:6]} d{sig.score}"
        )
        if not ok:
            log(f"[FAIL] gene {gene.id[:6]}: {msg}")
            return

        # Track
        ticket_key = ticket if ticket > 0 else (-1 - self.next_dry_ticket)
        if ticket == 0: self.next_dry_ticket += 1
        self.live_positions[ticket_key] = {
            "gene_id":      gene.id,
            "entry_time":   time.time(),
            "entry_price":  tick.ask,
            "sl":           sl,
            "tp":           tp,
            "lot":          lot,
            "profit_target_usd": gene.dna.profit_target_usd,
            "max_hold_min": gene.dna.max_hold_minutes,
            "dip_score":    sig.score,
            "dip_drop_atr": sig.drop_atr,
        }
        self.pool.mark_signal_sent(gene.id)
        log(f"[OPEN] #{ticket_key} gene {gene.id[:6]} (gen{gene.generation}) "
            f"lot={lot:.2f} score={sig.score} drop={sig.drop_pt:.0f}pt")

    def _manage_positions(self):
        # For paper, simulate exits; for live, query MT5 and exit on target
        for ticket_key, pos in list(self.live_positions.items()):
            age_min = (time.time() - pos["entry_time"]) / 60

            if self.exec.dry_run:
                # Simulate: random walk based on dip's expected mean-reversion
                tick = mt5.symbol_info_tick(SYMBOL)
                current = tick.bid
                # Simulated P/L (very rough — for paper testing)
                pl_usd = (current - pos["entry_price"]) * 100 * pos["lot"] - 0.30  # subtract spread
            else:
                # Real position lookup
                live = mt5.positions_get(ticket=ticket_key)
                if not live:
                    # closed externally — record neutral exit
                    self._record_close(ticket_key, pos, 0)
                    continue
                pl_usd = live[0].profit

            # Exit conditions
            exit_reason = None
            if pl_usd >= pos["profit_target_usd"]:
                exit_reason = f"target ${pl_usd:.2f}"
            elif age_min >= pos["max_hold_min"]:
                exit_reason = f"timeout {age_min:.1f}min"

            if exit_reason:
                if not self.exec.dry_run:
                    self.exec.close_position(ticket_key)
                log(f"[CLOSE] #{ticket_key} {exit_reason}  P/L=${pl_usd:+.2f}")
                self._record_close(ticket_key, pos, pl_usd)

    def _record_close(self, ticket_key: int, pos: dict, pl_usd: float):
        self.pool.record_outcome(pos["gene_id"], pl_usd)
        log_trade_csv({
            "ts":         datetime.utcnow().isoformat(),
            "ticket":     ticket_key,
            "gene_id":    pos["gene_id"],
            "entry":      pos["entry_price"],
            "lot":        pos["lot"],
            "profit_target": pos["profit_target_usd"],
            "dip_score":  pos["dip_score"],
            "dip_drop_atr": pos["dip_drop_atr"],
            "age_min":    round((time.time() - pos["entry_time"])/60, 1),
            "pl":         round(pl_usd, 2),
            "paper":      self.exec.dry_run,
        })
        del self.live_positions[ticket_key]

    def loop(self):
        log("=" * 60)
        log(f"FRIDAY v3 — Genetic Dip Buyer  ({'🔴 LIVE' if not self.exec.dry_run else '🟢 PAPER'})")
        log(f"  Magic:    {MAGIC}")
        log(f"  Cycle:    {CYCLE_S}s")
        log(f"  Pool:     {len(self.pool.genes)} genes, gen {self.pool.generation}")
        log(f"  Daily cap: ${MAX_DAILY_LOSS_USD}, max pos: {MAX_OPEN_POSITIONS}")
        log(f"  Kill:     {KILL_FILE.name}")
        log("=" * 60)
        cycle = 0
        while True:
            try:
                cycle += 1
                self._manage_positions()
                self._try_open()
                self._write_state()
                if cycle % 20 == 1:   # every minute summary
                    s = self.pool.summary()
                    log(f"summary: trades={s['total_trades']} pl=${s['total_pl']} "
                        f"open={len(self.live_positions)} daily=${daily_pl_today()}")
            except Exception as e:
                log(f"cycle error: {e}")
                import traceback; traceback.print_exc()
            time.sleep(CYCLE_S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="execute real trades")
    args = ap.parse_args()
    FridayV3(live=args.live).loop()


if __name__ == "__main__":
    main()
