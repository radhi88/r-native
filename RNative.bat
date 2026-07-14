@echo off
REM ─────────────────────────────────────────────────────────────────
REM  FRIDAY R Factory — Master Launcher
REM
REM  Double-click to start the entire stack:
REM    brain_server + r_executor (LIVE) + 3 daemons + UI
REM  Then watches everything and respawns anything that crashes.
REM
REM  Flags (pass on command line if you need them):
REM    --paper       PAPER mode (no real orders)
REM    --bootstrap   Scan top 15 symbols × 4 TFs × 4 archetypes first
REM    --skip-ui     Headless (no window)
REM    --stop        Kill everything
REM ─────────────────────────────────────────────────────────────────
cd /d C:\Users\Radhi\MT5
title FRIDAY R Factory — Supervisor
python -m r_native.launcher %*
echo.
echo Launcher exited. Press any key to close this window.
pause >nul
