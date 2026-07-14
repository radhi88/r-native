"""Micro-equity survival calculus for a $10 account.

Implements the modified Kelly criterion, the volatility-adjusted stop, and
fractional position sizing with the hard survival rule: if a minimum-lot
position risks more than :data:`config.SURVIVAL_REJECT_RISK` of equity, the
trade is rejected rather than sized down (you cannot size below the min lot).
"""
from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass
class SizingResult:
    """Outcome of a sizing decision.

    Attributes:
        volume: Lots to trade (0.0 means rejected).
        risk_money: Money at risk to the stop, in account currency.
        risk_pct: ``risk_money`` as a fraction of equity.
        kelly_f: The Kelly fraction used.
        reason: Human-readable accept/reject explanation.
        accepted: Whether the trade clears every survival gate.
    """

    volume: float
    risk_money: float
    risk_pct: float
    kelly_f: float
    reason: str
    accepted: bool


def modified_kelly(win_rate: float, payoff: float) -> float:
    """Compute the capped modified-Kelly fraction.

    ``f* = min(KELLY_CAP, (p*(b+1) - 1) / b)`` floored at 0.

    Args:
        win_rate: Probability of a win, ``p`` in ``[0, 1]``.
        payoff: Ratio of average win to average loss, ``b > 0``.

    Returns:
        A fraction of equity in ``[0, config.KELLY_CAP]``.
    """
    if payoff <= 0:
        return 0.0
    raw = (win_rate * (payoff + 1.0) - 1.0) / payoff
    return max(0.0, min(config.KELLY_CAP, raw))


def atr_stop_distance(atr: float, market_k: float) -> float:
    """Volatility-adjusted stop distance in price units.

    Args:
        atr: Average True Range of the working timeframe.
        market_k: Per-market multiplier (1.4–2.0 typical).

    Returns:
        ``ATR * k`` clamped to the sane ``[1.4, 2.0] * atr`` band.
    """
    k = max(1.4, min(2.0, market_k))
    return atr * k


def _money_per_lot(sl_dist: float, tick_size: float, tick_value: float) -> float:
    """Money lost per 1.0 lot if the stop is hit."""
    if tick_size <= 0:
        return 0.0
    return (sl_dist / tick_size) * tick_value


def size_position(
    equity: float,
    sl_dist: float,
    kelly_f: float,
    tick_size: float,
    tick_value: float,
    vol_min: float,
    vol_step: float,
    free_margin: float,
    margin_per_lot: float,
) -> SizingResult:
    """Size a position under the micro-equity survival rules.

    ``Volume = max(V_min, Equity * f* / (SL_dist * value_per_point))``, then
    rejected if the floored min-lot risk exceeds the survival threshold or if
    required margin exceeds 90% of free margin.

    Args:
        equity: Account equity.
        sl_dist: Stop distance in price units (from :func:`atr_stop_distance`).
        kelly_f: Kelly fraction from :func:`modified_kelly`.
        tick_size: Symbol tick size.
        tick_value: Money value of one tick for 1.0 lot.
        vol_min: Broker minimum lot.
        vol_step: Broker lot step.
        free_margin: Available margin.
        margin_per_lot: Margin required for 1.0 lot.

    Returns:
        A :class:`SizingResult`; ``accepted`` is False when any gate trips.
    """
    per_lot = _money_per_lot(sl_dist, tick_size, tick_value)
    if per_lot <= 0:
        return SizingResult(0.0, 0.0, 0.0, kelly_f, "bad tick math", False)

    target = (equity * kelly_f) / per_lot
    steps = max(1, round(target / vol_step)) if target >= vol_min else 0
    vol = max(vol_min, steps * vol_step) if steps else vol_min
    vol = round(vol / vol_step) * vol_step

    risk_money = vol * per_lot
    risk_pct = risk_money / equity if equity > 0 else 1.0

    # $10 survival rule: cannot size below vol_min, so reject outright.
    min_risk_pct = (vol_min * per_lot) / equity if equity > 0 else 1.0
    if min_risk_pct > config.SURVIVAL_REJECT_RISK:
        return SizingResult(
            0.0, vol_min * per_lot, min_risk_pct, kelly_f,
            f"min-lot risk {min_risk_pct:.1%} > {config.SURVIVAL_REJECT_RISK:.0%} "
            f"survival cap — WAIT for low-vol compression", False)

    if risk_pct > config.MAX_RISK_PER_TRADE:
        # clamp to the smallest viable lot if even that fits the survival cap
        vol = vol_min
        risk_money = vol * per_lot
        risk_pct = risk_money / equity

    if margin_per_lot * vol > 0.90 * free_margin:
        return SizingResult(0.0, risk_money, risk_pct, kelly_f,
                            "margin > 90% free margin — reject", False)

    return SizingResult(vol, risk_money, risk_pct, kelly_f,
                        f"sized {vol} lots @ {risk_pct:.1%} risk", True)
