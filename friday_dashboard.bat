@echo off
chcp 65001 >nul
cd /d C:\Users\Radhi\MT5
echo Starting FRIDAY web dashboard...
start "" http://127.0.0.1:8900
.venv\Scripts\python.exe friday_dashboard.py
pause >nul
