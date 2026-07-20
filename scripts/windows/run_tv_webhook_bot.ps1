param(
    [string]$RepoPath = "",
    [string]$PythonPath = "",
    [string]$Interval = "15m",
    [string]$StateFile = "mt5_trading_state.db",
    [string]$Host = "0.0.0.0",
    [int]$Port = 80,
    [string]$Path = "/tradingview/webhook"
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

$LogDir = Join-Path $RepoPath "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$WrapperLog = Join-Path $LogDir "tv_webhook_wrapper.log"

Set-Location $RepoPath
$env:PYTHONPATH = $RepoPath

while ($true) {
    $stamp = (Get-Date).ToString("s")
    Add-Content -Path $WrapperLog -Value "[$stamp] Starting TradingView webhook bot"

    $args = @(
        "-m", "trading_bot.bot",
        "--mode", "tv-webhook",
        "--interval", "$Interval",
        "--state-file", "$StateFile",
        "--tv-host", "$Host",
        "--tv-port", "$Port",
        "--tv-path", "$Path"
    )

    & $PythonPath @args
    $exitCode = $LASTEXITCODE

    $doneStamp = (Get-Date).ToString("s")
    Add-Content -Path $WrapperLog -Value "[$doneStamp] TradingView webhook bot exited with code $exitCode"

    # Exit cleanly when process exited without error.
    if ($exitCode -eq 0) {
        break
    }

    Add-Content -Path $WrapperLog -Value "[$doneStamp] Restarting in 30 seconds"
    Start-Sleep -Seconds 30
}
