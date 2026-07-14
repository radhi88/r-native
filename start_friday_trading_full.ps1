$root = "C:\Users\Radhi\MT5"
$py   = "$root\.venv\Scripts\python.exe"

# ─── Load .env (API keys) ────────────────────────────────────────────────────
$envFile = "$root\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.+)$') {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
        }
    }
    Write-Host "Loaded .env" -ForegroundColor DarkGreen
} else {
    Write-Host "WARNING: .env not found" -ForegroundColor Yellow
}

# ─── Launch Orchestrator ─────────────────────────────────────────────────────
# friday_orchestrator.py يشغّل الكل بالترتيب الصحيح وبوضع آمن:
#   Tier 1: Data Foundation   (indicator + orderflow)
#   Tier 2: Intelligence      (learners + brain_loop)
#   Tier 3: API Layer         (gateway + brain_server + mesh)
#   Tier 4: Dashboards        (chat + tv + agents + ai_dashboard)
#   Tier 5: Trading Engine    (autopilot + algory_runner PAPER)
#   Tier 6: Health Monitor    (watchdog + diagnostics)
#   Tier 7: JARVIS Mark-XXXIX (آخر شيء — أوامر المستخدم فقط)

$env:FRIDAY_PROJECT_ROOT = $root
$env:QADER_ROOT = $root
$env:FRIDAY_MT5_READONLY = "1"
$env:FRIDAY_DASHBOARD_DISABLE_TF = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:FRIDAY_DASHBOARD_URL = "http://127.0.0.1:8790"
$env:FRIDAY_GATEWAY_URL = "http://127.0.0.1:8799"
$env:FRIDAY_CHAT_URL = "http://127.0.0.1:8811"
$env:FRIDAY_TRADINGVIEW_URL = "http://127.0.0.1:8822"
$env:FRIDAY_AGENTS_URL = "http://127.0.0.1:8833"
$env:FRIDAY_BRAIN_URL = "http://127.0.0.1:8844"
$env:QADER_DASHBOARD_URL = "http://127.0.0.1:8765"
$env:QADER_STATE_URL = "http://127.0.0.1:8765/api/state"
$env:QADER_STREAM_URL = "http://127.0.0.1:8765/api/stream"
$env:QADER_CHAT_URL = "http://127.0.0.1:8788"

Write-Host ""
Write-Host "Starting FRIDAY via Orchestrator..." -ForegroundColor Cyan
Write-Host "(كل طبقة تنتظر الطبقة اللي قبلها قبل ما تشتغل)" -ForegroundColor DarkCyan
Write-Host "Fixed URLs:" -ForegroundColor DarkCyan
Write-Host "  Qader Live : $env:QADER_DASHBOARD_URL/qader_live_dashboard.html" -ForegroundColor Gray
Write-Host "  Qader Chat : $env:QADER_CHAT_URL" -ForegroundColor Gray
Write-Host "  AI Dash    : $env:FRIDAY_DASHBOARD_URL" -ForegroundColor Gray
Write-Host ""

& $py "$root\friday_orchestrator.py"
