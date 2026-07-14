@echo off
REM Clean shutdown of every FRIDAY R-Factory service.
cd /d C:\Users\Radhi\MT5
python -m r_native.launcher --stop
echo.
pause
