@echo off
chcp 65001 > nul
title R-Native v2 — Tests + brain_server
echo ==========================================
echo  R-Native v2 — Using MT5 venv Python
echo ==========================================
echo.

SET VENV_PY=C:\Users\Radhi\MT5\.venv\Scripts\python.exe
SET REPO=C:\Users\Radhi\MT5\r-native-pipflow

cd /d "%REPO%"

echo [1/3] Verifying venv imports...
"%VENV_PY%" -c "import numpy, matplotlib, flask, requests; print('  deps ok')"
"%VENV_PY%" -c "import MetaTrader5; print('  MetaTrader5 ok')"
echo.

echo [2/3] Running 142 unit tests...
"%VENV_PY%" tests/run_all.py
echo.

echo [3/3] Tests complete.
echo.
echo ==========================================
echo  To start brain_server on port 5055, run:
echo  %VENV_PY% brain_server.py
echo ==========================================
pause
