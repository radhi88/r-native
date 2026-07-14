param(
    [switch]$InstallPyInstaller,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Set-Location $Root

if ($Clean) {
    $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $Archive = Join-Path "_archive" "qader_build_cleanup_$Stamp"
    New-Item -ItemType Directory -Force $Archive | Out-Null
    if (Test-Path "build") {
        Move-Item -LiteralPath "build" -Destination (Join-Path $Archive "build")
    }
    if (Test-Path "dist\Qader") {
        New-Item -ItemType Directory -Force "dist" | Out-Null
        Move-Item -LiteralPath "dist\Qader" -Destination (Join-Path $Archive "Qader")
    }
}

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    if ($InstallPyInstaller) {
        & $Python -m pip install pyinstaller
    } else {
        Write-Host "PyInstaller is not installed. Re-run with -InstallPyInstaller or install it in .venv."
        exit 2
    }
}

& $Python -m PyInstaller "packaging\qader.spec" --noconfirm

$DataDir = "dist\Qader\data\qader"
$LogsDir = "dist\Qader\logs"
$ReportsDir = "dist\Qader\reports"
New-Item -ItemType Directory -Force $DataDir | Out-Null
New-Item -ItemType Directory -Force "$DataDir\dna" | Out-Null
New-Item -ItemType Directory -Force $LogsDir | Out-Null
New-Item -ItemType Directory -Force $ReportsDir | Out-Null

Write-Host "Build complete: dist\Qader\Qader.exe"
