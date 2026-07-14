# daemon_launcher.ps1 — Start all FRIDAY/Qader subsystems as persistent daemons
# Each process auto-restarts on crash. Ctrl+C stops all.
# Usage: .\scripts\daemon_launcher.ps1
# Optional: .\scripts\daemon_launcher.ps1 -NoBacktest -NoVoice

param(
    [switch]$NoBacktest,
    [switch]$NoVoice,
    [switch]$NoAgentsServer
)

$Root = Split-Path $PSScriptRoot -Parent
$Python = "$Root\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Error "Python not found at $Python — activate venv first"
    exit 1
}

$Daemons = @(
    @{
        Name    = "QaderLoop"
        Script  = "scripts\run_qader_headless.py"
        Args    = @()
        Color   = "Cyan"
        Delay   = 5
    },
    @{
        Name    = "DnaFeedback"
        Script  = "scripts\dna_live_feedback.py"
        Args    = @("--interval", "60")
        Color   = "Green"
        Delay   = 15
    }
)

if (-not $NoAgentsServer) {
    $Daemons += @{
        Name    = "AgentsServer"
        Script  = "scripts\agents_state_server.py"
        Args    = @()
        Color   = "Yellow"
        Delay   = 10
    }
}

$Jobs = @{}
$Running = $true

function Write-Daemon([string]$Name, [string]$Msg, [string]$Color = "White") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] [$Name] $Msg" -ForegroundColor $Color
}

function Start-Daemon([hashtable]$Daemon) {
    $name   = $Daemon.Name
    $script = Join-Path $Root $Daemon.Script
    $args   = $Daemon.Args

    if (-not (Test-Path $script)) {
        Write-Daemon $name "Script not found: $script — skipping" "Red"
        return $null
    }

    Write-Daemon $name "Starting..." $Daemon.Color
    $proc = Start-Process -FilePath $Python `
        -ArgumentList (@($script) + $args) `
        -WorkingDirectory $Root `
        -NoNewWindow `
        -PassThru

    Write-Daemon $name "PID=$($proc.Id)" $Daemon.Color
    return $proc
}

# Register Ctrl+C handler
[Console]::TreatControlCAsInput = $false
$null = [System.Console]::OutputEncoding

trap {
    Write-Host "`n[Daemon] Shutting down all processes..." -ForegroundColor Red
    foreach ($kv in $Jobs.GetEnumerator()) {
        try { $kv.Value.Kill() } catch {}
    }
    $Running = $false
    exit 0
}

# Initial launch — staggered to avoid MT5 connection conflicts
Write-Host "======================================" -ForegroundColor Magenta
Write-Host "  FRIDAY DAEMON LAUNCHER              " -ForegroundColor Magenta
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Magenta
Write-Host "  $($Daemons.Count) services starting" -ForegroundColor Magenta
Write-Host "======================================" -ForegroundColor Magenta

foreach ($d in $Daemons) {
    $proc = Start-Daemon $d
    if ($proc) { $Jobs[$d.Name] = $proc }
    Start-Sleep -Seconds $d.Delay
}

# Monitor + auto-restart loop
Write-Daemon "Launcher" "All daemons running. Monitoring (Ctrl+C to stop)..." "Magenta"

while ($Running) {
    Start-Sleep -Seconds 10

    foreach ($d in $Daemons) {
        $name = $d.Name
        if (-not $Jobs.ContainsKey($name)) { continue }

        $proc = $Jobs[$name]
        if ($proc.HasExited) {
            $exit = $proc.ExitCode
            Write-Daemon $name "Crashed (exit=$exit). Restarting in $($d.Delay)s..." "Red"
            Start-Sleep -Seconds $d.Delay
            $newProc = Start-Daemon $d
            if ($newProc) {
                $Jobs[$name] = $newProc
                Write-Daemon $name "Restarted PID=$($newProc.Id)" $d.Color
            }
        }
    }

    # Heartbeat every 5 minutes
    if ((Get-Date).Minute % 5 -eq 0 -and (Get-Date).Second -lt 15) {
        $ts = Get-Date -Format "HH:mm"
        $alive = ($Jobs.Values | Where-Object { -not $_.HasExited }).Count
        Write-Daemon "Launcher" "Heartbeat $ts — $alive/$($Daemons.Count) alive" "Magenta"
    }
}
