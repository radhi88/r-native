@echo off
chcp 65001 >nul
set "ROOT=C:\Users\Radhi\MT5"
set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"

:: أوقف الحارس القديم و cloudflared (بدون مسّ الجسر)
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tv_tunnel_keeper.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
powershell -NoProfile -Command "Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"
timeout /t 3 /nobreak >nul

:: احذف ملف الرابط القديم ليُكتب رابط جديد نظيف
del /q "%ROOT%\data\r_native\tv_tunnel.json" 2>nul

:: أطلق الحارس المدمج (جسر + نفق) windowless
start "TV Keeper" /b "%PYW%" "%ROOT%\tv_tunnel_keeper.py"
