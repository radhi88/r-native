@echo off
chcp 65001 >nul
title TradingView Bridge LIVE
setlocal
set "ROOT=C:\Users\Radhi\MT5"
set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================
echo   TradingView -^> MT5  Bridge  (LIVE)
echo ============================================
echo.

:: 1) Confirm the bridge is listening on :8025
echo [1/4] Checking bridge on :8025 ...
powershell -NoProfile -Command ^
  "try { $r = Invoke-RestMethod -Uri 'http://localhost:8025/tv' -TimeoutSec 5; Write-Host '[OK] Bridge alive:' ($r | ConvertTo-Json -Compress) } catch { Write-Host '[WARN] Bridge not answering - launching it...'; exit 1 }"
if errorlevel 1 (
    start "TV Bridge" /b "%PYW%" "%ROOT%\tradingview_bridge.py"
    timeout /t 3 /nobreak >nul
)
echo.

:: 2) Start the cloudflared tunnel keeper (windowless, self-restarting)
echo [2/4] Starting cloudflared tunnel keeper ...
wmic process where "CommandLine like '%%tv_tunnel_keeper.py%%'" get ProcessId 2>nul | findstr /r "[0-9]" >nul
if errorlevel 1 (
    start "TV Tunnel" /b "%PYW%" "%ROOT%\tv_tunnel_keeper.py"
    echo [OK] Tunnel keeper launched. Waiting for public URL...
) else (
    echo [OK] Tunnel keeper already running.
)

:: Wait up to 30s for the public URL to appear
set "URLFILE=%ROOT%\data\r_native\tv_tunnel.json"
for /l %%i in (1,1,15) do (
    if exist "%URLFILE%" goto :haveurl
    timeout /t 2 /nobreak >nul
)
:haveurl
echo.
echo [3/4] Public webhook URL:
if exist "%URLFILE%" (
    powershell -NoProfile -Command "$j = Get-Content -Raw '%URLFILE%' | ConvertFrom-Json; Write-Host ('   ' + $j.webhook)"
) else (
    echo    [WARN] URL not ready yet - check %URLFILE% in a few seconds.
)
echo.

:: 3) Self-test: correct secret (expect ok:true) and wrong secret (expect 403)
echo [4/4] Running secret tests against localhost:8025 ...
echo.
echo    -- Correct secret (expect accepted) --
powershell -NoProfile -Command ^
  "$body = @{secret='<TV_BRIDGE_SECRET>'; action='ping'; symbol='TESTONLY'} | ConvertTo-Json; try { $r = Invoke-RestMethod -Uri 'http://localhost:8025/tv' -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 5; Write-Host ('   [PASS] Accepted: ' + ($r | ConvertTo-Json -Compress)) } catch { Write-Host ('   [FAIL] ' + $_.Exception.Message) }"
echo.
echo    -- Wrong secret (expect 403 rejected) --
powershell -NoProfile -Command ^
  "$body = @{secret='WRONG_SECRET'; action='ping'; symbol='TESTONLY'} | ConvertTo-Json; try { Invoke-RestMethod -Uri 'http://localhost:8025/tv' -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 5 | Out-Null; Write-Host '   [FAIL] wrong secret was NOT rejected!' } catch { if ($_.Exception.Response.StatusCode.value__ -eq 403) { Write-Host '   [PASS] Rejected with 403 as expected.' } else { Write-Host ('   [?] ' + $_.Exception.Message) } }"
echo.
echo ============================================
echo  Done. Keep this window's processes running.
echo  The guardian (watchdog_guard.py) will also
echo  keep the bridge + tunnel alive from now on.
echo ============================================
echo.
pause
