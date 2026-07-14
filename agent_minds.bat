@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title FRIDAY Agent Minds - دقّة القراءات
cd /d C:\Users\Radhi\MT5
.venv\Scripts\python.exe agent_minds.py
echo.
pause >nul
