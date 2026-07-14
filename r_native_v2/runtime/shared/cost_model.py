"""shared/cost_model.py — Realistic broker-friction cost model (BRICK B1).

Born 2026-05-31. Stdlib only — no MetaTrader5, no numpy.

PURPOSE
    Make backtests honest about the tight-TP cost killer on M1/M5. A naive
    backtest that ignores spread + commission + slippage will happily "profit"
    on a 5-pip TP that, after round-trip friction, is actually a loser. This
    module quantifies the real dollar drag per round-trip so the optimizer
    stops chasing fictional edges.

GROUNDING (Algory broker-friction diagnostics)
    Gold (XAUUSDm):
        - spread ~280 points, point size 0.001 => ~0.28 price units
        - total fee ~0.0218% (round-turn, notional-based)
        - slippage 30 points (default execution assumption)
        - swap long -547.6 (per lot, per night, points/account-ccy basis)
        - max_spread 16 pips (entry gate, not applied as cost here)
    These numbers seed the XAUUSDm profile below; FX and crypto profiles use
    sensible broker-typical defaults in the same shape.

COST MODEL (per round-trip = one open + one close)
    spread_cost      : you cross the spread once on entry (paid at fill).
    commission_cost  : notional * fee_rate, charged round-turn.
    slippage_cost    : adverse fill, modelled as N points * point_value * lot,
                       applied for entry AND exit (2x) => round-trip slippage.
    round_trip_cost  : spread + commission + 2x slippage, in account dollars.

UNITS
    All *_cost functions return dollars (account currency) for the given lot
    size. spread_cost(symbol, price) returns the per-1.0-lot spread cost; callers
    multiply by lot if needed, or use round_trip_cost() which folds lot in.

USAGE
    from runtime.shared.cost_model import round_trip_cost, COSTS
    rt = round_trip_cost("XAUUSDm", lot=0.10, price=3300.0)
    # rt -> total $ drag a trade must overcome before it nets positive
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class SymbolCost:
    """Per-symbol friction profile.

    point          : smallest price increment (e.g. gold 0.001, EURUSD 0.00001).
    contract_size  : units of base asset per 1.0 lot.
    spread_points  : typical spread in *points* (point-multiples).
    fee_rate       : round-turn commission as a fraction of notional (0.0218% = 0.000218).
    slippage_points: default adverse-fill slippage in points, per side.
    swap_long      : informational — overnight swap on a long, per lot (account ccy basis).
    max_spread_points: entry gate threshold in points (not charged as a cost).

    point_value (per 1.0 lot) = point * contract_size, expressed in the symbol's
    quote currency. For USD-quoted symbols (XAU/USD, BTC/USD, EUR/USD) this is
    already account dollars on a USD account.
    """

    point: float
    contract_size: float
    spread_points: float
    fee_rate: float
    slippage_points: float = 30.0
    swap_long: float = 0.0
    max_spread_points: float = 0.0

    @property
    def point_value(self) -> float:
        """Dollar value of one point move, per 1.0 lot (quote ccy = USD assumed)."""
        return self.point * self.contract_size


# ---------------------------------------------------------------------------
# Per-symbol config. Defaults grounded in Algory diagnostics (gold) plus
# broker-typical FX / crypto values. Keys match MT5 'm' suffix convention.
# ---------------------------------------------------------------------------
COSTS: Dict[str, SymbolCost] = {
    # Gold — directly from Algory friction profile.
    # 280 points * 0.001 = 0.28 price units spread; contract 100 oz/lot
    # => point_value = 0.001 * 100 = $0.10 per point per lot.
    "XAUUSDm": SymbolCost(
        point=0.001,
        contract_size=100.0,
        spread_points=280.0,
        fee_rate=0.000218,        # ~0.0218% round-turn
        slippage_points=30.0,
        swap_long=-547.6,
        max_spread_points=160.0,  # 16 pips (1 pip = 10 points on 3-dp gold)
    ),
    # EUR/USD — 5-digit FX. point_value = 0.00001 * 100000 = $1.00 / point / lot.
    "EURUSDm": SymbolCost(
        point=0.00001,
        contract_size=100000.0,
        spread_points=12.0,       # ~1.2 pip typical
        fee_rate=0.00007,         # ~0.007% round-turn (raw-ish spread acct)
        slippage_points=10.0,
        swap_long=-7.2,
        max_spread_points=30.0,
    ),
    # BTC/USD — crypto. 1 BTC/lot, 2-dp pricing.
    # point_value = 0.01 * 1 = $0.01 / point / lot.
    "BTCUSDm": SymbolCost(
        point=0.01,
        contract_size=1.0,
        spread_points=5000.0,     # ~$50 typical spread
        fee_rate=0.0005,          # ~0.05% round-turn
        slippage_points=200.0,    # crypto fills are loose
        swap_long=-35.0,
        max_spread_points=12000.0,
    ),
    # ↓ ملفّات مصحّحة من مواصفات MT5 الحقيقية (trade_tick_value) — كانت تسقط على FX-default
    # الخاطئ فتضخّم net$ بـ~100x وتقلّل السبريد (تدقيق 2026-06-15: US30 أظهر +$9.3M وهمي).
    # point_value = point*contract = tick_value الحقيقي لكل رمز.
    # USD/JPY — quote=JPY فلا ينطبق point*contract؛ نضبط contract تركيبياً ليطابق tickval=0.624.
    "USDJPYm": SymbolCost(
        point=0.001, contract_size=624.0,    # 0.001*624 = 0.624 = tick_value الحقيقي
        spread_points=10.0, fee_rate=0.00007, slippage_points=10.0, swap_long=4.0, max_spread_points=30.0,
    ),
    # Silver — point 0.001, contract 5000 => tick_value $5.0/point ✓
    "XAGUSDm": SymbolCost(
        point=0.001, contract_size=5000.0,
        spread_points=30.0, fee_rate=0.00022, slippage_points=25.0, swap_long=-3.0, max_spread_points=120.0,
    ),
    # WTI Oil — point 0.001, contract 1000 => tick_value $1.0/point ✓
    "USOILm": SymbolCost(
        point=0.001, contract_size=1000.0,
        spread_points=20.0, fee_rate=0.0002, slippage_points=20.0, swap_long=-5.0, max_spread_points=80.0,
    ),
    # US30 (Dow CFD) — point 0.1, contract 1 => tick_value $0.10/point ✓
    "US30m": SymbolCost(
        point=0.1, contract_size=1.0,
        spread_points=23.0, fee_rate=0.0001, slippage_points=30.0, swap_long=-10.0, max_spread_points=100.0,
    ),
}

# Generic fallbacks by asset class, used when a symbol is unknown.
_FX_DEFAULT = COSTS["EURUSDm"]
_GOLD_DEFAULT = COSTS["XAUUSDm"]
_CRYPTO_DEFAULT = COSTS["BTCUSDm"]


def _profile(symbol: str) -> SymbolCost:
    """Resolve a symbol to its cost profile, with asset-class fallback."""
    if symbol in COSTS:
        return COSTS[symbol]
    s = symbol.upper()
    if "XAU" in s or "GOLD" in s:
        return _GOLD_DEFAULT
    if "BTC" in s or "ETH" in s or s.endswith("USDT"):
        return _CRYPTO_DEFAULT
    # default: treat as FX
    return _FX_DEFAULT


# ---------------------------------------------------------------------------
# Cost functions. All return dollars (account ccy, USD account assumed).
# ---------------------------------------------------------------------------
def spread_cost(symbol: str, price: float) -> float:
    """Cost of crossing the spread once (entry), per 1.0 lot, in dollars.

    spread_points * point_value gives the spread in dollars per lot. The
    `price` argument is accepted for interface symmetry and for any future
    percentage-of-price spread models; the points-based model does not need it.
    """
    p = _profile(symbol)
    return p.spread_points * p.point_value


def commission_cost(symbol: str, lot: float, price: float) -> float:
    """Round-turn commission in dollars: notional * fee_rate.

    notional = lot * contract_size * price (in quote ccy = USD).
    """
    p = _profile(symbol)
    notional = lot * p.contract_size * price
    return notional * p.fee_rate


def slippage_cost(symbol: str, points: float = 30.0) -> float:
    """Adverse-fill cost for ONE side, per 1.0 lot, in dollars.

    Defaults to 30 points (Algory gold assumption). Caller scales by lot;
    round_trip_cost applies this twice (entry + exit) and multiplies by lot.
    """
    p = _profile(symbol)
    return points * p.point_value


def round_trip_cost(symbol: str, lot: float, price: float) -> float:
    """Total dollar cost of a complete round-trip (open + close) for `lot`.

    = spread (crossed once on entry)
    + round-turn commission
    + slippage on entry + slippage on exit (2 sides)
    all scaled to the traded lot size.
    """
    p = _profile(symbol)
    spread = spread_cost(symbol, price) * lot
    commission = commission_cost(symbol, lot, price)
    slip = slippage_cost(symbol, p.slippage_points) * lot * 2.0
    return spread + commission + slip


def round_trip_cost_pts(symbol: str, price: float | None = None) -> float:
    """Round-trip cost expressed in *points* (price-units / point) per trade.

    This is the lot- and account-currency-independent friction a single trade
    must overcome, in points of price travel. It is the interface the
    independent backtester (BRICK B2, runtime.oos_backtest) probes for.

    Derivation: round_trip_cost is lot-linear EXCEPT commission, which scales
    with notional (price). We compute the round-trip dollar cost at lot=1.0 and
    divide by point_value (dollars per point per lot) to get points. A
    representative price is needed for the commission term; if none is given we
    use a sensible per-symbol default so the call still works arg-free.
    """
    p = _profile(symbol)
    if price is None:
        # representative mid prices for the commission (notional) term
        s = symbol.upper()
        if "XAU" in s or "GOLD" in s:
            price = 3300.0
        elif "BTC" in s:
            price = 68000.0
        elif "ETH" in s:
            price = 3500.0
        else:
            price = 1.10  # FX-typical
    dollars = round_trip_cost(symbol, lot=1.0, price=price)
    pv = p.point_value
    if pv <= 0:
        return 0.0
    cost_in_internal_points = dollars / pv  # points of size `p.point`

    # The independent backtester (oos_backtest) expresses gold SL/TP in
    # 1.0-price-unit "gold-points" (its pt=1.0 for XAU), whereas this module's
    # internal point for gold is 0.001. Convert to the caller's trading-point
    # convention so `value * pt` in B2 yields the correct price-unit cost:
    #   gold  -> price units      (trading-point = 1.0)
    #   FX    -> internal points  (trading-point = symbol.point)
    s = symbol.upper()
    if "XAU" in s or "GOLD" in s:
        # internal points are 0.001 each; collapse to 1.0-unit points.
        return cost_in_internal_points * p.point
    return cost_in_internal_points


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    examples = [
        ("XAUUSDm", 0.10, 3300.00),
        ("EURUSDm", 0.10, 1.0850),
        ("BTCUSDm", 0.10, 68000.00),
    ]
    print("=" * 72)
    print("BRICK B1 — round-trip cost model  (account ccy = USD)")
    print("=" * 72)
    for sym, lot, px in examples:
        p = _profile(sym)
        sp = spread_cost(sym, px) * lot
        com = commission_cost(sym, lot, px)
        slip = slippage_cost(sym, p.slippage_points) * lot * 2.0
        rt = round_trip_cost(sym, lot, px)
        # break-even move in points: drag must be recovered by price travel
        be_points = rt / (p.point_value * lot) if p.point_value * lot else 0.0
        print(f"\n{sym}  lot={lot}  price={px}")
        print(f"  point_value/lot   : ${p.point_value:,.4f} per point")
        print(f"  spread  ({p.spread_points:>7.0f} pts) : ${sp:,.2f}")
        print(f"  commission ({p.fee_rate*100:.4f}%) : ${com:,.2f}")
        print(f"  slippage (2x{p.slippage_points:.0f} pts) : ${slip:,.2f}")
        print(f"  --------------------------------")
        print(f"  ROUND-TRIP TOTAL  : ${rt:,.2f}")
        print(f"  break-even move   : {be_points:,.1f} points "
              f"(${rt:,.2f} drag to overcome before profit)")
    print("\n" + "=" * 72)
    print("Takeaway: any TP tighter than the break-even move is a guaranteed")
    print("net loser once friction is paid. Backtests must subtract round_trip_cost.")
    print("=" * 72)
