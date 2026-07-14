# Start the AI Geometric Agentic Desk under the watchdog (Windows PowerShell).
# Usage:  .\scripts\start_desk.ps1            # default symbols
#         .\scripts\start_desk.ps1 XAUUSDm BTCUSDm EURUSDm
param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Symbols)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Symbols -or $Symbols.Count -eq 0) {
    $Symbols = @("XAUUSDm", "BTCUSDm", "EURUSDm", "GBPUSDm", "USDJPYm")
}

Write-Host "[start_desk] launching watchdog for: $($Symbols -join ', ')"
& python "$root\scripts\watchdog.py" @Symbols
