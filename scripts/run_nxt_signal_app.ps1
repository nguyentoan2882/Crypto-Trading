$ErrorActionPreference = "Stop"

$Root = "D:\Workspace\Codex\Investment"
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$LogDir = Join-Path $Root "outputs"
$LogPath = Join-Path $LogDir "nxt_signal_app_server.log"
$Port = 6789

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

$Listener = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Listener) {
    Add-Content -Path $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] App already listening on 127.0.0.1:$Port"
    exit 0
}

Add-Content -Path $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting NXT Signal App on 127.0.0.1:$Port"
& $Python -u "app\nxt_signal_app.py" --host 127.0.0.1 --port $Port 2>&1 | ForEach-Object {
    Add-Content -Path $LogPath -Value $_
}
$ExitCode = $LASTEXITCODE
Add-Content -Path $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] App stopped with exit code $ExitCode"
exit $ExitCode
