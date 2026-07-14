param(
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "scripts\arena_fleet.py"
$LogDir = Join-Path $Root "logs"
$Out = Join-Path $LogDir "arena_fleet.out.log"
$Err = Join-Path $LogDir "arena_fleet.err.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

if ($Foreground) {
    .\.venv\Scripts\python.exe -c "import runpy; runpy.run_path(r'scripts\arena_fleet.py', run_name='__main__')"
    exit $LASTEXITCODE
}

$proc = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-c", "import runpy; runpy.run_path(r'scripts\arena_fleet.py', run_name='__main__')") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $Out `
    -RedirectStandardError $Err `
    -PassThru

"Arena fleet started. PID=$($proc.Id)"
"Status: $Root\runtime\arena_fleet\status.json"
"Log:    $Root\logs\arena_fleet.log"
