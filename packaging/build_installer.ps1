# build_installer.ps1 — one-shot Windows installer build for FRIDAY R Factory.
#
# Run from project root:
#   .\packaging\build_installer.ps1
#
# Stages:
#   1. Verify Python + pyinstaller + Inno Setup are installed
#   2. Clean previous dist/ folder
#   3. Run PyInstaller using packaging/FRIDAY.spec → dist/FRIDAY/
#   4. (Optional) Build Inno Setup installer → dist/FRIDAY_Setup_v<ver>.exe
#
# Outputs:
#   dist/FRIDAY/                 — portable folder (copy to any machine)
#   dist/FRIDAY_Setup_*.exe      — single-file installer (if Inno present)

$ErrorActionPreference = "Stop"
$VERSION = "1.0.0"
$ROOT = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $ROOT

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  FRIDAY R Factory  —  Installer Build v$VERSION" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# Stage 1 — prerequisites
Write-Host ""
Write-Host "[1/4] checking prerequisites…"
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "Python not found in PATH" }
Write-Host "  python: $py"

$has_pi = & python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
if (-not $has_pi) {
    Write-Host "  installing pyinstaller…"
    & python -m pip install --quiet --upgrade pyinstaller
}
Write-Host "  pyinstaller: $(& python -c 'import PyInstaller; print(PyInstaller.__version__)')"

# Stage 2 — clean
Write-Host ""
Write-Host "[2/4] cleaning previous build…"
if (Test-Path "$ROOT\dist\FRIDAY")     { Remove-Item -Recurse -Force "$ROOT\dist\FRIDAY" }
if (Test-Path "$ROOT\build")            { Remove-Item -Recurse -Force "$ROOT\build" }

# Stage 3 — PyInstaller
Write-Host ""
Write-Host "[3/4] running PyInstaller…"
& python -m PyInstaller "$ROOT\packaging\FRIDAY.spec" --noconfirm --clean
if (-not (Test-Path "$ROOT\dist\FRIDAY\FRIDAY.exe")) {
    throw "PyInstaller did not produce dist\FRIDAY\FRIDAY.exe — see build log"
}
$sz = (Get-ChildItem -Recurse "$ROOT\dist\FRIDAY" | Measure-Object Length -Sum).Sum / 1MB
Write-Host "  dist\FRIDAY\  size: $([int]$sz) MB"

# Stage 4 — Inno Setup (optional)
Write-Host ""
Write-Host "[4/4] building Inno Setup installer…"
$iscc = "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe"
$iscc2 = "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
$iss = if (Test-Path $iscc)  { $iscc }
       elseif (Test-Path $iscc2) { $iscc2 }
       else { $null }
if (-not $iss) {
    Write-Host "  Inno Setup not found — skipping installer build."
    Write-Host "  Install from https://jrsoftware.org/isdl.php to enable."
} else {
    & $iss "$ROOT\packaging\installer.iss"
    Write-Host "  installer: dist\FRIDAY_Setup_v$VERSION.exe"
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  BUILD COMPLETE" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host "  Portable folder:  dist\FRIDAY\"
Write-Host "  Run on target machine:  dist\FRIDAY\FRIDAY.exe"
Write-Host "================================================" -ForegroundColor Green
