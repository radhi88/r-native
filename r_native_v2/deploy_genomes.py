"""deploy_genomes.py — write the F2-b factory genomes into R Native's symbol_config format
so the program's own executor trades the OOS-optimized configs.

Maps each data/genomes/<SYM>.json (tf/stop/target/gate + OOS stats) into a ga_strategy entry
and sets it as the deployed genome. Risk is scaled small for a $100 account (lot 0.01,
1 position/symbol, modest per-symbol daily cap) so an overnight run survives instead of
blowing up on the first hour. Idempotent — re-running updates the deployed genome.

Run:  python deploy_genomes.py
"""
from __future__ import annotations
import json, time
from pathlib import Path

_V2 = Path(__file__).resolve().parent
GENO = _V2 / "data" / "genomes"
CFG_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
GENES = ["trend", "markov", "rsi", "macd", "stoch", "adx", "ema_cross", "supertrend",
         "ichimoku", "vwap", "bollinger", "cci", "williams", "obv", "roc"]


def _conf_tier(pf):
    return "HIGH" if pf >= 2.0 else "MED" if pf >= 1.5 else "LOW"


def deploy():
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    done = []
    for gf in sorted(GENO.glob("*.json")):
        try:
            g = json.loads(gf.read_text(encoding="utf-8"))
            sym = g["symbol"]; c = g["config"]; oos = g.get("oos", {})
            tf = c["tf"]; pf = oos.get("pf", 0)
            gid = f"F2B-{sym.replace('m','')[:6]}-{tf}"
            entry = {
                "id": gid, "archetype": "TREND_ATTACK", "timeframe": tf,
                "score": round(pf * 10, 1), "trades": oos.get("trades", 0),
                "win_rate": round(oos.get("win_rate", 0) * 100, 1), "profit_factor": pf,
                "total_return_pct": oos.get("net_R", 0), "max_drawdown_pct": 0.0,
                "sharpe": 0.0, "linearity": round(oos.get("folds_pos", 0) / 4.0, 2),
                "confidence": _conf_tier(pf), "active_genes": GENES,
                "sl_atr_mult": c["stop_atr"], "tp_atr_mult": c["target_atr"],
                "conf_gate": c["conf_gate"], "start_hour": 0, "end_hour": 23,
                "source": "F2B_FACTORY_OOS", "created_at": int(time.time()),
                "stats": {"trades": oos.get("trades", 0), "win_rate": round(oos.get("win_rate", 0) * 100, 1),
                          "profit_factor": pf},          # nested stats (R Native schema)
            }
            p = CFG_DIR / f"{sym}.json"
            cfg = {}
            if p.exists():
                try: cfg = json.loads(p.read_text(encoding="utf-8"))
                except Exception: cfg = {}
            # keep prior strategies, drop any old F2B entry for this sym, add the fresh one
            strat = [s for s in cfg.get("ga_strategies", []) if not str(s.get("id", "")).startswith("F2B-")]
            strat.insert(0, entry)
            cfg.update({
                "symbol": sym, "ga_strategies": strat,
                "deployed_genome": entry, "deploy_strategies": [entry],   # dicts (R Native expects dicts, not id strings)
                "best_archetype": "TREND_ATTACK", "best_tf": tf, "best_pf": pf,
                "tradeable": True, "lot": 0.01, "max_concurrent": 1,
                "daily_loss_cap_usd": 8.0,                 # tight for a $100 account
                "deployed_at": int(time.time()),
                "asset_class": cfg.get("asset_class", "auto"),
            })
            p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            done.append((sym, tf, pf))
        except Exception as e:
            print(f"  ✗ {gf.name}: {e}")
    return done


if __name__ == "__main__":
    d = deploy()
    print(f"[DEPLOY] wrote {len(d)} genomes into R Native symbol_configs:")
    for sym, tf, pf in sorted(d, key=lambda x: -x[2]):
        print(f"   ✓ {sym:10s} {tf:3s} PF {pf}  → deployed")
    print(f"[DEPLOY] lot 0.01 · 1 pos/symbol · $8 daily cap each (scaled for $100). DEMO.")
