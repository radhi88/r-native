OBEY DEMO SCALPING PATCH

What this patch does:
- Makes /api/mode accept paper/demo reliably.
- Makes /api/autopaper/mode also update JarvisAssistant.mode.
- Adds /api/obey: sets MT5 data source + XAUUSDm + scalping profile + demo mode + spread override + starts auto trader.
- Adds Arabic/chat commands such as: أطيعيني، ذهب سكالبينج، تجاهلي السبريد.
- Keeps LIVE AUTO / real-account autonomous execution blocked.

Install from C:\Users\Radhi\MT5:
  Expand-Archive .\obey_demo_scalping_patch.zip -DestinationPath . -Force

Then restart:
  taskkill /F /IM python.exe
  .\.venv\Scripts\Activate.ps1
  python scripts\jarvis_ui.py --source mt5 --profile scalping --symbol XAUUSDm --timeframe M1

Test:
  Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/obey" -Method POST -ContentType "application/json" -Body '{"symbol":"XAUUSDm","mode":"demo"}'
  Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/status" -Method GET

Expected status:
- assistant.mode = demo
- assistant.profile = scalping
- assistant.source = mt5
- assistant.symbol = XAUUSDm
- assistant.ignore_spread_filter = True
- safety.live_trading_enabled = False
