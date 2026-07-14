@echo off
REM ============================================================
REM  R-Native init.bat — get your bearings + basic health check
REM  Usage:  init.bat          (checks only)
REM          init.bat start    (checks + launch fleet)
REM ============================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo === [1/4] git state =========================================
git log --oneline -5 2>nul || echo   (!) git unavailable or repo broken
git status -s 2>nul | findstr /r "^.M ^M ^A ^D" >nul && echo   (i) uncommitted changes present

echo === [2/4] agent harness =====================================
if exist feature_list.json (
  python -c "import json;d=json.load(open('feature_list.json',encoding='utf-8'))['features'];p=sum(1 for f in d if f['passes']);print(f'  features: {len(d)} total, {p} passing, {len(d)-p} remaining')" 2>nul || echo   (!) python/json check failed
) else (
  echo   (!) feature_list.json missing
)
if exist claude-progress.txt (
  echo   claude-progress.txt: found — READ IT FIRST
) else (
  echo   (!) claude-progress.txt missing
)

echo === [3/4] health checks =====================================
curl -s -m 3 -o nul -w "  brain_server :5055  -> HTTP %%{http_code}\n" http://localhost:5055/ 2>nul || echo   brain_server :5055  -^> DOWN
curl -s -m 3 -o nul -w "  tv_bridge    :8025  -> HTTP %%{http_code}\n" http://localhost:8025/ 2>nul || echo   tv_bridge    :8025  -^> DOWN
tasklist /fi "imagename eq terminal64.exe" 2>nul | find /i "terminal64" >nul && echo   MT5 terminal        -^> RUNNING || echo   MT5 terminal        -^> NOT RUNNING

echo === [4/4] next step =========================================
echo   1. type claude-progress.txt
echo   2. pick ONE feature with "passes": false from feature_list.json
echo   3. python sync_to_repo.py --push   (when done, secret-scan enforced)

if /i "%1"=="start" (
  echo.
  echo === launching fleet ===
  start "" START_FLEET.bat
)
endlocal
