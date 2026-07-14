# start_brain.ps1 — FRIDAY Brain Launcher
# يفتح 3 نوافذ: السرب المحلي + الوكلاء الذكيون + Vault Claude Code

param(
    [string]$Query  = "حلل الوضع الحالي وأعطني الأولوية الواحدة لهذا اليوم",
    [string]$Mode   = "paper",
    [string]$Symbol = "XAUUSDm",
    [switch]$SwarmOnly,    # شغّل السرب المحلي فقط
    [switch]$AgentsOnly,   # شغّل الوكلاء الذكيين فقط
    [switch]$VaultOnly     # افتح Claude Code في الـ vault فقط
)

$MT5   = "C:\Users\Radhi\MT5"
$Vault = "C:\Users\Radhi\MT5\plutobrain"

Write-Host ""
Write-Host "  FRIDAY Brain Launcher" -ForegroundColor Cyan
Write-Host "  ─────────────────────────────────────────" -ForegroundColor DarkCyan
Write-Host "  السرب المحلي  : friday_agents.py     (6 وكلاء + منسق)" -ForegroundColor Yellow
Write-Host "  الوكلاء الذكيون: friday_claude_agents.py (3 Claude AI)" -ForegroundColor Blue
Write-Host "  Vault         : claude (في plutobrain)" -ForegroundColor Green
Write-Host "  ─────────────────────────────────────────" -ForegroundColor DarkCyan
Write-Host ""

# ── 0. Brain Server (يخدم الـ dashboard في المتصفح)
Write-Host "[0] تشغيل Brain Server على http://localhost:5055 ..." -ForegroundColor Magenta
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$MT5'; Write-Host 'FRIDAY Brain Server — http://localhost:5055' -ForegroundColor Magenta; python brain_server.py"
) -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process "http://localhost:5055"   # افتح المتصفح تلقائياً

# ── 1. السرب المحلي (يعمل في الخلفية ويكتب JSON كل 5 ثواني)
if (-not $AgentsOnly -and -not $VaultOnly) {
    Write-Host "[1] تشغيل السرب المحلي (friday_agents.py)..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "cd '$MT5'; Write-Host 'FRIDAY Local Swarm — 6 وكلاء' -ForegroundColor Yellow; python friday_agents.py"
    ) -WindowStyle Hidden
    Start-Sleep -Seconds 3

    # 1b: جسر السرب → MT5 EA (Live Control CSV)
    Write-Host "[1b] تشغيل جسر EA (friday_to_ea_bridge.py)..." -ForegroundColor DarkYellow
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "cd '$MT5'; Write-Host 'FRIDAY -> EA Live Control Bridge' -ForegroundColor DarkYellow; python friday_to_ea_bridge.py"
    ) -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

# ── 2. الوكلاء الذكيون (Claude API — يفكرون ويخططون وينفذون)
if (-not $SwarmOnly -and -not $VaultOnly) {
    Write-Host "[2] تشغيل الوكلاء الذكيين (friday_claude_agents.py)..." -ForegroundColor Blue
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "cd '$MT5'; Write-Host 'FRIDAY Claude Agents — 3 وكلاء ذكيون' -ForegroundColor Blue; python friday_claude_agents.py --symbol '$Symbol' --mode '$Mode' --query '$Query'"
    ) -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

# ── 3. Vault (Claude Code في plutobrain — مهارات /sync /query /save)
if (-not $SwarmOnly -and -not $AgentsOnly) {
    Write-Host "[3] فتح Vault في Claude Code..." -ForegroundColor Green
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "cd '$Vault'; Write-Host 'PlutoBrain Vault — مهارات /sync /query /save' -ForegroundColor Green; Write-Host 'اكتب: /query [سؤالك] أو /save أو /sync' -ForegroundColor DarkGreen; claude"
    ) -WindowStyle Hidden
}

Write-Host ""
Write-Host "  4 نوافذ تفتح:" -ForegroundColor Cyan
Write-Host "  🟣 Brain Server    — http://localhost:5055 (افتح في المتصفح)" -ForegroundColor Magenta
Write-Host "  🟡 السرب المحلي   — يكتب friday_agents.json كل 5 ثواني" -ForegroundColor Yellow
Write-Host "  🔵 الوكلاء الذكيون — يفكرون ويخططون وينفذون بـ Claude AI" -ForegroundColor Blue
Write-Host "  🟢 Vault Claude    — /sync /query /save /weekly-update" -ForegroundColor Green
Write-Host ""
Write-Host "  الـ Dashboard: http://localhost:5055" -ForegroundColor Magenta
Write-Host "  الـ Dashboard القديم (SMC): http://localhost:5050" -ForegroundColor DarkMagenta
Write-Host ""
Write-Host "  دمج الأوامر الشائعة:" -ForegroundColor DarkCyan
Write-Host "  .\start_brain.ps1 --Query 'ما الوضع الآن؟'" -ForegroundColor Gray
Write-Host "  .\start_brain.ps1 --SwarmOnly    # السرب فقط بدون Claude API" -ForegroundColor Gray
Write-Host "  .\start_brain.ps1 --VaultOnly    # vault فقط" -ForegroundColor Gray
Write-Host "  .\start_brain.ps1 --AgentsOnly   # الوكلاء الذكيون فقط" -ForegroundColor Gray
