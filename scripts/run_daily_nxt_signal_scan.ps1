$ErrorActionPreference = "Stop"

$Root = "D:\Workspace\Codex\Investment"
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$LogDir = Join-Path $Root "outputs"
$LogPath = Join-Path $LogDir "daily_nxt_signal_scan.log"
$DefaultRetryDelays = "0,120,120,300"
$RetryText = if ($env:NXT_RETRY_DELAYS_SECONDS) { $env:NXT_RETRY_DELAYS_SECONDS } else { $DefaultRetryDelays }
$RetryDelaysSeconds = @($RetryText.Split(",") | ForEach-Object { [int]$_.Trim() })

if (-not $RetryDelaysSeconds.Count -or ($RetryDelaysSeconds | Where-Object { $_ -lt 0 })) {
    throw "NXT_RETRY_DELAYS_SECONDS must contain non-negative integers."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

$FinalExitCode = 1
$OriginalNotifyErrors = $env:NXT_NOTIFY_ERRORS
$OriginalSkipIfSuccess = $env:NXT_SKIP_IF_DAILY_SUCCESS
$env:NXT_SKIP_IF_DAILY_SUCCESS = "1"
$Mutex = New-Object System.Threading.Mutex($false, "Local\NXT_Daily_Telegram_Signal_Scan")
$HasMutex = $false

try {
    try {
        $HasMutex = $Mutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $HasMutex = $true
    }

    if (-not $HasMutex) {
        Add-Content -Path $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Another scanner instance is already running; skipped."
        $FinalExitCode = 0
        return
    }

    for ($Index = 0; $Index -lt $RetryDelaysSeconds.Count; $Index++) {
        $DelaySeconds = $RetryDelaysSeconds[$Index]
        if ($DelaySeconds -gt 0) {
            Start-Sleep -Seconds $DelaySeconds
        }

        $Attempt = $Index + 1
        $IsFinalAttempt = $Attempt -eq $RetryDelaysSeconds.Count
        if ($IsFinalAttempt) {
            if ($null -eq $OriginalNotifyErrors) {
                Remove-Item Env:NXT_NOTIFY_ERRORS -ErrorAction SilentlyContinue
            }
            else {
                $env:NXT_NOTIFY_ERRORS = $OriginalNotifyErrors
            }
        }
        else {
            $env:NXT_NOTIFY_ERRORS = "0"
        }

        $StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path $LogPath -Value "[$StartedAt] Starting NXT daily signal scan attempt $Attempt/$($RetryDelaysSeconds.Count)"

        try {
            $ProcessInfo = New-Object System.Diagnostics.ProcessStartInfo
            $ProcessInfo.FileName = $Python
            $ProcessInfo.Arguments = '"scripts\daily_nxt_signal_scan.py"'
            $ProcessInfo.WorkingDirectory = $Root
            $ProcessInfo.UseShellExecute = $false
            $ProcessInfo.CreateNoWindow = $true
            $ProcessInfo.RedirectStandardOutput = $true
            $ProcessInfo.RedirectStandardError = $true

            $Process = New-Object System.Diagnostics.Process
            $Process.StartInfo = $ProcessInfo
            [void]$Process.Start()
            $StdoutTask = $Process.StandardOutput.ReadToEndAsync()
            $StderrTask = $Process.StandardError.ReadToEndAsync()
            $Process.WaitForExit()
            $Stdout = $StdoutTask.Result
            $Stderr = $StderrTask.Result
            $FinalExitCode = $Process.ExitCode
            $Process.Dispose()

            foreach ($Line in ($Stdout -split "`r?`n")) {
                if ($Line) { Add-Content -Path $LogPath -Value $Line }
            }
            foreach ($Line in ($Stderr -split "`r?`n")) {
                if ($Line) { Add-Content -Path $LogPath -Value "ERROR: $Line" }
            }

            $FinishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            Add-Content -Path $LogPath -Value "[$FinishedAt] Attempt $Attempt finished with exit code $FinalExitCode"
            if ($FinalExitCode -eq 0) {
                break
            }
        }
        catch {
            $FinalExitCode = 1
            $FailedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            Add-Content -Path $LogPath -Value "[$FailedAt] Attempt $Attempt wrapper failure: $($_.Exception.Message)"
        }
    }
}
finally {
    if ($null -eq $OriginalNotifyErrors) {
        Remove-Item Env:NXT_NOTIFY_ERRORS -ErrorAction SilentlyContinue
    }
    else {
        $env:NXT_NOTIFY_ERRORS = $OriginalNotifyErrors
    }
    if ($null -eq $OriginalSkipIfSuccess) {
        Remove-Item Env:NXT_SKIP_IF_DAILY_SUCCESS -ErrorAction SilentlyContinue
    }
    else {
        $env:NXT_SKIP_IF_DAILY_SUCCESS = $OriginalSkipIfSuccess
    }
    if ($HasMutex) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
}

exit $FinalExitCode
