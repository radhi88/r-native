cd "C:\Users\Radhi\MT5\mark_xxxix"
Copy-Item "C:\Users\Radhi\MT5\mark_xxxix\_qader_share_picker_backups\20260515_015414\main.py" ".\main.py" -Force
if (Test-Path "C:\Users\Radhi\MT5\mark_xxxix\_qader_share_picker_backups\20260515_015414\qader_visual_upgrade.py") { Copy-Item "C:\Users\Radhi\MT5\mark_xxxix\_qader_share_picker_backups\20260515_015414\qader_visual_upgrade.py" ".\qader_visual_upgrade.py" -Force }
if (Test-Path "C:\Users\Radhi\MT5\mark_xxxix\_qader_share_picker_backups\20260515_015414\qader_screen_share_controller.py") { Copy-Item "C:\Users\Radhi\MT5\mark_xxxix\_qader_share_picker_backups\20260515_015414\qader_screen_share_controller.py" ".\qader_screen_share_controller.py" -Force }
python -m py_compile .\main.py .\qader_visual_upgrade.py .\qader_screen_share_controller.py
Write-Host "Restored backup from C:\Users\Radhi\MT5\mark_xxxix\_qader_share_picker_backups\20260515_015414"
