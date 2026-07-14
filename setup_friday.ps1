# setup_friday.ps1 — One-shot tuner + launcher
# Validates settings, stops rogue EAs, starts all services with correct mode.
#
# Usage:
#   .\setup_friday.ps1            (PAPER mode default)
#   .\setup_friday.ps1 -Live      (LIVE trading)
#   .\setup_friday.ps1 -Kill      (emergency stop)

param(
    [switch]$Live,
    [switch]$Kill,
    [switch]$NoClaude        # skip Claude API for COORDINATOR
)

$ErrorActionPreference = 'Continue'
$MT5 = "C:\Users\Radhi\MT5"

function Write-Hdr($txt, $color = 'Cyan') {
    Write-Host ""
    Write-Host ("═" * 70) -ForegroundColor $color
    Write-Host "  $txt" -ForegroundColor $color
    Write-Host ("═" * 70) -ForegroundColor $color
}

function Stop-Friday-Procs {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'friday_brain.py|brain_server.py|friday_agents.py|smc_dashboard.py' } |
        ForEach-Object {
            Write-Host "  stop PID $($_.ProcessId)" -ForegroundColor DarkGray
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 2
}

# ── EMERGENCY STOP ─────────────────────────────────────────────────
if ($Kill) {
    Write-Hdr "🛑 EMERGENCY STOP" 'Red'
    Set-Content -Path "$MT5\kill_switch.txt" -Value ("killed at " + (Get-Date)) -Encoding UTF8
    Write-Host "  ✓ kill_switch.txt created — brain + EA will halt next tick" -ForegroundColor Yellow

    Stop-Friday-Procs

    Write-Host "`n  Cancelling all Brain pendings..." -ForegroundColor Yellow
    python -c "import MetaTrader5 as mt5; mt5.initialize(); p=[o for o in (mt5.orders_get(symbol='XAUUSDm') or []) if o.magic==20260600]; print(f'  {len(p)} pendings to cancel');
[mt5.order_send({'action':mt5.TRADE_ACTION_REMOVE,'order':o.ticket}) for o in p]; mt5.shutdown()"

    Write-Host "`n  ✓ Everything stopped. Remove kill_switch.txt to resume." -ForegroundColor Green
    exit 0
}

# ── 1. CONFIG VALIDATION ───────────────────────────────────────────
Write-Hdr "1. التحقق من الإعدادات"
python "$MT5\friday_config.py" | Out-Host

# Account check
$bal = python -c "import MetaTrader5 as mt5; mt5.initialize(); print(mt5.account_info().balance); mt5.shutdown()"
$bal = [double]$bal
Write-Host "`n  💰 Balance: `$$bal" -ForegroundColor Cyan

if ($bal -lt 20) {
    Write-Host "  ⚠️  رصيد منخفض جداً — أوصي بأن تعمل PAPER فقط" -ForegroundColor Red
    if ($Live) {
        Write-Host "  → سأبدّل لـ PAPER تلقائياً" -ForegroundColor Yellow
        $Live = $false
    }
} elseif ($bal -lt 50) {
    Write-Host "  ⚠️  رصيد صغير — تأكد MAX_LOT=$($cfg.MAX_LOT) و MAX_ORDERS=$($cfg.MAX_ORDERS)" -ForegroundColor Yellow
}

# ── 2. CLEANUP ─────────────────────────────────────────────────────
Write-Hdr "2. تنظيف العمليات والأوامر المارقة"

# Remove kill switch (if user wants to resume)
if (Test-Path "$MT5\kill_switch.txt") {
    if ($Live) {
        Remove-Item "$MT5\kill_switch.txt" -Force
        Write-Host "  ✓ kill_switch.txt removed" -ForegroundColor Green
    }
}

# Stop old Python procs
Stop-Friday-Procs

# Cancel non-Brain pendings (safety)
Write-Host "  فحص أوامر EAs المارقة..." -ForegroundColor Yellow
$rogue = python -c @"
import MetaTrader5 as mt5
mt5.initialize()
p = mt5.orders_get(symbol='XAUUSDm') or []
rogue = [o for o in p if o.magic != 20260600]
print(len(rogue))
for o in rogue:
    print(f'{o.ticket}|{o.magic}|{o.type}|{o.price_open}')
mt5.shutdown()
"@
$rogueLines = $rogue -split "`n"
$rogueCount = [int]$rogueLines[0]
if ($rogueCount -gt 0) {
    Write-Host "  ⚠️ وجدت $rogueCount أوامر من EAs أخرى (غير Brain)" -ForegroundColor Red
    $rogueLines | Select-Object -Skip 1 | ForEach-Object {
        if ($_) { Write-Host "    rogue: $_" -ForegroundColor DarkRed }
    }
    Write-Host "  → أوقف الـ EAs القديمة من نوافذ MT5 يدوياً" -ForegroundColor Yellow
} else {
    Write-Host "  ✓ لا توجد أوامر EAs مارقة" -ForegroundColor Green
}

# ── 3. ENVIRONMENT ─────────────────────────────────────────────────
Write-Hdr "3. إعدادات البيئة"

# Claude API
if (-not $NoClaude -and $env:ANTHROPIC_API_KEY) {
    Write-Host "  ✓ ANTHROPIC_API_KEY مضبوط — COORDINATOR سيستخدم Claude Sonnet 4.5" -ForegroundColor Green
} elseif ($NoClaude) {
    $env:ANTHROPIC_API_KEY = $null
    Write-Host "  ⚪ Claude API معطّل (--NoClaude)" -ForegroundColor DarkGray
} else {
    Write-Host "  ⚪ ANTHROPIC_API_KEY غير مضبوط — COORDINATOR على qwen2.5:7b" -ForegroundColor DarkYellow
    Write-Host "    لتفعيل Claude: `$env:ANTHROPIC_API_KEY='sk-ant-...' ثم أعد تشغيل" -ForegroundColor DarkGray
}

# ── 4. SERVICES ────────────────────────────────────────────────────
Write-Hdr "4. تشغيل الخدمات"

# Ollama
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
    Write-Host "  ✓ Ollama يعمل" -ForegroundColor Green
} catch {
    Write-Host "  Ollama متوقف — تشغيل..." -ForegroundColor Yellow
    Start-Process ollama -ArgumentList "serve" -WindowStyle Minimized
    Start-Sleep -Seconds 5
}

# SMC Dashboard
Start-Process powershell -ArgumentList @(
    "-NoExit","-Command",
    "cd '$MT5\dashboard'; `$Host.UI.RawUI.WindowTitle='SMC Dashboard 5050'; python smc_dashboard.py"
) -WindowStyle Minimized
Write-Host "  ✓ SMC Dashboard launching (port 5050)" -ForegroundColor Green

# Brain Server
Start-Process powershell -ArgumentList @(
    "-NoExit","-Command",
    "cd '$MT5'; `$Host.UI.RawUI.WindowTitle='Brain Server 5055'; python brain_server.py"
) -WindowStyle Normal
Write-Host "  ✓ Brain Server launching (port 5055)" -ForegroundColor Green

# Rule-based swarm (for graph viz)
Start-Process powershell -ArgumentList @(
    "-NoExit","-Command",
    "cd '$MT5'; `$Host.UI.RawUI.WindowTitle='Swarm (graph)'; python friday_agents.py"
) -WindowStyle Minimized
Write-Host "  ✓ Rule-based Swarm launching" -ForegroundColor Green

# LLM Brain — the main one
$modeFlag  = if ($Live) { '--live' } else { '' }
$modeColor = if ($Live) { 'Red' } else { 'Yellow' }
$modeTxt   = if ($Live) { '🔴 LIVE (real trades)' } else { '🟡 PAPER (dry-run)' }

Start-Process powershell -ArgumentList @(
    "-NoExit","-Command",
    "cd '$MT5'; `$Host.UI.RawUI.WindowTitle='FRIDAY Brain $modeTxt'; Write-Host '$modeTxt' -ForegroundColor $modeColor; python friday_brain.py $modeFlag"
) -WindowStyle Normal
Write-Host "  ✓ LLM Brain launching ($modeTxt)" -ForegroundColor $modeColor

Start-Sleep -Seconds 8

# ── 5. VERIFICATION ────────────────────────────────────────────────
Write-Hdr "5. التحقق النهائي" 'Green'

Write-Host "`nالمنافذ:" -ForegroundColor Cyan
@(5050, 5055, 11434) | ForEach-Object {
    $c = Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue
    $n = switch ($_) { 5050 {'SMC Dashboard'} 5055 {'Brain Server'} 11434 {'Ollama'} }
    if ($c) {
        Write-Host "  ✓ $_  $n" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $_  $n" -ForegroundColor Red
    }
}

Write-Host "`nالعمليات:" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'friday_brain.py|brain_server.py|friday_agents.py|smc_dashboard.py' } |
    ForEach-Object {
        $name = 'Other'
        if     ($_.CommandLine -match 'friday_brain.py')   { $name = 'LLM Brain' }
        elseif ($_.CommandLine -match 'brain_server.py')   { $name = 'Brain Server' }
        elseif ($_.CommandLine -match 'smc_dashboard.py')  { $name = 'SMC Dashboard' }
        elseif ($_.CommandLine -match 'friday_agents.py')  { $name = 'Rule Swarm' }
        $live = ''
        if ($_.CommandLine -match '--live') { $live = ' [LIVE]' }
        Write-Host "  ✓ PID $($_.ProcessId)  $name$live" -ForegroundColor Green
    }

Write-Host "`nMCP:" -ForegroundColor Cyan
$mcp = claude mcp list 2>&1 | Out-String
if ($mcp -match 'friday:.*Connected') {
    Write-Host "  ✓ friday — Connected (12 tools)" -ForegroundColor Green
}

Write-Host "`nScheduled Task:" -ForegroundColor Cyan
$tasks = Get-ChildItem "$env:USERPROFILE\.claude\scheduled-tasks\friday-continuous-improvement\" -ErrorAction SilentlyContinue
if ($tasks) { Write-Host "  ✓ friday-continuous-improvement — كل 4 ساعات" -ForegroundColor Green }

Write-Host "`nMT5:" -ForegroundColor Cyan
python -c "import MetaTrader5 as mt5; mt5.initialize(); i=mt5.account_info(); p=[o for o in (mt5.orders_get(symbol='XAUUSDm') or []) if o.magic==20260600]; pos=[x for x in (mt5.positions_get(symbol='XAUUSDm') or []) if x.magic==20260600]; print(f'  Account {i.login}  Balance {i.balance}  Equity {i.equity}'); print(f'  Trade Allowed: {i.trade_allowed}  Expert: {i.trade_expert}'); print(f'  Brain pendings: {len(p)}  positions: {len(pos)}'); mt5.shutdown()"

Write-Host "`n═════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✅ النظام شغّال بالإعدادات المضبوطة" -ForegroundColor Green
Write-Host "═════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard:  http://localhost:5055/" -ForegroundColor Cyan
Write-Host "  Kill:       .\setup_friday.ps1 -Kill" -ForegroundColor Yellow
Write-Host "  Report:     python friday_analyze.py" -ForegroundColor Yellow

Start-Process "http://localhost:5055/"
