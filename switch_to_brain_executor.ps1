# switch_to_brain_executor.ps1
# Cancels old EA's pendings (magic ≠ 20260600), keeps brain's pendings intact.
# Run AFTER you've removed the old EA from the chart.

param(
    [switch]$Force,
    [long]$BrainMagic = 20260600
)

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Switch to FRIDAY_Brain_Executor — clean handoff" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$script = @"
import MetaTrader5 as mt5
import sys

BRAIN_MAGIC = $BrainMagic

if not mt5.initialize():
    print('ERROR: cannot init MT5'); sys.exit(1)

info = mt5.account_info()
print(f'Account: {info.login} balance={info.balance} equity={info.equity}')
print()

# Inventory all our pendings and positions
pendings = mt5.orders_get(symbol='XAUUSDm') or []
positions = mt5.positions_get(symbol='XAUUSDm') or []

print(f'=== Pendings: {len(pendings)} ===')
to_cancel = []
for o in pendings:
    side = 'BUY' if o.type in (mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_LIMIT) else 'SELL'
    tag  = 'BRAIN' if o.magic == BRAIN_MAGIC else f'OLD (magic={o.magic})'
    print(f'  #{o.ticket}  {side}  @ {o.price_open:.2f}  SL={o.sl:.2f} TP={o.tp:.2f}  vol={o.volume_initial}  [{tag}]')
    if o.magic != BRAIN_MAGIC:
        to_cancel.append(o.ticket)

print()
print(f'=== Positions: {len(positions)} ===')
for p in positions:
    side = 'BUY' if p.type == mt5.POSITION_TYPE_BUY else 'SELL'
    tag  = 'BRAIN' if p.magic == BRAIN_MAGIC else f'OLD (magic={p.magic})'
    print(f'  #{p.ticket}  {side}  @ {p.price_open:.2f}  SL={p.sl:.2f} TP={p.tp:.2f}  P/L={p.profit:.2f}  [{tag}]')

print()
if not to_cancel:
    print('No old-EA pendings to cancel. Clean.')
    sys.exit(0)

$forceFlag = '$($Force.IsPresent)'.ToLower()
if $forceFlag != 'true':
    ans = input(f'\nCancel {len(to_cancel)} OLD pendings? (yes/no): ')
    if ans.strip().lower() != 'yes':
        print('Aborted.'); sys.exit(0)

cancelled = 0
for ticket in to_cancel:
    req = {'action': mt5.TRADE_ACTION_REMOVE, 'order': ticket}
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        print(f'  ✓ cancelled #{ticket}'); cancelled += 1
    else:
        print(f'  ✗ failed #{ticket}: {r.retcode if r else \"None\"} {r.comment if r else \"\"}')

print(f'\nDone — {cancelled}/{len(to_cancel)} cancelled.')
print('Now you can attach FRIDAY_Brain_Executor.mq5 to the chart.')
mt5.shutdown()
"@

# Run the python script
$tempFile = "$env:TEMP\switch_ea_$([System.Guid]::NewGuid().ToString('N').Substring(0,8)).py"
$script | Out-File -FilePath $tempFile -Encoding utf8
try {
    python $tempFile
} finally {
    Remove-Item $tempFile -ErrorAction SilentlyContinue
}
