$root = "C:\Users\Radhi\MT5"
$py = "$root\.venv\Scripts\python.exe"

$FRIDAY_DASHBOARD_URL   = "http://127.0.0.1:8790"
$FRIDAY_GATEWAY_URL     = "http://127.0.0.1:8799"
$FRIDAY_CHAT_URL        = "http://127.0.0.1:8811"
$FRIDAY_TRADINGVIEW_URL = "http://127.0.0.1:8822"
$FRIDAY_AGENTS_URL      = "http://127.0.0.1:8833"
$FRIDAY_BRAIN_URL       = "http://127.0.0.1:8844"

$env:FRIDAY_DASHBOARD_URL   = $FRIDAY_DASHBOARD_URL
$env:FRIDAY_BASE            = $FRIDAY_DASHBOARD_URL
$env:FRIDAY_SSE_URL         = "$FRIDAY_DASHBOARD_URL/events"
$env:FRIDAY_GATEWAY_URL     = $FRIDAY_GATEWAY_URL
$env:FRIDAY_CHAT_URL        = $FRIDAY_CHAT_URL
$env:FRIDAY_TRADINGVIEW_URL = $FRIDAY_TRADINGVIEW_URL
$env:FRIDAY_AGENTS_URL      = $FRIDAY_AGENTS_URL
$env:FRIDAY_BRAIN_URL       = $FRIDAY_BRAIN_URL
$env:FRIDAY_ROOT            = $root
$env:JARVIS_PROJECT_ROOT    = $root
$env:FRIDAY_PROJECT_ROOT    = $root   # ← fixes config_loader.py path resolution
$env:QADER_ROOT             = $root   # ← fixes qader_app paths.py resolution
$env:FRIDAY_SYMBOLS = "XAUUSD"
$env:FRIDAY_MAX_SYMBOLS = "0"
$env:FRIDAY_SYMBOLS_VISIBLE_ONLY = "0"

function Start-FridayWindow($title, $cmd) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; `$host.UI.RawUI.WindowTitle='$title'; $cmd"
}

Start-FridayWindow "FRIDAY Gateway 8799" "$py -m uvicorn friday_local_gateway:app --host 127.0.0.1 --port 8799"
Start-Sleep -Seconds 2

Start-FridayWindow "FRIDAY Chat 8811" "$py friday_chat_app.py"
Start-Sleep -Seconds 2

Start-FridayWindow "FRIDAY TradingView Dashboard 8822" "$py friday_scalper_live_dashboard.py"
Start-Sleep -Seconds 2

Start-FridayWindow "FRIDAY AI Dashboard 8790" "$py scripts\friday_web_dashboard.py --profile scalping --symbols all --max-open-positions 3 --entry-cooldown-seconds 30 --analysis-only --port 8790"
Start-Sleep -Seconds 2

Start-FridayWindow "FRIDAY Agents Browser 8833" "$py friday_agents_browser.py"
Start-Sleep -Seconds 2

Start-FridayWindow "FRIDAY Autopilot Supervisor" "$py friday_autopilot_supervisor.py 20"

Start-Process $FRIDAY_DASHBOARD_URL
Start-Process $FRIDAY_AGENTS_URL
Start-Process $FRIDAY_TRADINGVIEW_URL
Start-Process $FRIDAY_CHAT_URL
