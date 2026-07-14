@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title FRIDAY War Room - VIEWER (execution runs 24/7 under watchdog)
cd /d C:\Users\Radhi\MT5
.venv\Scripts\python.exe army_warroom.py --view
echo.
echo War room closed - press any key
pause >nul
