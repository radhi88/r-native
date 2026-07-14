cd "C:\Users\Radhi\MT5\mark_xxxix"
Copy-Item "C:\Users\Radhi\MT5\mark_xxxix\_qader_visual_backups\20260515_012952\main.py" ".\main.py" -Force
Copy-Item "C:\Users\Radhi\MT5\mark_xxxix\_qader_visual_backups\20260515_012952\ui.py" ".\ui.py" -Force
python -m py_compile .\main.py .\ui.py
Write-Host "Restored backup from C:\Users\Radhi\MT5\mark_xxxix\_qader_visual_backups\20260515_012952"
