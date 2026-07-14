@echo off
chcp 65001 >nul 2>&1
title FRIDAY System Check
cd /d C:\Users\Radhi\MT5

set FRIDAY_PROJECT_ROOT=C:\Users\Radhi\MT5
set FRIDAY_ROOT=C:\Users\Radhi\MT5
set JARVIS_PROJECT_ROOT=C:\Users\Radhi\MT5
set QADER_ROOT=C:\Users\Radhi\MT5
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

echo.
echo ====================================================
echo   FRIDAY JARVIS — System Check
echo ====================================================
echo.

REM Check Python
.venv\Scripts\python.exe --version
echo.

REM Check voice dependencies
echo [1] Checking voice dependencies...
.venv\Scripts\python.exe -c "
import importlib.util
packages = ['sounddevice','faster_whisper','edge_tts','pyttsx3','webrtcvad','MetaTrader5','numpy','requests','yaml','fastapi','uvicorn','ollama']
missing = []
print()
for p in packages:
    name = p.replace('-','_').replace('.','_')
    found = importlib.util.find_spec(name) is not None
    mark = 'OK  ' if found else 'MISS'
    print(f'  [{mark}]  {p}')
    if not found:
        missing.append(p)
print()
if missing:
    print('Missing packages:', ', '.join(missing))
    print('Run: .venv\\Scripts\\pip.exe install -r requirements-voice.txt')
else:
    print('All voice packages OK!')
print()
"

REM Check Ollama
echo [2] Checking Ollama...
.venv\Scripts\python.exe -c "
import urllib.request, json
try:
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=3) as r:
        data = json.loads(r.read())
        models = data.get('models', [])
        print(f'  Ollama: RUNNING — {len(models)} models')
        for m in models[:5]:
            print(f'    - {m[\"name\"]}')
except Exception as e:
    print(f'  Ollama: NOT RUNNING ({e})')
    print('  Start Ollama and run: ollama pull qwen2.5:3b-instruct')
print()
"

REM Check config file
echo [3] Checking config file...
.venv\Scripts\python.exe -c "
from pathlib import Path
cfg = Path('config/trading_runtime.yaml')
if cfg.exists():
    print(f'  config/trading_runtime.yaml: OK ({cfg.stat().st_size} bytes)')
else:
    print('  config/trading_runtime.yaml: MISSING!')
print()
"

REM Check MT5
echo [4] Checking MT5...
.venv\Scripts\python.exe -c "
try:
    import MetaTrader5 as mt5
    if mt5.initialize():
        acc = mt5.account_info()
        print(f'  MT5: CONNECTED — account={acc.login} balance={acc.balance:.2f}')
        mt5.shutdown()
    else:
        print(f'  MT5: Cannot initialize — {mt5.last_error()}')
except ImportError:
    print('  MT5: MetaTrader5 package not installed')
except Exception as e:
    print(f'  MT5: Error — {e}')
print()
"

echo ====================================================
echo   Config loader test
echo ====================================================
.venv\Scripts\python.exe -c "
import sys
sys.path.insert(0, 'src')
try:
    from mt5_ai.core.config_loader import active_config_path, load
    cfg = load()
    print(f'  Config loaded OK: {active_config_path()}')
    print(f'  Mode: {cfg.get(\"runtime\", {}).get(\"mode\")}')
    print(f'  Kill switch: {cfg.get(\"runtime\", {}).get(\"kill_switch\")}')
except Exception as e:
    print(f'  Config ERROR: {e}')
print()
"

echo ====================================================
echo   Done. Press any key to close.
echo ====================================================
pause
