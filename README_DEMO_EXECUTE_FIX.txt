HOTFIX: Demo MT5 execution command

This patch fixes commands like:
  فرايدي نفذي ديمو MT5 إذا الصفقة مناسبة

Before: the command was handled as a mode-only request or by stale code, so it returned messages such as "Mode must be Live" / "Mode must be Paper or Demo" and did not execute.

After:
  1) It switches the assistant to DEMO MT5.
  2) It uses the last analysis decision if available; otherwise it analyzes again.
  3) It executes only if action is BUY or SELL.
  4) LIVE/AUTO LIVE remains blocked.

Files included in both common layouts:
  src/mt5_ai/jarvis_assistant.py
  src/mt5_ai/local_mind.py
  mt5_ai/jarvis_assistant.py
  mt5_ai/local_mind.py
  scripts/jarvis_ui.py

Install from C:\Users\Radhi\MT5:
  Expand-Archive .\demo_execute_command_fix.zip -DestinationPath . -Force

Then stop old server on port 8765 and restart:
  Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }
  python .\scripts\jarvis_ui.py --source mt5 --profile scalping --symbol XAUUSDm --timeframe M1
