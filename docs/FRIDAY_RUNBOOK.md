# FRIDAY Local AI Runbook

FRIDAY is designed to be local-first:

- Browser UI: `http://127.0.0.1:8765`
- Trading model: `models/hybrid_model.keras`
- Long memory: `data/journal/jarvis_memory.sqlite3`
- Local LLM target: `llama.cpp` server on `http://127.0.0.1:8080`
- Offline wake word target: Vosk + local model

## 1. Start The UI

Recommended full local start after installing assets:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_friday_full.ps1
```

This starts:

- `llama.cpp` on `http://127.0.0.1:8080`
- FRIDAY UI on `http://127.0.0.1:8765`
- Offline Vosk wake listening automatically
- Windows SAPI local speech output
- MT5 as the default market-data source
- Autonomous multi-market Paper trading by default

```powershell
.\.venv\Scripts\python.exe scripts\jarvis_ui.py --source csv --profile scalping
```

For live MT5 market data:

```powershell
.\.venv\Scripts\python.exe scripts\jarvis_ui.py --source mt5 --profile scalping
```

## 2. Install Local Runtime Assets

These commands install or download third-party runtime software/models. Run
them only when you are ready to approve that action.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_friday_local_ai.ps1 `
  -DownloadFfmpeg `
  -DownloadLlamaCpp `
  -InstallVoicePython `
  -DownloadVoskModel `
  -DownloadQwen7B `
  -DownloadQwen3B
```

You can run only one flag at a time if you want smaller steps.

## 3. Start llama.cpp

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_llama_cpp_server.ps1
```

The script chooses the largest `.gguf` in `models/llm` unless you pass
`-ModelPath`.

For the installed Qwen 7B split GGUF, it uses the `00001-of-00002` file and
loads the companion part automatically.

## 4. Enable Offline Wake Word

After downloading a Vosk model, set:

```powershell
$env:VOSK_MODEL_PATH="C:\Users\Radhi\MT5\models\voice\<vosk-model-folder>"
.\.venv\Scripts\python.exe scripts\jarvis_ui.py --source mt5 --profile scalping
```

Use the UI button `WAKE WORD`. If dependencies/model are missing, the UI shows
the exact missing part.

Installed model path:

```powershell
$env:VOSK_MODEL_PATH="C:\Users\Radhi\MT5\models\voice\vosk-model-ar-mgb2-0.4"
```

## 5. Extract Reference Frames From The Video

```powershell
.\.venv\Scripts\python.exe scripts\extract_video_refs.py `
  "C:\Users\Radhi\Downloads\Building FRIDAY - Tony Starks female ai assistant. Follow & comment link for codebase.#bangalor.mp4"
```

Frames are written to `reports/video_refs`.

## 6. Safety

FRIDAY has a capability broker. Broad system control is routed through tools
and logs, not through an unrestricted shell from the UI.

The assistant can listen continuously and execute safe local tools, but live
financial orders, deletion, external transmission, and similar high-risk actions
remain blocked behind confirmation or are kept out of autonomous execution.

Autonomous mode is `Paper` only. It scans MT5 symbols, opens simulated trades,
manages exits, and records outcomes into the learning journal. It does not send
real MT5 orders.

Always-confirm actions remain blocked until action-time confirmation:

- Deleting or moving local files
- Installing/running newly acquired software
- Live MT5 orders
- External data upload/transmission
- Financial transactions

MT5 live trading remains locked unless `MT5_AI_LIVE_TRADING` is set to the
configured risk-acceptance value and the UI/server is started with live enabled.
