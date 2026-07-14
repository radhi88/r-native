$Root = "C:\Users\Radhi\MT5"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Out = "C:\Users\Radhi\MT5_AUDIT_FULL_$Stamp"

New-Item -ItemType Directory -Force -Path $Out | Out-Null

Write-Host "[1/10] Building full project tree..."
cmd /c "tree ""$Root"" /F /A" | Out-File "$Out\00_project_tree.txt" -Encoding utf8

Write-Host "[2/10] Indexing all files..."
$AllFiles = Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
Where-Object { $_.FullName -notlike "$Out*" }

$AllFiles |
Select-Object `
@{Name="RelativePath";Expression={$_.FullName.Substring($Root.Length).TrimStart("\")}},
FullName,
Name,
Extension,
Length,
@{Name="SizeMB";Expression={[math]::Round($_.Length/1MB,4)}},
LastWriteTime |
Sort-Object RelativePath |
Export-Csv "$Out\01_all_files_index.csv" -NoTypeInformation -Encoding UTF8

Write-Host "[3/10] Indexing all folders..."
Get-ChildItem -LiteralPath $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
Where-Object { $_.FullName -notlike "$Out*" } |
Select-Object `
@{Name="RelativePath";Expression={$_.FullName.Substring($Root.Length).TrimStart("\")}},
FullName,
Name,
LastWriteTime |
Sort-Object RelativePath |
Export-Csv "$Out\02_all_folders_index.csv" -NoTypeInformation -Encoding UTF8

Write-Host "[4/10] Finding largest files..."
$AllFiles |
Sort-Object Length -Descending |
Select-Object -First 500 `
@{Name="RelativePath";Expression={$_.FullName.Substring($Root.Length).TrimStart("\")}},
FullName,
Extension,
@{Name="SizeMB";Expression={[math]::Round($_.Length/1MB,4)}},
LastWriteTime |
Export-Csv "$Out\03_largest_files.csv" -NoTypeInformation -Encoding UTF8

Write-Host "[5/10] Finding duplicate file names..."
$AllFiles |
Group-Object Name |
Where-Object { $_.Count -gt 1 } |
Select-Object Name, Count, @{Name="Paths";Expression={($_.Group.FullName -join " | ")}} |
Sort-Object Count -Descending |
Export-Csv "$Out\04_duplicate_file_names.csv" -NoTypeInformation -Encoding UTF8

Write-Host "[6/10] Selecting source/config files for code audit..."
$TextExt = @(
".py",".mq5",".mqh",
".json",".yaml",".yml",".ini",".toml",".cfg",
".ps1",".bat",".cmd",
".md",".txt"
)

$SkipContentRegex = "\\(\.venv|venv|__pycache__|\.git|node_modules|prepared|models|logs|dist|build)\\"

$SourceFiles = $AllFiles |
Where-Object {
    $TextExt -contains $_.Extension.ToLower() -and
    $_.FullName -notmatch $SkipContentRegex -and
    $_.Length -le 1048576
} |
Sort-Object FullName

$SourceFiles |
Select-Object `
@{Name="RelativePath";Expression={$_.FullName.Substring($Root.Length).TrimStart("\")}},
FullName,
Extension,
@{Name="SizeKB";Expression={[math]::Round($_.Length/1KB,2)}},
LastWriteTime |
Export-Csv "$Out\05_source_files_included.csv" -NoTypeInformation -Encoding UTF8

Write-Host "[7/10] Creating source code bundles..."

function Redact-Text {
    param([string]$Text)

    $Text = [regex]::Replace(
        $Text,
        '(?im)^(\s*[^#\r\n]*(PASSWORD|PASS|TOKEN|SECRET|API[_-]?KEY|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|PRIVATE[_-]?KEY|MT5_LOGIN|LOGIN|ACCOUNT)[^=\r\n]*=\s*).+$',
        '$1****'
    )

    $Text = [regex]::Replace(
        $Text,
        '(?i)("(password|pass|token|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|private[_-]?key|login|account)"\s*:\s*)"[^"]*"',
        '$1"****"'
    )

    return $Text
}

$MaxChars = 6000000
$Part = 1
$Builder = New-Object System.Text.StringBuilder

function Flush-Bundle {
    param(
        [System.Text.StringBuilder]$B,
        [int]$PartNo,
        [string]$OutDir
    )

    if ($B.Length -gt 0) {
        $FileName = "10_source_bundle_part_{0:D3}.txt" -f $PartNo
        $Path = Join-Path $OutDir $FileName
        [System.IO.File]::WriteAllText($Path, $B.ToString(), [System.Text.UTF8Encoding]::new($false))
    }
}

foreach ($File in $SourceFiles) {
    $Rel = $File.FullName.Substring($Root.Length).TrimStart("\")
    $Header = "`r`n`r`n================================================================================`r`nFILE: $Rel`r`nSIZE_BYTES: $($File.Length)`r`nLAST_WRITE: $($File.LastWriteTime)`r`n================================================================================`r`n"

    try {
        $Raw = Get-Content -LiteralPath $File.FullName -Raw -Encoding UTF8 -ErrorAction Stop
    } catch {
        try {
            $Raw = Get-Content -LiteralPath $File.FullName -Raw -ErrorAction Stop
        } catch {
            $Raw = "[READ_ERROR] $($_.Exception.Message)"
        }
    }

    $Raw = Redact-Text $Raw
    $Block = $Header + $Raw

    if (($Builder.Length + $Block.Length) -gt $MaxChars) {
        Flush-Bundle -B $Builder -PartNo $Part -OutDir $Out
        $Part++
        [void]$Builder.Clear()
    }

    [void]$Builder.Append($Block)
}

Flush-Bundle -B $Builder -PartNo $Part -OutDir $Out

Write-Host "[8/10] Running conflict scans..."

function Run-Scan {
    param(
        [string]$Name,
        [string]$Pattern
    )

    $ResultPath = Join-Path $Out $Name

    $SourceFiles |
    Select-String -Pattern $Pattern -AllMatches -ErrorAction SilentlyContinue |
    Select-Object `
    @{Name="RelativePath";Expression={$_.Path.Substring($Root.Length).TrimStart("\")}},
    LineNumber,
    Line |
    Export-Csv $ResultPath -NoTypeInformation -Encoding UTF8
}

Run-Scan "20_execution_scan.csv" "mt5\.order_send|order_send|OrderSend|TRADE_ACTION|TRADE_ACTION_DEAL|TRADE_ACTION_SLTP|TRADE_ACTION_REMOVE|PositionOpen|positions_get|orders_get|Buy\(|Sell\(|CTrade|close|Close|modify|Modify|trailing|Trailing|breakeven|Breakeven|partial_close|SL|TP|stop_loss|take_profit"

Run-Scan "21_signal_ai_scan.csv" "signal|Signal|confidence|Confidence|prediction|predict|direction|BUY|SELL|HOLD|CLOSE|fractal|Fractal|SMC|BOS|CHOCH|CHoCH|liquidity|sweep|Sweep|pivot|Pivot|orderflow|OrderFlow|volume|Volume|trend|Trend|AI|model|keras|tensorflow|torch|zmq|reversal|strength"

Run-Scan "22_config_scan.csv" "SYMBOL|symbol|XAUUSD|timeframe|TIMEFRAME|lot|LOT|risk|RISK|max_trades|cooldown|spread|magic|MAGIC|slippage|SL|TP|model_path|csv|CSV|ZMQ|port|session|SESSION|threshold|THRESHOLD"

Run-Scan "23_classes_functions_scan.csv" "^\s*(class|def|async\s+def)\s+"

Run-Scan "24_entrypoints_scan.csv" "__main__|argparse|asyncio\.run|main\(|run\(|start\(|while True|schedule|loop"

Write-Host "[9/10] Creating summary..."
$Summary = @"
# MT5 Full Audit Pack

Root:
$Root

Output:
$Out

Generated:
$(Get-Date)

Files indexed:
$($AllFiles.Count)

Source/config files included in code bundles:
$($SourceFiles.Count)

Important files to review first:
- 00_project_tree.txt
- 01_all_files_index.csv
- 05_source_files_included.csv
- 10_source_bundle_part_*.txt
- 20_execution_scan.csv
- 21_signal_ai_scan.csv
- 22_config_scan.csv
- 23_classes_functions_scan.csv
- 24_entrypoints_scan.csv

Notes:
- All files were indexed.
- Source/config text files were bundled.
- Heavy folders such as .venv, node_modules, logs, models, prepared were indexed but not copied into source bundles.
- Basic credential-like values were redacted in source bundles.
"@

$Summary | Out-File "$Out\README_AUDIT_PACK.md" -Encoding utf8

Write-Host "[10/10] Compressing audit pack..."
$ZipPath = "$Out.zip"
Compress-Archive -Path "$Out\*" -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "DONE"
Write-Host "Audit folder: $Out"
Write-Host "Audit zip:    $ZipPath"
Write-Host ""
Get-ChildItem $Out |
Select-Object Name, @{Name="SizeMB";Expression={[math]::Round($_.Length/1MB,3)}} |
Sort-Object Name |
Format-Table -AutoSize
