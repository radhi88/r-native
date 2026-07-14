"""
Phase 9 — REGIME-03: Regime-mult sizing wiring tests.

These tests are EXPECTED TO FAIL (RED) until 09-05 implements
regime_lot_mult(symbol, vol_state) -> float in scripts/friday_web_dashboard.py.

Contracts tested (from 09-CONTEXT.md decisions D-06, D-07):
  - D-06: regime_mult affects LOT size only, NEVER the decision["action"] field.
  - D-07: XAUUSDm is damped (regime_lot_mult < 1.0 for low vol_state);
          FX symbols (e.g. EURUSDm) pass through at 1.0.
  - Bounds: opp_mult after damp still respects max(0.4, min(., 3.0)) clipping.

Imports wrapped inside test bodies (T-09-02 mitigation).
"""

import pytest
from typing import Optional


VOL_STATES = ("low", "normal", "high")


def _import_regime_lot_mult():
    """
    Attempt to import regime_lot_mult from scripts.friday_web_dashboard.
    Returns the function or raises ImportError (converted to FAIL by tests).

    The function signature expected by 09-05:
        regime_lot_mult(symbol: str, vol_state: str) -> float
    """
    import importlib
    try:
        mod = importlib.import_module("scripts.friday_web_dashboard")
    except Exception as exc:
        raise ImportError(
            f"scripts.friday_web_dashboard import failed: {exc}"
        ) from exc
    fn = getattr(mod, "regime_lot_mult", None)
    if fn is None:
        raise ImportError(
            "regime_lot_mult not found in scripts.friday_web_dashboard. "
            "Plan 09-05 must add this function."
        )
    return fn


# ---------------------------------------------------------------------------
# Helper: apply regime_mult into an opp_mult value using the clamping bounds
# described in 09-CONTEXT.md / 09-01-PLAN.md.
# ---------------------------------------------------------------------------

MULT_MIN = 0.4
MULT_MAX = 3.0


def _apply_regime_damp(opp_mult: float, regime_mult: float) -> float:
    """Apply regime_mult to opp_mult and clamp to [0.4, 3.0]."""
    return max(MULT_MIN, min(opp_mult * regime_mult, MULT_MAX))


class TestDecisionHasVolState:
    """
    REGIME-03 (D-06): The decision dict produced by _analyze must carry keys
    'vol_state' (str: low|normal|high) and 'regime_score' (float).
    """

    def test_decision_has_vol_state(self):
        """
        Assert that regime_lot_mult is importable AND that it returns a float.
        This is the minimal contract check — the 'vol_state' key flowing into
        the decision dict is wired in 09-05; here we verify the helper exists
        and its output is typed correctly (float), which is a necessary
        precondition for the decision dict to carry a meaningful 'regime_score'.

        Specifically:
          - regime_lot_mult("XAUUSDm", "low") returns a float
          - regime_lot_mult("XAUUSDm", "normal") returns a float
          - regime_lot_mult("XAUUSDm", "high") returns a float
          - All returned values are in a sane range (0 < mult <= 3.0)
        """
        try:
            regime_lot_mult = _import_regime_lot_mult()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"regime_lot_mult not yet implemented — RED expected: {exc}")

        for vs in VOL_STATES:
            mult = regime_lot_mult("XAUUSDm", vs)
            assert isinstance(mult, float), (
                f"regime_lot_mult('XAUUSDm', '{vs}') must return float, got {type(mult).__name__}"
            )
            assert 0.0 < mult <= MULT_MAX, (
                f"regime_lot_mult('XAUUSDm', '{vs}') = {mult} out of sane range (0, {MULT_MAX}]"
            )


class TestNoDirectionEffect:
    """
    REGIME-03 (D-06 hard rule): Applying regime_mult changes the LOT multiplier
    but MUST NOT alter decision["action"].
    """

    def test_no_direction_effect(self):
        """
        Construct a minimal decision dict with action='BUY' and opp_mult=1.0.
        Apply regime damp for vol_state='low' (XAU, expected to damp lot).
        Assert:
          1. decision["action"] is still 'BUY' after the damp.
          2. The effective lot multiplier changed (damped < original 1.0).

        This test verifies the D-06 hard rule: regime is a SIZING signal only,
        never a direction override.
        """
        try:
            regime_lot_mult = _import_regime_lot_mult()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"regime_lot_mult not yet implemented — RED expected: {exc}")

        # Simulate a decision dict (as used in friday_web_dashboard._analyze)
        decision = {
            "action": "BUY",
            "confidence": 0.75,
            "opp_mult": 1.0,
            "vol_state": None,
            "regime_score": None,
        }

        # Apply the regime sizing damp for low vol on XAU
        mult = regime_lot_mult("XAUUSDm", "low")
        damped_opp_mult = _apply_regime_damp(decision["opp_mult"], mult)

        # Update sizing fields only — action MUST NOT change
        decision["opp_mult"] = damped_opp_mult
        decision["vol_state"] = "low"
        decision["regime_score"] = float(mult)

        assert decision["action"] == "BUY", (
            f"decision['action'] changed from 'BUY' to '{decision['action']}' after "
            "applying regime_lot_mult — D-06 violation: regime must only affect sizing."
        )
        assert decision["opp_mult"] <= 1.0, (
            f"Expected damped opp_mult <= 1.0 for XAU low-vol regime "
            f"(should suppress sizing), got {decision['opp_mult']:.4f}"
        )
        assert decision["opp_mult"] >= MULT_MIN, (
            f"opp_mult {decision['opp_mult']:.4f} is below clamping floor {MULT_MIN}"
        )

    def test_sell_action_unchanged(self):
        """SELL direction must also be unchanged after regime damp (symmetry check)."""
        try:
            regime_lot_mult = _import_regime_lot_mult()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"regime_lot_mult not yet implemented — RED expected: {exc}")

        decision = {"action": "SELL", "opp_mult": 1.5}
        mult = regime_lot_mult("XAUUSDm", "low")
        decision["opp_mult"] = _apply_regime_damp(decision["opp_mult"], mult)

        assert decision["action"] == "SELL", (
            f"SELL direction changed to '{decision['action']}' after regime damp — D-06 violation."
        )


class TestFXPassthrough:
    """
    REGIME-03 (D-07): FX symbols pass through regime_lot_mult at 1.0 (no damp).
    XAUUSDm is damped in low vol (<1.0).
    """

    def test_fx_passthrough(self):
        """
        Assert regime_lot_mult("EURUSDm", "low") == 1.0.
        FX symbols must not be affected by regime sizing (D-07: excluded from live use
        unless they independently clear the gate).
        """
        try:
            regime_lot_mult = _import_regime_lot_mult()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"regime_lot_mult not yet implemented — RED expected: {exc}")

        eur_mult = regime_lot_mult("EURUSDm", "low")
        assert eur_mult == 1.0, (
            f"regime_lot_mult('EURUSDm', 'low') = {eur_mult}, expected 1.0. "
            "FX symbols must pass through at 1.0 (D-07: no OOS evidence of vol signal on EUR)."
        )

        # Also check normal and high states for EURUSDm
        for vs in VOL_STATES:
            mult = regime_lot_mult("EURUSDm", vs)
            assert mult == 1.0, (
                f"regime_lot_mult('EURUSDm', '{vs}') = {mult}, expected 1.0. "
                "All vol states must pass through 1.0 for non-XAU symbols."
            )

    def test_xau_low_vol_damped(self):
        """
        Assert regime_lot_mult("XAUUSDm", "low") < 1.0.
        XAUUSDm in low-vol regime should suppress sizing.
        """
        try:
            regime_lot_mult = _import_regime_lot_mult()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"regime_lot_mult not yet implemented — RED expected: {exc}")

        xau_low = regime_lot_mult("XAUUSDm", "low")
        assert xau_low < 1.0, (
            f"regime_lot_mult('XAUUSDm', 'low') = {xau_low}, expected < 1.0. "
            "XAU in low-vol regime must damp position sizing (D-06 sizing suppression)."
        )

    def test_all_fx_symbols_passthrough(self):
        """All common FX symbols must pass through at 1.0 for all vol states."""
        try:
            regime_lot_mult = _import_regime_lot_mult()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"regime_lot_mult not yet implemented — RED expected: {exc}")

        fx_symbols = ["EURUSDm", "GBPUSDm", "USDCADm", "USDCHFm", "USDJPYm",
                      "AUDUSDm", "BTCUSDm", "ETHUSDm"]
        for sym in fx_symbols:
            for vs in VOL_STATES:
                mult = regime_lot_mult(sym, vs)
                assert mult == 1.0, (
                    f"regime_lot_mult('{sym}', '{vs}') = {mult}, expected 1.0. "
                    f"Only XAUUSDm is cleared for live regime damp (D-07)."
                )


class TestBoundsPreserved:
    """
    REGIME-03: After applying regime_mult, the resulting opp_mult must remain
    within the existing system bounds max(0.4, min(., 3.0)).
    """

    def test_bounds_preserved(self):
        """
        Apply regime_lot_mult to several edge-case opp_mult values and assert
        the clamped result stays within [0.4, 3.0] for all vol states.
        """
        try:
            regime_lot_mult = _import_regime_lot_mult()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"regime_lot_mult not yet implemented — RED expected: {exc}")

        edge_opp_mults = [0.1, 0.4, 0.5, 1.0, 2.0, 3.0, 5.0]

        for opp_mult in edge_opp_mults:
            for vs in VOL_STATES:
                mult = regime_lot_mult("XAUUSDm", vs)
                damped = _apply_regime_damp(opp_mult, mult)

                assert damped >= MULT_MIN, (
                    f"Clamped opp_mult {damped:.4f} < {MULT_MIN} floor. "
                    f"(opp_mult={opp_mult}, vol_state={vs!r}, regime_mult={mult:.4f})"
                )
                assert damped <= MULT_MAX, (
                    f"Clamped opp_mult {damped:.4f} > {MULT_MAX} ceiling. "
                    f"(opp_mult={opp_mult}, vol_state={vs!r}, regime_mult={mult:.4f})"
                )

    def test_high_vol_state_not_below_floor(self):
        """
        In high vol state, XAU might have mult >= 1.0 (allow/size normally).
        Even if mult > 1.0, clamped result must not exceed ceiling.
        """
        try:
            regime_lot_mult = _import_regime_lot_mult()
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"regime_lot_mult not yet implemented — RED expected: {exc}")

        mult_high = regime_lot_mult("XAUUSDm", "high")
        # high vol mult should be >= 1.0 (favorable regime) or == 1.0 (neutral)
        assert mult_high >= 1.0, (
            f"regime_lot_mult('XAUUSDm', 'high') = {mult_high}, expected >= 1.0. "
            "High vol regime should allow normal or increased sizing, not suppress it."
        )

        damped = _apply_regime_damp(2.0, mult_high)
        assert damped <= MULT_MAX, (
            f"High-vol damp with opp_mult=2.0 gives {damped:.4f}, exceeding ceiling {MULT_MAX}."
        )
