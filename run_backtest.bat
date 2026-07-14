@echo off
cd /d C:\Users\Radhi\MT5
python scripts\ict_sweep_trader.py --symbol XAUUSDm --bars 500 --backtest > backtest_output.txt 2>&1
echo Done. >> backtest_output.txt
