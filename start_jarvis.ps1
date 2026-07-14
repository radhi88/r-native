# ═══════════════════════════════════════════════════════════════════════════
#  FRIDAY JARVIS  v3  —  Full-stack launcher
#  Usage:  .\start_jarvis.ps1              (voice mode)
#          .\start_jarvis.ps1 --text-loop  (keyboard mode)
#          .\start_jarvis.ps1 --install-check
# ═══════════════════════════════════════════════════════════════════════════
param([switch]$TextLoop, [switch]$InstallCheck, [switch]$NoAgent)

$root = "C:\Users\Radhi\MT5"
$py   = "$root\.venv\Scripts\python.exe"
$ffplayDir = "C:\Users\Radhi\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"

# ── Critical path resolution (fixes config_loader.py & qader_app) ─────────
$env:FRIDAY_PROJECT_ROOT        = $root
$env:FRIDAY_ROOT                = $root
$env:JARVIS_PROJECT_ROOT        = $root
$env:QADER_ROOT                 = $root

# ── Encoding ───────────────────────────────────────────────────────────────
$env:PYTHONUTF8                 = "1"
$env:PYTHONIOENCODING           = "utf-8"
$env:PYTHONUNBUFFERED           = "1"

# ── ffplay (for audio playback) ────────────────────────────────────────────
$env:FRIDAY_FFPLAY_PATH         = "$ffplayDir\ffplay.exe"
$env:PATH                       = "$ffplayDir;" + $env:PATH

# ── LLM ───────────────────────────────────────────────────────────────────
$env:OLLAMA_HOST                = "http://127.0.0.1:11434"
$env:FRIDAY_OLLAMA_MODEL        = "qwen2.5:3b-instruct"
$env:FRIDAY_LLM_TEMPERATURE     = "0.20"
$env:FRIDAY_LLM_NUM_CTX         = "4096"
$env:FRIDAY_MAX_RESPONSE_TOKENS = "160"
$env:FRIDAY_LLM_WARMUP_ON_START = "1"

# ── Whisper STT ────────────────────────────────────────────────────────────
$env:FRIDAY_WHISPER_MODEL       = "base"
$env:FRIDAY_WHISPER_LANGUAGE    = "auto"
$env:FRIDAY_WHISPER_DEVICE      = "auto"
$env:FRIDAY_PARTIAL_TRANSCRIPTS = "1"

# ── VAD / Audio ────────────────────────────────────────────────────────────
$env:FRIDAY_SAMPLE_RATE         = "16000"
$env:FRIDAY_AUDIO_CHUNK_MS      = "30"
$env:FRIDAY_VAD_BACKEND         = "webrtcvad"
$env:FRIDAY_VAD_SENSITIVITY     = "0.60"
$env:FRIDAY_SILENCE_TIMEOUT_MS  = "850"
$env:FRIDAY_MIN_SPEECH_MS       = "220"
$env:FRIDAY_SPEECH_START_CONFIRM_MS = "100"
$env:FRIDAY_TTS_BARGE_IN_MS     = "1800"
$env:FRIDAY_MAX_RECORD_SECONDS  = "30"

# ── TTS ────────────────────────────────────────────────────────────────────
$env:FRIDAY_TTS_ENGINE          = "edge-tts"
$env:FRIDAY_TTS_VOICE           = "ar-SA-HamedNeural"
$env:FRIDAY_TTS_RATE            = "+8%"
$env:FRIDAY_SPEAK_WHILE_GENERATING = "1"

# ── Runtime ────────────────────────────────────────────────────────────────
$env:FRIDAY_DEFAULT_SYMBOL      = "XAUUSDm"
$env:FRIDAY_DEFAULT_TIMEFRAME   = "M1"
$env:FRIDAY_MT5_READONLY        = "1"
$env:FRIDAY_ALWAYS_LISTENING    = "1"
$env:FRIDAY_WAKE_WORD           = ""
$env:FRIDAY_MEMORY_ENABLED      = "1"
$env:FRIDAY_STREAMING_ENABLED   = "1"

# ── Desktop Agent ──────────────────────────────────────────────────────────
$env:FRIDAY_DESKTOP_AGENT_URL   = "http://127.0.0.1:8855"
$env:OPENJARVIS_URL             = "http://127.0.0.1:8000/v1/chat/completions"

# ══════════════════════════════════════════════════════════════════════════
$host.UI.RawUI.WindowTitle = "FRIDAY — JARVIS v3"
Set-Location -LiteralPath $root

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     F R I D A Y  J A R V I S  v 3              ║" -ForegroundColor Cyan
Write-Host "╠══════════════════════════════════════════════════╣" -ForegroundColor Cyan
Write-Host "║  Model   : $($env:FRIDAY_OLLAMA_MODEL.PadRight(38))║" -ForegroundColor White
Write-Host "║  Whisper : $($env:FRIDAY_WHISPER_MODEL.PadRight(38))║" -ForegroundColor White
Write-Host "║  TTS     : $($env:FRIDAY_TTS_VOICE.PadRight(38))║" -ForegroundColor White
Write-Host "║  Symbol  : $($env:FRIDAY_DEFAULT_SYMBOL.PadRight(38))║" -ForegroundColor Yellow
Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Start Desktop Agent in background ─────────────────────────────────────
if (-not $NoAgent) {
    $agentScript = "$root\scripts\friday_jarvis_desktop_agent.py"
    if (Test-Path $agentScript) {
        Write-Host "[JARVIS] Starting Desktop Agent on port 8855..." -ForegroundColor Yellow
        Start-Process powershell -ArgumentList "-NoExit", "-WindowStyle", "Minimized", "-Command", @"
            `$env:FRIDAY_PROJECT_ROOT = '$root'
            `$env:FRIDAY_ROOT = '$root'
            `$env:PYTHONUTF8 = '1'
            `$env:PYTHONIOENCODING = 'utf-8'
            `$env:PYTHONUNBUFFERED = '1'
            Set-Location -LiteralPath '$root'
            `$host.UI.RawUI.WindowTitle = 'FRIDAY Desktop Agent 8855'
            & '$py' 'scripts\friday_jarvis_desktop_agent.py'
"@
        Start-Sleep -Seconds 4
        Write-Host "[JARVIS] Desktop Agent started." -ForegroundColor Green
    }
}

# ── Launch voice ───────────────────────────────────────────────────────────
Write-Host "[FRIDAY] Starting voice pipeline..." -ForegroundColor Green
Write-Host "[FRIDAY] Speak Arabic or English freely. Press Ctrl+C to stop." -ForegroundColor Gray
Write-Host ""

if ($InstallCheck) {
    & $py "scripts\run_friday_voice.py" "--install-check"
}
elseif ($TextLoop) {
    & $py "scripts\run_friday_voice.py" "--text-loop"
}
else {
    & $py "scripts\run_friday_voice.py"
}
