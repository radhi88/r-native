"""
FRIDAY Auto Trader - التشغيل التلقائي عند 连接 MT5

يعمل تلقائياً عند تشغيل MT5 سواء كان حساب حقيقي أو ديمو:
- يكتشف نوع الحساب (ديمو/حقيقي)
- يحلل السوق كل فترة محددة
- يدخل صفقات تلقائياً

Usage:
    python friday_auto_trader.py                    # تشغيل تلقائي
    python friday_auto_trader.py --profile scalping  # تحديد الاستراتيجية
    python friday_auto_trader.py --poll-seconds 30   # تحديد الفترة
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import tensorflow as tf

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.ai_brain import TradingBrain
from mt5_ai.config import (
    DEFAULT_LOT,
    FEATURE_COLUMNS,
    LOG_DIR,
    MODEL_PATH,
    MT5_SYMBOL,
    SCALER_PATH,
    SEQ_LEN,
)
from mt5_ai.execution import DemoMT5Executor, PaperExecutor, SafeMT5Executor
from mt5_ai.market_structure import add_market_structure
from mt5_ai.mt5_gateway import MT5Gateway


class AutoTrader:
    def __init__(self, profile="scalping", poll_seconds=30, auto_live=True):
        self.profile = profile
        self.poll_seconds = poll_seconds
        self.auto_live = auto_live
        
        # تحميل النموذج
        print(f"📂 Loading model: {MODEL_PATH}")
        self.model = tf.keras.models.load_model(MODEL_PATH, compile=False)
        self.scaler = joblib.load(SCALER_PATH)
        self.brain = TradingBrain(model=self.model, profile_name=profile)
        
        # الاتصال بـ MT5
        self.gateway = MT5Gateway()
        self.gateway.initialize()
        
        # تحديد نوع الحساب
        self.account = self.gateway.account_snapshot()
        self.is_demo = self.gateway.is_demo_account(self.account)
        self.account_type = "DEMO" if self.is_demo else "LIVE"
        
        print(f"✅ Connected to MT5")
        print(f"   Account: {self.account.get('login')}")
        print(f"   Server: {self.account.get('server')}")
        print(f"   Balance: {self.account.get('balance')} {self.account.get('currency', 'USD')}")
        print(f"   Type: {self.account_type}")
        
        # المحExecutors
        self.paper_executor = PaperExecutor()
        self.demo_executor = DemoMT5Executor(gateway=self.gateway)
        self.live_executor = SafeMT5Executor(gateway=self.gateway, allow_live=auto_live)
        
        # سجل العمليات
        self.log_file = LOG_DIR / "auto_trades.jsonl"
        self.stats = {
            "started": datetime.now(timezone.utc).isoformat(),
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "account_type": self.account_type,
        }

    def log(self, event_type, data):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            **data,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def fetch_data(self, symbol, bars=500):
        df = self.gateway.fetch_rates(symbol, "M1", bars)
        return df

    def analyze(self, symbol):
        df = self.fetch_data(symbol)
        enriched = add_market_structure(df)
        
        seq = enriched[FEATURE_COLUMNS].tail(SEQ_LEN).to_numpy(dtype=np.float32)
        seq = self.scaler.transform(seq)
        sequence = seq.reshape(1, SEQ_LEN, len(FEATURE_COLUMNS))
        
        probability = float(np.asarray(self.model.predict(sequence, verbose=0)).squeeze())
        spread = float(enriched["spread"].iloc[-1]) if "spread" in enriched.columns else None
        
        decision = self.brain.decide(
            df=enriched,
            sequence=sequence,
            probability=probability,
            spread=spread,
            ignore_spread=False,
        ).to_dict()
        
        decision["close"] = float(enriched["close"].iloc[-1])
        decision["symbol"] = symbol
        
        return decision

    def execute(self, decision):
        action = decision.get("action")
        if action not in {"BUY", "SELL"}:
            return None
        
        symbol = decision.get("symbol", MT5_SYMBOL)
        side = action
        price = decision["close"]
        lot = DEFAULT_LOT
        
        # تحديد SL/TP
        sl_pct, tp_pct = 0.0010, 0.0015
        if side == "BUY":
            sl = price * (1 - sl_pct)
            tp = price * (1 + tp_pct)
        else:
            sl = price * (1 + sl_pct)
            tp = price * (1 - tp_pct)
        
        # التنفيذ حسب نوع الحساب
        if self.is_demo:
            result = self.demo_executor.execute(
                symbol=symbol, side=side, price=price, lot=lot, sl=sl, tp=tp
            )
            mode = "DEMO"
        else:
            if self.auto_live:
                result = self.live_executor.execute(
                    symbol=symbol, side=side, price=price, lot=lot, sl=sl, tp=tp
                )
                mode = "LIVE"
            else:
                result = self.paper_executor.execute(
                    symbol=symbol, side=side, price=price, lot=lot
                )
                mode = "PAPER (LIVE blocked)"
        
        self.stats["trades"] += 1
        
        trade_info = {
            "mode": mode,
            "action": action,
            "symbol": symbol,
            "price": price,
            "lot": lot,
            "result": result,
            "decision": decision,
        }
        
        self.log("auto_trade", trade_info)
        
        return {
            "executed": result.get("sent", False),
            "mode": mode,
            **trade_info,
        }

    def run(self):
        symbol = MT5_SYMBOL
        print(f"\n🚀 Starting Auto Trader")
        print(f"   Symbol: {symbol}")
        print(f"   Profile: {self.profile}")
        print(f"   Poll: {self.poll_seconds}s")
        print(f"   Account: {self.account_type}")
        print(f"   Auto Live: {self.auto_live}")
        print("-" * 50)
        
        try:
            while True:
                try:
                    # تحليل السوق
                    decision = self.analyze(symbol)
                    
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ", end="")
                    print(f"{decision.get('action')} ", end="")
                    print(f"{decision.get('symbol')} @ {decision.get('close'):.2f} ", end="")
                    print(f"({decision.get('probability'):.2%}) ", end="")
                    print(f"- {decision.get('reason')}")
                    
                    # تنفيذ الصفقة
                    if decision.get("action") in {"BUY", "SELL"}:
                        result = self.execute(decision)
                        if result and result.get("executed"):
                            print(f"   ✅ Executed: {result['mode']}")
                        elif result:
                            print(f"   ❌ Failed: {result.get('result', {}).get('reason', 'unknown')}")
                    else:
                        print(f"   ⏸️  No trade")
                    
                except Exception as e:
                    print(f"   ⚠️  Error: {e}")
                    self.log("error", {"error": str(e)})
                
                # انتظار للدورة التالية
                time.sleep(self.poll_seconds)
                
        except KeyboardInterrupt:
            print("\n🛑 Stopped by user")
        finally:
            self.shutdown()

    def shutdown(self):
        self.gateway.shutdown()
        print(f"\n📊 Stats: {self.stats['trades']} trades executed")
        print(f"   Account: {self.account_type}")


def main():
    parser = argparse.ArgumentParser(description="FRIDAY Auto Trader")
    parser.add_argument("--profile", default="scalping", help="Strategy profile")
    parser.add_argument("--poll-seconds", type=int, default=30, help="Poll interval")
    parser.add_argument("--symbol", default=MT5_SYMBOL, help="Trading symbol")
    parser.add_argument("--no-auto-live", action="store_true", help="Disable auto live trading")
    args = parser.parse_args()

    print("=" * 60)
    print("🤖 FRIDAY AUTO TRADER")
    print("=" * 60)
    
    trader = AutoTrader(
        profile=args.profile,
        poll_seconds=args.poll_seconds,
        auto_live=not args.no_auto_live,
    )
    trader.run()


if __name__ == "__main__":
    main()