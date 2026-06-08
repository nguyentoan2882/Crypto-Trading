$ErrorActionPreference = "Stop"

$Root = "D:\Workspace\Codex\Crypto trading"
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$LogDir = Join-Path $Root "outputs"
$LogPath = Join-Path $LogDir "daily_nxt_signal_scan.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

$StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogPath -Value "[$StartedAt] Starting NXT daily signal scan"

try {
    & $Python "scripts\daily_nxt_signal_scan.py" 2>&1 | ForEach-Object {
        Add-Content -Path $LogPath -Value $_
    }
    $ExitCode = $LASTEXITCODE
    $FinishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$FinishedAt] Finished with exit code $ExitCode"
    exit $ExitCode
}
catch {
    $FailedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$FailedAt] Failed: $($_.Exception.Message)"
    exit 1
}
