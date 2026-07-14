@echo off
chcp 65001 > nul
title R-Native Setup + Tests
echo ==========================================
echo  R-Native v2 — Setup and Test Runner
echo ==========================================
echo.

cd /d "C:\Users\Radhi\MT5\r-native-pipflow"
echo [1/4] Installing Python dependencies...
pip install numpy matplotlib flask requests MetaTrader5 2>&1
echo.

echo [2/4] Verifying imports...
python -c "import numpy, matplotlib, flask, requests; print('  deps ok')" 2>&1
python -c "import MetaTrader5; print('  MetaTrader5 ok')" 2>&1
echo.

echo [3/4] Running 142 unit tests...
python tests/run_all.py 2>&1
echo.

echo [4/4] Done. Check results above.
echo ==========================================
pause
