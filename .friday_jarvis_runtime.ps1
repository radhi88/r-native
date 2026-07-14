$ErrorActionPreference = "Stop"

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$env:FRIDAY_FFPLAY_PATH = "C:\Users\Radhi\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffplay.exe"
$env:FRIDAY_TTS_VOICE = "ar-SA-HamedNeural"

$env:FRIDAY_WHISPER_MODEL = "small"
$env:FRIDAY_WHISPER_LANGUAGE = "ar"

$env:FRIDAY_VAD_SENSITIVITY = "0.50"
$env:FRIDAY_SPEECH_START_CONFIRM_MS = "350"
$env:FRIDAY_MIN_SPEECH_MS = "800"
$env:FRIDAY_SILENCE_TIMEOUT_MS = "1000"
$env:FRIDAY_TTS_BARGE_IN_MS = "4500"
$env:FRIDAY_MAX_RECORD_SECONDS = "10"

$env:OLLAMA_HOST = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "qwen2.5:3b-instruct"
$env:FRIDAY_OLLAMA_MODEL = "qwen2.5:3b-instruct"
$env:FRIDAY_BRAIN_MODEL = "qwen2.5:3b-instruct"

$env:FRIDAY_VISION_MODEL = "llava:latest"
$env:FRIDAY_USE_VISION = "0"

$env:FRIDAY_DESKTOP_AGENT_URL = "http://127.0.0.1:8855"
$env:OPENJARVIS_URL = "http://127.0.0.1:8000/v1/chat/completions"

$env:PATH = "C:\Users\Radhi\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin;" + $env:PATH

Set-Location -LiteralPath "C:\Users\Radhi\MT5"
$host.UI.RawUI.WindowTitle = "FRIDAY Jarvis Voice"

Write-Host "[FRIDAY] Runtime started." -ForegroundColor Cyan
Write-Host "[FRIDAY] OpenJarvis URL: $env:OPENJARVIS_URL" -ForegroundColor DarkGray
Write-Host "[FRIDAY] Desktop Agent:  $env:FRIDAY_DESKTOP_AGENT_URL" -ForegroundColor DarkGray
Write-Host ""

& "C:\Users\Radhi\MT5\.venv\Scripts\python.exe" "scripts\friday_jarvis_voice_bridge.py"
