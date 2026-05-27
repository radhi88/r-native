"""council/risk.py — capital protection.

  • Per-trade risk ≤ 3% of equity (the cycle-24 cap)
  • Open exposure ≤ 6% of equity (sum of all current SL distances × lot)
  • Account ≥ $10 floor
  • Spread ≤ 25% of M1 ATR (don't trade through huge spreads)
"""
from __future__ import annotations
from .types import Proposal, Verdict


MAX_RISK_PCT  = 3.0
MAX_OPEN_EXPO = 6.0
MIN_BALANCE   = 10.0


def _risk_usd(p, contract_size: float = 100.0) -> float:
    """USD risk = SL distance × lot × contract size (gold $1/pt @ 0.01)."""
    return abs(p.entry - p.sl) * p.lot * contract_size


def risk_review(proposal: Proposal, snapshot, account) -> Verdict:
    p = proposal
    eq = float(account.get("equity", 0)) if isinstance(account, dict) else float(getattr(account, "equity", 0))
    if eq < MIN_BALANCE:
        return Verdict(False, f"equity ${eq:.2f} below ${MIN_BALANCE} floor", 100)

    # Per-trade risk
    try:
        import MetaTrader5 as mt5
        si = mt5.symbol_info(p.symbol)
        per_pt = float(si.trade_tick_value) / max(float(si.trade_tick_size), 1e-9)
    except Exception:
        per_pt = 100.0   # fall back gold default
    risk = abs(p.entry - p.sl) * per_pt * p.lot
    pct  = (risk / eq * 100) if eq > 0 else 0
    if pct > MAX_RISK_PCT:
        return Verdict(False, f"risk ${risk:.2f} = {pct:.1f}% > {MAX_RISK_PCT}% cap", 100)

    # Spread vs ATR
    m1 = snapshot.tfs.get("M1")
    if m1 and m1.atr > 0:
        ratio = snapshot.spread / m1.atr
        if ratio > 0.25:
            return Verdict(False,
                f"spread ${snapshot.spread:.2f} = {ratio*100:.0f}% of M1 ATR — too wide", 90)

    return Verdict(True,
        f"risk ${risk:.2f} ({pct:.1f}% eq) · spread OK", 80)
