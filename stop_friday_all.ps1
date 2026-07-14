$ports = @(8765, 8788, 8790, 8799, 8811, 8822, 8833, 8844, 8855, 8866)

Write-Host "Stopping FRIDAY services by ports..."

foreach ($port in $ports) {
    $ownerPid = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess

    if ($ownerPid) {
        Write-Host "Stopping port $port PID $ownerPid"
        Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 400
    } else {
        Write-Host "Port $port is not running"
    }
}

Write-Host "Stopping FRIDAY PowerShell/Python workers..."

$patterns = @(
    "friday_live_brain_state.py",
    "friday_system_mesh.py",
    "friday_autopilot_supervisor.py",
    "friday_trade_outcome_learner.py",
    "friday_realtime_scalper_demo_executor.py",
    "friday_touch_demo_executor.py",
    "friday_demo_position_governor.py",
    "friday_demo_position_governor_v2.py",
    "friday_control_center.py",
    "friday_web_dashboard.py",
    "friday_scalper_live_dashboard.py",
    "friday_agents_browser.py",
    "friday_chat_app.py",
    "friday_local_gateway:app",
    "friday_orchestrator.py",
    "brain_server.py",
    "friday_agents.py",
    "friday_claude_agents.py",
    "scripts\friday_jarvis_desktop_agent.py",
    "scripts/dashboard_server.py",
    "dashboard_server.py",
    "scripts/jarvis_ui.py",
    "jarvis_ui.py",
    "scripts/run_qader_headless.py",
    "run_qader_headless.py",
    "scripts/system_status_report.py",
    "system_status_report.py",
    "scripts/dna_live_feedback.py",
    "dna_live_feedback.py",
    "algory_chart_dashboard.py",
    "live_fractal_projection_monitor.py",
    "friday_v3.friday_v3",
    "friday_v3\friday_v3.py",
    "friday_fractals.py",
    "friday_footprint.py",
    "friday_binance_dom.py",
    "friday_agent_team.py",
    "friday_indicator_feature_engine.py",
    "friday_feature_outcome_learner.py",
    "friday_orderflow_feature_engine.py",
    "mark_xxxix",
    "algory_runner",
    "friday_health_monitor",
    "friday_safe_supervisor.py",
    "friday_genome_status_export.py",
    "main.py"
)

$regex = ($patterns | ForEach-Object { [regex]::Escape($_) }) -join "|"

function Set-JsonProperty {
    param(
        [Parameter(Mandatory=$true)] $Object,
        [Parameter(Mandatory=$true)] [string] $Name,
        [Parameter(Mandatory=$false)] $Value
    )
    if ($Object.PSObject.Properties[$Name]) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

Get-CimInstance Win32_Process |
Where-Object {
    if (-not $_.CommandLine) { return $false }
    $cmd = $_.CommandLine -replace "/", "\"
    $cmd -match $regex
} |
ForEach-Object {
    Write-Host "Stopping worker PID:" $_.ProcessId "CMD:" $_.CommandLine
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

$statePath = Join-Path $PSScriptRoot "dashboard\qader_live_state.json"
if (Test-Path $statePath) {
    try {
        $state = Get-Content $statePath -Raw | ConvertFrom-Json
        $now = (Get-Date).ToUniversalTime().ToString("o")
        $state.timestamp = $now
        if (-not $state.loop) {
            $state | Add-Member -NotePropertyName loop -NotePropertyValue ([pscustomobject]@{})
        }
        Set-JsonProperty $state.loop "state" "STOPPED"
        Set-JsonProperty $state.loop "reason" "stop_friday_all"
        Set-JsonProperty $state.loop "thread_alive" $false
        Set-JsonProperty $state.loop "allow_new_entries" $false
        if ($state.latest_record) {
            Set-JsonProperty $state.latest_record "loop_state" "STOPPED"
            Set-JsonProperty $state.latest_record "execution_status" "stopped"
            Set-JsonProperty $state.latest_record "execution_decision" "stopped"
            Set-JsonProperty $state.latest_record "reason" "stop_friday_all"
            Set-JsonProperty $state.latest_record "blocked_reason" "stop_friday_all"
            Set-JsonProperty $state.latest_record "open_positions" 0
            Set-JsonProperty $state.latest_record "open_positions_total" 0
            Set-JsonProperty $state.latest_record "pending_orders" 0
            Set-JsonProperty $state.latest_record "pending_orders_total" 0
            Set-JsonProperty $state.latest_record "qader_pending_tickets" @()
        }
        $json = $state | ConvertTo-Json -Depth 100
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($statePath, $json, $utf8NoBom)
        Write-Host "Marked QADER dashboard state as STOPPED."
    } catch {
        Write-Host "Could not mark QADER dashboard state as STOPPED:" $_.Exception.Message
    }
}

Write-Host "FRIDAY stopped."
