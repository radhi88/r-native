# Gold M3 Stochastic-Reversion EA — install guide

The chart screenshot strategy turned into a working MT5 EA + Python
backtest. **Built from your screenshot — not authorized advice. Test on
demo first.**

## 1 · What you have

| File | Purpose |
|---|---|
| `mql5_templates/Stoch_Reversion_M3.mq5` | The EA. Compile + attach to a XAUUSD M3 chart. |
| `strategies/stoch_reversion.py`         | Pure-Python strategy + backtest engine. |
| `tests/test_stoch_reversion.py`         | 11 unit tests (all green). |

## 2 · Install the EA on your MT5

1. Open MetaEditor (`F4` from MT5).
2. `File → Open Data Folder → MQL5 → Experts`.
3. Drop `Stoch_Reversion_M3.mq5` into that folder.
4. Back in MetaEditor, double-click it, press `F7` to compile (should
   read "0 error(s), 0 warning(s)").
5. In MT5: refresh the Navigator (`Ctrl+N`), find **Stoch_Reversion_M3**
   under Expert Advisors, drag it onto a **XAUUSD M3** chart.
6. In the dialog: tick **Allow algo trading**, click OK.
7. Top-right corner should show a smiley face — EA is live.

### Inputs (defaults match the screenshot)

```
OB_Heavy  90   ── SELL when %D crosses down through 90
OB_Light  85   ── SELL when %D crosses down through 85
OS_Heavy  10   ── BUY  when %D crosses up through 10
OS_Light  15   ── BUY  when %D crosses up through 15
Midline   50   ── exit all when %D crosses 50
Lot       0.01
MaxTrades 2    ── pyramid cap per side
UseSL     true ── set FALSE to mirror screenshot exactly (no SL)
AtrSlMult 2.5  ── if UseSL: SL = 2.5 × ATR(14) beyond entry
Magic     20260605
```

## 3 · Verify entries

After attach, the EA prints to the **Experts** tab on every bar event:

```
OPEN  SELL  tier=H  XAUUSD@4568.75  SL=4576.20  D=89.2
OPEN  SELL  tier=L  XAUUSD@4535.13  SL=4541.80  D=84.5
CLOSE #123  reason=D 53.1 -> 48.7 cross 50
```

You see ▼ red arrows above SELL entries and ▲ green arrows below BUY
entries on the chart automatically (MT5 default markers).

## 4 · What the backtest shows

`python /tmp/backtest_stoch_rev.py` (or write your own using
`strategies.stoch_reversion.backtest()`) on synthetic gold M3 bars:

- **46 trades · 39% WR · PF 0.51 · net -$28.65** on 600 bars
- TP_midline hits 23×, SL hits 22×, EOD 1
- Worst trade -$3.16, best +$3.53

**Honest read**: the raw strategy is a coin-flip on these synthetics
because mean-reversion bleeds during trends. The PNG attached to the chat
shows every entry/exit so you can audit visually.

## 5 · What to improve (already on the branch)

- Wire `live_indicators.adx_filter` to skip entries when ADX > 25
  (avoid trending markets that punish mean-reversion).
- Use `sl_tp_resolver.resolve_sl_tp` with `sl_anchor_smc_swing` so the
  stop sits beyond the local liquidity, not 2.5 × ATR.
- Pass each closed trade through `combo_fitness.record_smc_trade` so the
  GA learns which contexts ("idm_swept_before", "bos_aligned") this
  Stochastic setup actually wins in.

These are one-liner integrations — say the word and I'll wire them.

## 6 · Safety

- Demo first. The screenshot original had **no SL**; the EA defaults to
  one but you can flip `UseSL=false` to reproduce exactly what you saw.
- The R magic (`20260605`) means the rest of the R-Native stack
  (governance, rollback, fitness recorder) will see and learn from
  these trades automatically.
