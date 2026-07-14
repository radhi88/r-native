@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title FRIDAY Evolution Monitor - التطوّر الحيّ
cd /d C:\Users\Radhi\MT5
.venv\Scripts\python.exe evolution_monitor.py
echo.
echo Evolution monitor closed - press any key
pause >nul
