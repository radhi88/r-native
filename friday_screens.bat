@echo off
chcp 65001 >nul
cd /d C:\Users\Radhi\MT5
echo Opening FRIDAY live screens (3 windows)...
start "FRIDAY - Command Center" cmd /k ".venv\Scripts\python.exe command_center.py"
start "FRIDAY - Evolution" cmd /k ".venv\Scripts\python.exe evolution_monitor.py"
start "FRIDAY - Agent Minds" cmd /k ".venv\Scripts\python.exe agent_minds.py"
echo Done - 3 windows opened. Close this launcher.
timeout /t 3 >nul
