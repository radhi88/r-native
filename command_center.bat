@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title FRIDAY Command Center - كل شيء في شاشة واحدة
cd /d C:\Users\Radhi\MT5
.venv\Scripts\python.exe command_center.py
echo.
echo Command center closed - press any key
pause >nul
