@echo off
:: DNA EVOLVE v7.2 — EA Monitor Launcher
:: Starts ea_monitor.py and opens the dashboard in the browser

title DNA EA Monitor

:: Set FRIDAY env vars
set FRIDAY_PROJECT_ROOT=C:\Users\Radhi\MT5
set FRIDAY_ROOT=C:\Users\Radhi\MT5
set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY%

cd /d C:\Users\Radhi\MT5

echo.
echo  ============================================
echo   DNA EVOLVE v7.2 — EA Monitor
echo   Dashboard → http://localhost:7799
echo  ============================================
echo.

:: Check API key
if "%ANTHROPIC_API_KEY%"=="" (
    echo  [WARN] ANTHROPIC_API_KEY not set — Claude suggestions disabled
    echo  Set it with: set ANTHROPIC_API_KEY=sk-ant-...
    echo.
)

:: Open browser after a short delay (runs in background)
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:7799"

:: Run monitor using venv
.venv\Scripts\python.exe ea_monitor.py

pause
