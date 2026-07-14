@echo off
title SMC Full System
set "ROOT=C:\Users\Radhi\MT5"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"

echo.
echo ============================================
echo   SMC Gold EA - Full System Launcher
echo ============================================
echo.

:: Check Ollama
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Ollama is not running!
    echo   Start it with: ollama serve
    echo   Then:          ollama pull llama3.2
    echo.
    echo Continuing without LLM support...
    echo.
) else (
    echo [OK] Ollama is running
)

:: Start dashboard if not already running
netstat -ano | findstr ":5050 " | findstr "LISTENING" >nul
if errorlevel 1 (
    start "SMC Dashboard" /b "%PYW%" "%ROOT%\dashboard\smc_dashboard.py"
    timeout /t 2 /nobreak > nul
    echo [OK] Dashboard started at http://localhost:5050
) else (
    echo [OK] Dashboard already running at http://localhost:5050
)

:: Open browser
start http://localhost:5050

:: Start EA monitor if not already running
netstat -ano | findstr ":7799 " | findstr "LISTENING" >nul
if errorlevel 1 (
    start "EA Monitor 7799" /b "%PYW%" "%ROOT%\ea_monitor.py"
    timeout /t 1 /nobreak > nul
    echo [OK] EA monitor started at http://localhost:7799
) else (
    echo [OK] EA monitor already running at http://localhost:7799
)

:: Run unified signal bridge; writes agents\unified_signal.json every 0.5s
echo.
echo Starting unified signal bridge (0.5s)...
wmic process where "CommandLine like '%%unified_signal_bridge.py%%' or CommandLine like '%%unified_orchestrator.py%% --loop%%'" get ProcessId 2>nul | findstr /r "[0-9]" >nul
if errorlevel 1 (
    start "Unified Signal Bridge 0.5s" /b "%PYW%" "%ROOT%\agents\unified_signal_bridge.py" --loop --interval 0.5
) else (
    echo [OK] Unified signal bridge already running
)

:: Run fast autopilot in sub-second loop
echo.
echo Starting fast autopilot loop (0.5s)...
wmic process where "CommandLine like '%%fast_autopilot_loop.py%%'" get ProcessId 2>nul | findstr /r "[0-9]" >nul
if errorlevel 1 (
    start "Fast Autopilot 0.5s" /b "%PYW%" "%ROOT%\agents\fast_autopilot_loop.py" --interval 0.5
) else (
    echo [OK] Fast autopilot already running
)

:: Run Unusual Whales bridge; it stays disabled until UW_API_KEY is set
echo Starting Unusual Whales bridge...
wmic process where "CommandLine like '%%unusual_whales_bridge.py%%'" get ProcessId 2>nul | findstr /r "[0-9]" >nul
if errorlevel 1 (
    start "Unusual Whales Bridge" /b "%PYW%" "%ROOT%\agents\unusual_whales_bridge.py" --loop --interval 15
) else (
    echo [OK] Unusual Whales bridge already running
)

:: Run agents + PlutoBrain in continuous loop
echo Starting PlutoBrain agent loop (1s)...
wmic process where "CommandLine like '%%orchestrator.py%% --loop%%'" get ProcessId 2>nul | findstr /r "[0-9]" >nul
if errorlevel 1 (
    start "SMC Agents PlutoBrain Loop" /b "%PYW%" "%ROOT%\agents\orchestrator.py" --loop --interval 1
) else (
    echo [OK] PlutoBrain agent loop already running
)

:: Maintain VS Code PID bridge for Claude terminal
echo Starting VS Code PID bridge (PID 2804)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-CimInstance Win32_Process | Where-Object { ($_.Name -like 'python*' -or $_.Name -eq 'py.exe') -and $_.CommandLine -like '*vs_pid_bridge.py*--loop*' }; if ($p) { exit 0 } exit 1" >nul 2>&1
if errorlevel 1 (
    if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PY%' -ArgumentList '\"%ROOT%\agents\vs_pid_bridge.py\" --pid 2804 --loop --interval 10 --quiet' -WorkingDirectory '%ROOT%' -WindowStyle Hidden"
) else (
    echo [OK] VS Code PID bridge already running
)

echo.
echo ============================================
echo  System is running!
echo  Dashboard:  http://localhost:5050
echo  Monitor:    http://localhost:7799
echo  Unified:    agents\unified_signal.json every 0.5s
echo  Autopilot:  live-control every 0.5s
echo  Agents:     PlutoBrain loop every 1s
echo ============================================
echo.
pause
