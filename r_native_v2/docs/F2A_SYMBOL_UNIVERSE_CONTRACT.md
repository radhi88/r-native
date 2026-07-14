# F2-a — Single Symbol Universe (DESIGN ONLY)

> **Status:** DESIGN ONLY — no engine edited. Resolves G1 (4+ divergent hardcoded symbol lists).
> Foundation for F2-b (discovery) and F2-c (TF×bar gauntlet). Date 2026-06-06.
> **Rails:** analyze/design · parallel-run before any engine swap · PAPER stays PAPER ·
> `enabled` defaults false for new symbols until OOS gate (F2-c) · never `magic 0`.

## 1. Problem (from F1 G1)
The tradable symbol set is hardcoded in ≥4 places, each different:
- `genome_academy.SYMBOLS` (7): XAU,EUR,GBP,GBPJPY,BTC,USDJPY,XAG
- `brain_v1.SYMBOLS`, `chart_signal_writer.DEFAULT_SYMBOLS` (5), `footprint_feeder.SYMBOLS` (6)
- live personas exist for 11 (adds AUD,NZD,CAD,CHF,EURJPY).
Adding/removing a market = editing many files; lists drift; "enter any market" impossible cleanly.

## 2. Proposed single source: `r_native_v2/data/symbol_universe.json`
```json
{
  "version": 1,
  "updated_ts": 0,
  "symbols": [
    {
      "symbol": "XAUUSDm", "market": "MT5", "asset_class": "metal",
      "enabled": true,            // may this symbol trade? (false until OOS-cleared)
      "always_open": false,       // 24/7? (true for crypto; FX/metals false)
      "point": 0.01, "digits": 2, // broker metadata (filled by discovery, F2-b)
      "tfs": ["M5","M15"],        // timeframes this symbol is gauntleted/traded on (F2-c)
      "source": "seed",           // seed | discovered | manual
      "added_ts": 0, "notes": ""
    }
  ]
}
```
Seed = union of the 4 lists + 11 personas (each `enabled` set to its current real state; crypto
`always_open:true`, FX/metals false — fixes INT-01 EUR by setting EUR `always_open:false`).

## 3. Shared loader: `runtime/shared/symbol_universe.py` (the ONLY reader)
```
get_symbols(market=None, enabled_only=True, always_open=None) -> list[dict]
get_symbol(symbol) -> dict | None
trading_symbols() -> [sym, ...]      # enabled_only convenience
```
- Reads `symbol_universe.json`; **fail-safe:** if missing/corrupt, returns a built-in DEFAULT
  (today's academy list) so nothing breaks. Never writes (writes are F2-b discovery / manual).
- Every engine imports this instead of a local hardcoded list.

## 4. Migration (each engine swap = its own gated step, parallel-run)
1. **F2-a.1:** create `symbol_universe.json` (seed) + `symbol_universe.py` loader + unit check.
   No engine wired yet — zero behavior change. (This is the only step I implement after approval.)
2. **F2-a.2..n (later, one ASK each):** replace the hardcoded list in ONE engine with the loader;
   **parallel-run:** assert `set(loader)==set(old_hardcoded)` for that engine before/after → identical
   set ⇒ safe; commit; next engine. Order: lowest-risk first (chart_signal_writer, footprint_feeder),
   highest-risk last (genome_academy, brain_v1).
3. Hub `/state` surfaces the universe (read-only) so the user SEES every symbol + enabled/always_open.

## 5. Safety / honesty
- `enabled:false` ⇒ a symbol is in the universe (visible) but **does not trade** — new symbols from F2-b
  discovery land disabled until they clear the F2-c OOS gauntlet (Phase-9 ethos: prove before trade).
- The loader changes NOTHING on its own; only engine-by-engine swaps (parallel-run verified) change behavior.
- PAPER stays PAPER; live order_send stays gold_live(99791)/btc_live(99792, +99793 swing) only.

## 6. Open questions for Claude
1. Approve `symbol_universe.json` schema + `symbol_universe.py` fail-safe loader (F2-a.1 only first)?
2. Seed `enabled` policy: seed ONLY the currently-traded set as enabled, all others enabled:false? (safer)
3. Add btc 99793 (swing H1) + 99792 (scalp M5) to the hub's read-only live_traders view in the same pass?
4. Confirm migration order (low-risk engines first; genome_academy/brain_v1 last), each its own ASK + parallel-run.
