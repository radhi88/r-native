param(
    [switch]$DownloadFfmpeg,
    [switch]$DownloadLlamaCpp,
    [switch]$InstallVoicePython,
    [switch]$DownloadVoskModel,
    [switch]$DownloadQwen7B,
    [switch]$DownloadQwen3B
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$ToolsDir = Join-Path $Root "tools"
$FfmpegDir = Join-Path $ToolsDir "ffmpeg"
$LlamaDir = Join-Path $ToolsDir "llama.cpp"
$LlmDir = Join-Path $Root "models\llm"
$VoiceDir = Join-Path $Root "models\voice"

New-Item -ItemType Directory -Force -Path $ToolsDir,$LlmDir,$VoiceDir | Out-Null

function Download-File($Url, $OutFile) {
    if ((Test-Path -LiteralPath $OutFile) -and ((Get-Item -LiteralPath $OutFile).Length -gt 1048576)) {
        Write-Host "Already downloaded: $OutFile"
        return
    }
    Write-Host "Downloading $Url"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -L --fail --retry 5 --retry-delay 3 -C - -o $OutFile $Url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile
    }
}

function Expand-Zip($Zip, $Destination) {
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Expand-Archive -LiteralPath $Zip -DestinationPath $Destination -Force
}

if ($InstallVoicePython) {
    & (Join-Path $Root ".venv\Scripts\python.exe") -m pip install vosk sounddevice
}

if ($DownloadFfmpeg) {
    $zip = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
    Download-File "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $zip
    Expand-Zip $zip $FfmpegDir
    $ffmpeg = Get-ChildItem -Path $FfmpegDir -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    if (-not $ffmpeg) { throw "ffmpeg.exe not found after extraction" }
    Write-Host "FFMPEG_EXE=$($ffmpeg.FullName)"
}

if ($DownloadLlamaCpp) {
    $release = Invoke-RestMethod "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    $assets = @($release.assets)
    $asset = $assets |
        Where-Object { $_.name -match "^llama-.*bin-win-cuda-12\.4-x64\.zip$" } |
        Sort-Object name |
        Select-Object -First 1
    if (-not $asset) {
        $asset = $assets | Where-Object { $_.name -match "^llama-.*bin-win-cuda-.*x64\.zip$" } | Select-Object -First 1
    }
    if (-not $asset) {
        $asset = $assets | Where-Object { $_.name -match "^llama-.*bin-win-cpu-x64\.zip$" } | Select-Object -First 1
    }
    if (-not $asset) { throw "Could not find a Windows x64 llama.cpp release asset" }
    $zip = Join-Path $env:TEMP $asset.name
    Download-File $asset.browser_download_url $zip
    Expand-Zip $zip $LlamaDir

    $cudart = $assets | Where-Object { $_.name -match "cudart-llama-bin-win-cuda-12\.4-x64\.zip$" } | Select-Object -First 1
    if ($cudart) {
        $cudaZip = Join-Path $env:TEMP $cudart.name
        Download-File $cudart.browser_download_url $cudaZip
        Expand-Zip $cudaZip $LlamaDir
    }

    $server = Get-ChildItem -Path $LlamaDir -Recurse -Filter llama-server.exe | Select-Object -First 1
    if (-not $server) { throw "llama-server.exe not found after extraction" }
    Write-Host "LLAMA_SERVER=$($server.FullName)"
}

if ($DownloadVoskModel) {
    $zip = Join-Path $env:TEMP "vosk-model-ar-mgb2-0.4.zip"
    Download-File "https://alphacephei.com/vosk/models/vosk-model-ar-mgb2-0.4.zip" $zip
    Expand-Zip $zip $VoiceDir
    $model = Get-ChildItem -Path $VoiceDir -Directory -Filter "vosk-model*" | Select-Object -First 1
    if (-not $model) { throw "Vosk model folder not found after extraction" }
    Write-Host "Set this before running FRIDAY voice:"
    Write-Host "`$env:VOSK_MODEL_PATH='$($model.FullName)'"
}

if ($DownloadQwen7B) {
    $out1 = Join-Path $LlmDir "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
    $out2 = Join-Path $LlmDir "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf"
    Download-File "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf" $out1
    Download-File "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf" $out2
    Write-Host "QWEN_7B_FIRST_PART=$out1"
}

if ($DownloadQwen3B) {
    $out = Join-Path $LlmDir "qwen2.5-3b-instruct-q4_k_m.gguf"
    Download-File "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf" $out
    Write-Host "QWEN_3B=$out"
}

Write-Host "Setup script finished."
