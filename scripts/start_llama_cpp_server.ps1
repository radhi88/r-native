param(
    [string]$ModelPath = "",
    [int]$Port = 8080,
    [int]$GpuLayers = 35,
    [int]$Context = 4096
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LlamaServer = Get-ChildItem -Path (Join-Path $Root "tools\llama.cpp") -Recurse -Filter llama-server.exe -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $LlamaServer) {
    throw "llama-server.exe not found. Run scripts\setup_friday_local_ai.ps1 -DownloadLlamaCpp first."
}

if (-not $ModelPath) {
    $ModelDir = Join-Path $Root "models\llm"
    $ModelPath = Get-ChildItem -Path $ModelDir -Filter "*7b*q4_k_m*00001-of*.gguf" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $ModelPath) {
        $ModelPath = Get-ChildItem -Path $ModelDir -Filter "*7b*q4_k_m*.gguf" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notmatch "00002-of" } |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $ModelPath) {
        $ModelPath = Get-ChildItem -Path $ModelDir -Filter "*3b*q4_k_m*.gguf" -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $ModelPath) {
        $ModelPath = Get-ChildItem -Path $ModelDir -Filter "*.gguf" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notmatch "00002-of" } |
            Sort-Object Length -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
}

if (-not $ModelPath -or -not (Test-Path -LiteralPath $ModelPath)) {
    throw "No GGUF model found. Download Qwen 7B or 3B first."
}

$env:LLAMA_CPP_HOST = "http://127.0.0.1:$Port"
$env:MT5_AI_LOCAL_MODEL = [IO.Path]::GetFileNameWithoutExtension($ModelPath)

& $LlamaServer.FullName `
    --model $ModelPath `
    --host 127.0.0.1 `
    --port $Port `
    --ctx-size $Context `
    --n-gpu-layers $GpuLayers
