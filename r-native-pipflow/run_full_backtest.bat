@echo off
chcp 65001 > nul
title R-Native v2 — Full Backtest Pipeline
color 0A

SET VENV_PY=C:\Users\Radhi\MT5\.venv\Scripts\python.exe
SET REPO=C:\Users\Radhi\MT5\r-native-pipflow

cd /d "%REPO%"

echo ==========================================
echo  R-Native v2 — Full Backtest Pipeline
echo  Using: %VENV_PY%
echo ==========================================
echo.

echo [1/5] Creating data directory...
if not exist "data" mkdir data
echo  OK

echo.
echo [2/5] Exporting 8000 M3 bars from MT5 (XAUUSDm)...
"%VENV_PY%" tools/export_mt5_bars.py --symbol XAUUSDm --tf M3 --bars 8000 --out data/gold_m3_live.json
if %errorlevel% neq 0 (
    echo ERROR: Export failed. Is MT5 running and XAUUSDm visible in Market Watch?
    pause
    exit /b 1
)

echo.
echo [3/5] Stoch Reversion backtest WITH SL...
"%VENV_PY%" tools/backtest_stoch_on_live_mt5.py --json data/gold_m3_live.json --use-sl 1 --out data/gold_real.png
if %errorlevel% neq 0 echo WARNING: backtest with SL failed

echo.
echo [4/5] Stoch Reversion backtest WITHOUT SL...
"%VENV_PY%" tools/backtest_stoch_on_live_mt5.py --json data/gold_m3_live.json --use-sl 0 --out data/gold_no_sl.png
if %errorlevel% neq 0 echo WARNING: backtest no-SL failed

echo.
echo [5/5] Running 119 unit tests to confirm no regressions...
"%VENV_PY%" tests/run_all.py
if %errorlevel% neq 0 (
    echo ERROR: Some tests FAILED!
) else (
    echo  All tests passed.
)

echo.
echo ==========================================
echo  DONE — Check data/ for PNG charts
echo  data/gold_real.png    (with SL)
echo  data/gold_no_sl.png   (no SL)
echo ==========================================
pause
