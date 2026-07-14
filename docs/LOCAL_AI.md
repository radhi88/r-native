# Private Local AI Architecture

This project now has two different AI layers:

1. **Trading model**
   - Path: `models/hybrid_model.keras`
   - Purpose: predicts market direction probability from prepared MT5 features.
   - Runs through TensorFlow.

2. **Private FRIDAY mind**
   - Memory: `data/journal/jarvis_memory.sqlite3`
   - Local chat/orchestration: `src/mt5_ai/local_mind.py`
   - Browser UI: `scripts/jarvis_ui.py` + `web/jarvis/`
   - Optional local LLM provider: llama.cpp at `http://127.0.0.1:8080`

No GPT/OpenAI API is required for the local FRIDAY UI.

## Run The UI

```powershell
python scripts/jarvis_ui.py --source csv --profile scalping
```

Then open:

```text
http://127.0.0.1:8765
```

For MT5 live data:

```powershell
python scripts/jarvis_ui.py --source mt5 --profile scalping
```

## Local LLM

llama.cpp is not installed/running on this machine right now. Without it,
FRIDAY still has memory and trading tools, but general conversation is handled
by a deterministic local controller.

To attach a local GGUF model later:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_friday_local_ai.ps1 -DownloadLlamaCpp -DownloadQwen7B
powershell -ExecutionPolicy Bypass -File scripts\start_llama_cpp_server.ps1
```

Suggested local models for an 8GB GPU are 7B-class quantized models. Larger
models may run slowly or fall back to CPU.

## Permission Model

Jarvis has project and MT5 access through tools. Live trading is locked by
default. Full unrestricted computer control is intentionally not exposed from
the web UI, because a voice assistant with raw shell access is unsafe. Add
specific tools one by one instead: MT5, files under this project, reports,
model training, and paper trading.
