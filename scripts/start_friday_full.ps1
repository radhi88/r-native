param(
    [int]$LlamaPort = 8080,
    [int]$UiPort = 8765,
    [string]$Source = "mt5",
    [string]$Profile = "scalping",
    [switch]$AutoPaper,
    [switch]$NoAutoPaper,
    [switch]$NoSupervisor,
    [switch]$KeepExistingUi
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogsDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

$voiceModel = Get-ChildItem -Path (Join-Path $Root "models\voice") -Directory -Filter "vosk-model*" -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if ($voiceModel) {
    $env:VOSK_MODEL_PATH = $voiceModel
}
$env:LLAMA_CPP_HOST = "http://127.0.0.1:$LlamaPort"

$llamaListening = Get-NetTCPConnection -LocalPort $LlamaPort -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" } |
    Select-Object -First 1
if (-not $llamaListening) {
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-ExecutionPolicy", "Bypass", "-File", "scripts\start_llama_cpp_server.ps1", "-Port", "$LlamaPort", "-GpuLayers", "35", "-Context", "4096") `
        -WorkingDirectory $Root `
        -RedirectStandardOutput (Join-Path $LogsDir "llama_server.out.log") `
        -RedirectStandardError (Join-Path $LogsDir "llama_server.err.log") `
        -WindowStyle Hidden
    Write-Host "Starting llama.cpp on http://127.0.0.1:$LlamaPort"
} else {
    Write-Host "llama.cpp already listening on http://127.0.0.1:$LlamaPort"
}

if (-not $KeepExistingUi) {
    $uiProcesses = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match "scripts\\jarvis_ui\.py|scripts/jarvis_ui\.py" }
    foreach ($uiProcess in $uiProcesses) {
        Stop-Process -Id $uiProcess.ProcessId -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

$uiListening = Get-NetTCPConnection -LocalPort $UiPort -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" } |
    Select-Object -First 1
if (-not $uiListening) {
    $uiArgs = @("scripts\jarvis_ui.py", "--source", $Source, "--profile", $Profile, "--port", "$UiPort", "--auto-voice")
    if ($AutoPaper -and -not $NoAutoPaper) {
        $uiArgs += "--auto-paper"
    }
    Start-Process -FilePath (Join-Path $Root ".venv\Scripts\python.exe") `
        -ArgumentList $uiArgs `
        -WorkingDirectory $Root `
        -RedirectStandardOutput (Join-Path $LogsDir "jarvis_ui.out.log") `
        -RedirectStandardError (Join-Path $LogsDir "jarvis_ui.err.log") `
        -WindowStyle Hidden
    Write-Host "Starting FRIDAY UI with always-on wake listening on http://127.0.0.1:$UiPort"
} else {
    Write-Host "FRIDAY UI already listening on http://127.0.0.1:$UiPort"
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$UiPort/api/voice/start" -Method Post -TimeoutSec 5 | Out-Null
        if ($AutoPaper -and -not $NoAutoPaper) {
            Invoke-RestMethod -Uri "http://127.0.0.1:$UiPort/api/autopaper/start" -Method Post -TimeoutSec 5 | Out-Null
        }
    } catch {
        Write-Host "Could not start voice on existing UI: $($_.Exception.Message)"
    }
}

if (-not $NoSupervisor) {
    $supervisorProcesses = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match "scripts\\friday_safe_supervisor\.py|scripts/friday_safe_supervisor\.py" }
    if (-not $supervisorProcesses) {
        $supervisorArgs = @(
            "scripts\friday_safe_supervisor.py",
            "--mode", "paper",
            "--interval-seconds", "15",
            "--position-interval-seconds", "1",
            "--symbols", "XAUUSDm,EURUSDm,GBPUSDm,USDJPYm,EURJPYm,AUDUSDm,USDCHFm,USDCADm,NZDUSDm,GBPJPYm",
            "--max-symbols", "10",
            "--max-open", "3",
            "--profiles", "scalping,sk,sb,ict,swing",
            "--gold-scalper-mode",
            "--ignore-spread-filter",
            "--reserve-gold-slot",
            "--research-horizon-seconds", "900",
            "--research-max-per-cycle", "250"
        )
        Start-Process -FilePath (Join-Path $Root ".venv\Scripts\python.exe") `
            -ArgumentList $supervisorArgs `
            -WorkingDirectory $Root `
            -RedirectStandardOutput (Join-Path $LogsDir "friday_supervisor.out.log") `
            -RedirectStandardError (Join-Path $LogsDir "friday_supervisor.err.log") `
            -WindowStyle Hidden
        Write-Host "Starting FRIDAY paper supervisor: position tick 1s, scan 15s"
    } else {
        Write-Host "FRIDAY paper supervisor already running"
    }
}

Write-Host "Voice model: $env:VOSK_MODEL_PATH"
Write-Host "Open http://127.0.0.1:$UiPort"
