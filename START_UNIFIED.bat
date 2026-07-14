@echo off
REM ============================================================================
REM  START_UNIFIED.bat  —  THE single entry point for R-Native (توحيد التشغيل #1)
REM  ------------------------------------------------------------------------
REM  One command. One supervisor of record: watchdog_guard.py.
REM  It spawns + revives EVERYTHING else (the ONE brain on :5055, the executor,
REM  and the whole root-engine fleet). gold_level_sentinel is the first engine
REM  it launches, so the winner comes back first on any fall.
REM
REM  Replaces the 7 old overlapping launchers (start_r / start_brain / RNative /
REM  R_TRADER / START_FLEET). DEMO-only. Never double-spawns: if a watchdog is
REM  already up, this exits without starting a second supervisor.
REM ============================================================================
setlocal
set MT5=C:\Users\Radhi\MT5
set PYW=%MT5%\.venv\Scripts\pythonw.exe
if not exist "%PYW%" set PYW=pythonw

echo(
echo   R-Native — Unified Runtime
echo   ------------------------------------------------
echo   Supervisor : watchdog_guard.py  (sole authority)
echo   Brain      : brain_server.py     ^(:5055, single^)
echo   Executor   : friday_v3.algory.r_executor ^(magic 20260605, PAPER default^)
echo   ------------------------------------------------

REM --- single-instance guard: do not start a 2nd supervisor over the file bus ---
tasklist /v /fi "imagename eq pythonw.exe" 2>nul | find /i "watchdog_guard" >nul
if %errorlevel%==0 (
  echo   [SKIP] watchdog_guard already running — supervisor of record is up. Nothing to do.
  goto :end
)

echo   [START] launching the single supervisor...
cd /d "%MT5%"
start "" /b "%PYW%" watchdog_guard.py
echo   [OK] watchdog_guard.py started. It now owns the whole fleet.
echo        Dashboard: http://localhost:5055/r/

:end
echo(
endlocal
