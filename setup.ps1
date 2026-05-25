# R Native — automated setup for a fresh Windows machine
# Run from PowerShell (NOT as admin) inside the cloned repo:
#   cd C:\Users\<you>\MT5\r_native
#   .\setup.ps1
#
# What this does:
#   1. Detect your username + verify the install location is C:\Users\<you>\MT5
#   2. Rewrite any C:\Users\Radhi\MT5 references in source files to your path
#   3. Install Python dependencies from requirements.txt
#   4. Create the data\r_native\* directory tree
#   5. Verify MT5 + Python are available
#   6. Print next steps
#
# Idempotent — safe to re-run.

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

function Step($n, $msg) {
    Write-Host ""
    Write-Host "─── Step $n — $msg ───" -ForegroundColor Cyan
}

# ── Step 1: detect environment ─────────────────────────────────────
Step 1 "Detecting environment"
$here = $PSScriptRoot
$parent = Split-Path $here -Parent
$yourUser = $env:USERNAME
$expectedRoot = "C:\Users\$yourUser\MT5"

Write-Host "  user:              $yourUser"
Write-Host "  this script:       $here"
Write-Host "  expected MT5 root: $expectedRoot"
Write-Host "  actual parent:     $parent"

if ($parent -ne $expectedRoot) {
    Write-Warning "This repo is at '$parent' but should be at '$expectedRoot\r_native'."
    Write-Warning "Many files hard-code C:\Users\Radhi\MT5 — please move the repo or rerun the clone."
    exit 1
}

# ── Step 2: path rewrite if username differs from 'Radhi' ──────────
Step 2 "Rewriting hard-coded paths (C:\Users\Radhi\MT5 -> $expectedRoot)"
if ($yourUser -ne "Radhi") {
    $oldPath = "C:\Users\Radhi\MT5"
    $newPath = $expectedRoot
    $files = Get-ChildItem -Recurse $here -Include *.py, *.json -ErrorAction SilentlyContinue
    $touched = 0
    foreach ($f in $files) {
        $content = Get-Content $f.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($content -and $content.Contains($oldPath)) {
            $content = $content.Replace($oldPath, $newPath)
            Set-Content -Path $f.FullName -Value $content -Encoding UTF8 -NoNewline
            $touched++
            Write-Host "    rewrote $($f.Name)"
        }
    }
    Write-Host "  rewrote $touched files"
} else {
    Write-Host "  username matches 'Radhi' — no rewrite needed"
}

# ── Step 3: pip install ────────────────────────────────────────────
Step 3 "Installing Python dependencies"
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Error "python.exe not on PATH. Install Python 3.13 from python.org and re-check 'Add to PATH'."
    exit 1
}
$pyver = & python --version 2>&1
Write-Host "  python: $pyver"
& python -m pip install --upgrade pip --quiet
& python -m pip install -r "$here\requirements.txt"

# ── Step 4: create data directories ────────────────────────────────
Step 4 "Creating data directory tree"
$dirs = @(
    "data\r_native",
    "data\r_native\symbol_configs",
    "data\r_native\symbol_intel",
    "data\r_native\symbol_learning",
    "data\r_native\hall_of_fame\by_symbol",
    "data\r_native\agents",
    "data\r_native\campaigns",
    "data\r_native\scans"
)
foreach ($d in $dirs) {
    $full = Join-Path $expectedRoot $d
    if (-not (Test-Path $full)) {
        New-Item -ItemType Directory -Path $full -Force | Out-Null
        Write-Host "  created $d"
    } else {
        Write-Host "  exists  $d"
    }
}

# ── Step 5: starter continuous_evo.json (disabled by default) ──────
Step 5 "Writing starter config files"
$evoCfg = Join-Path $expectedRoot "data\r_native\continuous_evo.json"
if (-not (Test-Path $evoCfg)) {
    @'
{
  "enabled": false,
  "interval_hours": 6,
  "symbols": ["BTCUSDm", "XAUUSDm"],
  "tf": "M5",
  "pg": 300,
  "gens": 2,
  "auto_deploy_threshold": 3.0,
  "max_deploys_per_day": 6,
  "min_trades_for_deploy": 5,
  "notify_telegram": false,
  "notify_ui": true,
  "total_cycles": 0,
  "total_deploys": 0,
  "deploys_today": 0,
  "history": []
}
'@ | Out-File -FilePath $evoCfg -Encoding utf8
    Write-Host "  wrote continuous_evo.json (auto-evo DISABLED until you toggle it in UI)"
} else {
    Write-Host "  continuous_evo.json already exists — keeping it"
}

# ── Step 6: MT5 check ──────────────────────────────────────────────
Step 6 "Checking MT5 availability"
$mt5check = & python -c "
import MetaTrader5 as mt5
ok = mt5.initialize()
if ok:
    info = mt5.account_info()
    if info:
        print(f'OK login={info.login} server={info.server} balance={info.balance}')
    else:
        print('NO_ACCOUNT')
    mt5.shutdown()
else:
    print(f'INIT_FAIL: {mt5.last_error()}')
" 2>&1

Write-Host "  MT5: $mt5check"
if ($mt5check -like "*INIT_FAIL*" -or $mt5check -like "*NO_ACCOUNT*") {
    Write-Warning "Open MetaTrader 5, log in with the account you'll use, then rerun this check."
}

# ── Done ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═════════════════════════════════════════════════" -ForegroundColor Green
Write-Host " ✅ Setup complete!" -ForegroundColor Green
Write-Host "═════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host " ONE command launches everything (UI + brain + executor):" -ForegroundColor Yellow
Write-Host ""
Write-Host "   cd $expectedRoot" -ForegroundColor Cyan
Write-Host "   python -m r_native.app" -ForegroundColor White
Write-Host ""
Write-Host " Status bar at the bottom shows live service health:" -ForegroundColor Yellow
Write-Host "   🧠 ✓ (emb)  brain_server running embedded" -ForegroundColor White
Write-Host "   🤖 ✓ (PAPER) executor in paper-mode" -ForegroundColor White
Write-Host "   ⚙ 5/5  all 5 agents alive" -ForegroundColor White
Write-Host ""
Write-Host " First-run inside the UI:" -ForegroundColor Yellow
Write-Host "   1. CAMPAIGN tab → pick a symbol → RUN CAMPAIGN (~2 min)" -ForegroundColor White
Write-Host "   2. VAULT tab → select top genome → DEPLOY" -ForegroundColor White
Write-Host "   3. Click 🧬 AUTO-EVOLVE to start the 6-hour cycle" -ForegroundColor White
Write-Host "   4. AI ADVISORS tab → ⚙ AUTONOMOUS: ON" -ForegroundColor White
Write-Host ""
Write-Host " Detailed steps + troubleshooting: see INSTALL.md" -ForegroundColor Yellow
