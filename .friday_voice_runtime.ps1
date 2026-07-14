$ErrorActionPreference = 'Stop'

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$root = 'C:\Users\Radhi\MT5'
$python = 'C:\Users\Radhi\MT5\.venv\Scripts\python.exe'
$voiceScript = 'scripts\run_friday_voice.py'

$ffmpegBin = 'C:\Users\Radhi\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin'
$ffplay = "$ffmpegBin\ffplay.exe"

$env:FRIDAY_FFPLAY_PATH = $ffplay
$env:PATH = "$ffmpegBin;" + $env:PATH

# TTS
$env:FRIDAY_TTS_VOICE = 'ar-SA-HamedNeural'

# Whisper Arabic - أدق من base
$env:FRIDAY_WHISPER_MODEL = 'small'
$env:FRIDAY_WHISPER_LANGUAGE = 'ar'

# VAD / Listening tuning
$env:FRIDAY_VAD_SENSITIVITY = '0.62'
$env:FRIDAY_SPEECH_START_CONFIRM_MS = '350'
$env:FRIDAY_MIN_SPEECH_MS = '900'
$env:FRIDAY_SILENCE_TIMEOUT_MS = '1200'
$env:FRIDAY_MAX_RECORD_SECONDS = '20'

# يمنع مقاطعة الرد بسرعة بسبب صوت السماعة
$env:FRIDAY_TTS_BARGE_IN_MS = '5000'

# Ollama / Brain model
$env:OLLAMA_HOST = 'http://127.0.0.1:11434'
$env:OLLAMA_MODEL = 'qwen2.5:3b-instruct'
$env:FRIDAY_OLLAMA_MODEL = 'qwen2.5:3b-instruct'
$env:FRIDAY_BRAIN_MODEL = 'qwen2.5:3b-instruct'
$env:FRIDAY_LLM_MODEL = 'qwen2.5:3b-instruct'
$env:FRIDAY_MODEL = 'qwen2.5:3b-instruct'

Set-Location -LiteralPath $root
$host.UI.RawUI.WindowTitle = 'FRIDAY Realtime Voice'

Write-Host 'FRIDAY voice runtime started...' -ForegroundColor Cyan
Write-Host 'Running voice script...' -ForegroundColor DarkGray
Write-Host ''
Write-Host "Whisper model: $env:FRIDAY_WHISPER_MODEL" -ForegroundColor DarkGray
Write-Host "Brain model:   $env:FRIDAY_OLLAMA_MODEL" -ForegroundColor DarkGray
Write-Host ''

if (!(Test-Path -LiteralPath $python)) {
    Write-Host "Python not found: $python" -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

if (!(Test-Path -LiteralPath "$root\scripts\run_friday_voice.py")) {
    Write-Host "Voice script not found: $root\scripts\run_friday_voice.py" -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

if (!(Test-Path -LiteralPath $ffplay)) {
    Write-Host "ffplay not found: $ffplay" -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

& $python $voiceScript

Write-Host ''
Write-Host 'FRIDAY stopped.' -ForegroundColor Yellow
Read-Host 'Press Enter to close'