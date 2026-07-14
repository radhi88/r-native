# deploy_ea.ps1 — Copy EA v7.33 to MetaTrader and launch MetaEditor
$src = "C:\Users\Radhi\MT5\live_ea\Agentic_Profiled_Grid_GOLD_LIVE.mq5"
$dst = "C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\53785E099C927DB68A545C249CDBCE06\MQL5\Experts\Agentic_Profiled_Grid_GOLD_LIVE.mq5"

Copy-Item $src $dst -Force
Write-Host "EA v7.33 copied to MetaTrader Experts folder" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Open MetaEditor (press F4 in MetaTrader, or open MetaEditor.exe)"
Write-Host "  2. Open the EA file and press F7 to compile"
Write-Host "  3. Restart MetaTrader or reload the EA on the chart"
Write-Host "  4. Run: ollama serve"
Write-Host "  5. Run: C:\Users\Radhi\MT5\start_all.bat"
