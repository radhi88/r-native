import sys, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
warnings.filterwarnings('ignore')

from mt5_ai.mt5_gateway import MT5Gateway
from mt5_ai.market_structure import add_market_structure
from mt5_ai.agents.market_analyst_agent import MarketAnalystAgent
from mt5_ai.agents.liquidity_hunter_agent import LiquidityHunterAgent
from mt5_ai.agents.entry_agent import EntryAgent

gw = MT5Gateway()
gw.initialize()
df = gw.fetch_rates('XAUUSDm', 'M1', 500)
print(f"Bars fetched : {len(df)}")
print(f"Last close   : {df.close.iloc[-1]:.2f}")

enriched = add_market_structure(df)
analyst  = MarketAnalystAgent('XAUUSDm')
hunter   = LiquidityHunterAgent('XAUUSDm')
entry    = EntryAgent('XAUUSDm')

ctx  = analyst.extract_context(enriched)
lctx = hunter.analyze(enriched, ctx['atr'])

atr_pts = ctx['atr'] * ctx['price']

print()
print("=== SMC Market Context ===")
print(f"Price   : {ctx['price']:.2f}")
print(f"ATR     : {ctx['atr']:.6f}  (~{atr_pts:.2f} USD)")
print(f"BOS up  : {ctx['bos_up']}   BOS down: {ctx['bos_down']}")
print(f"CHOCH up: {ctx['choch_up']}  CHOCH dn: {ctx['choch_down']}")
print(f"OB bull : {ctx['in_bullish_ob']}  OB bear: {ctx['in_bearish_ob']}")
print(f"FVG bull: {ctx['bullish_fvg']}  FVG bear: {ctx['bearish_fvg']}")
print(f"SMC buy={ctx['smc_buy_score']}  sell={ctx['smc_sell_score']}  bias={ctx['smc_bias']}")
print(f"Trend   : {ctx['trend']:.6f}")
print()
print("=== Liquidity Context ===")
print(f"SSL sweep active : {lctx['ssl_sweep_active']}  ({lctx['ssl_sweep_bars_ago']} bars ago)")
print(f"BSL sweep active : {lctx['bsl_sweep_active']}  ({lctx['bsl_sweep_bars_ago']} bars ago)")
print(f"BSL target (TP buy)  : {lctx['bsl_target']}")
print(f"SSL target (TP sell) : {lctx['ssl_target']}")
print(f"EQH levels : {[round(x,2) for x in lctx['eqh_levels'][-5:]]}")
print(f"EQL levels : {[round(x,2) for x in lctx['eql_levels'][:5]]}")
print()
print("=== Structure Targets ===")
print(f"Swing highs (TP BUY)  : {[round(x,2) for x in ctx['swing_highs']]}")
print(f"Swing lows  (TP SELL) : {[round(x,2) for x in ctx['swing_lows']]}")

# هل يوجد إشارة الآن؟
# نموذج وهمي مؤقتاً (0.65)
for prob in [0.65, 0.72, 0.78, 0.35, 0.28, 0.22]:
    sig = entry.evaluate(ctx, lctx, prob)
    if sig:
        print()
        print(f"!!! SIGNAL: {sig.side}  reason={sig.reason}  prob={prob}")
        break
else:
    print()
    print("No entry signal with current SMC setup (normal — waiting for sweep + BOS confluence)")

gw.shutdown()
