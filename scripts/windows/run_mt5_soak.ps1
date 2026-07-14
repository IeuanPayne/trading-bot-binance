param(
    [string]$RepoPath = "",
    [string]$PythonPath = "",
    [int]$IntervalMinutes = 15,
    [int]$BufferSeconds = 5,
    [double]$OrderPct = 0.01,
    [double]$StopPips = 0.7,
    [string]$StateFile = "mt5_trading_state.db",
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $RepoPath ".venv\Scripts\python.exe"
}

if (-not (Test-Path $PythonPath)) {
    throw "Python executable not found at $PythonPath"
}

$ScriptPath = Join-Path $RepoPath "scripts\soak_mt5.py"
if (-not (Test-Path $ScriptPath)) {
    throw "MT5 soak script not found at $ScriptPath"
}

$LogDir = Join-Path $RepoPath "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$WrapperLog = Join-Path $LogDir "mt5_wrapper.log"

$env:PYTHONPATH = $RepoPath

while ($true) {
    $stamp = (Get-Date).ToString("s")
    Add-Content -Path $WrapperLog -Value "[$stamp] Starting MT5 soak process"

    $args = @(
        $ScriptPath,
        "--interval", "${IntervalMinutes}m",
        "--duration-hours", "0",
        "--buffer-seconds", "$BufferSeconds",
        "--order-pct", "$OrderPct",
        "--stop-pips", "$StopPips",
        "--state-file", "$StateFile"
    )

    if ($RunNow) {
        $args += "--run-now"
    }

    & $PythonPath @args
    $exitCode = $LASTEXITCODE

    $doneStamp = (Get-Date).ToString("s")
    Add-Content -Path $WrapperLog -Value "[$doneStamp] MT5 soak process exited with code $exitCode"

    if ($exitCode -eq 0) {
        break
    }

    Add-Content -Path $WrapperLog -Value "[$doneStamp] Restarting in 30 seconds"
    Start-Sleep -Seconds 30
}
