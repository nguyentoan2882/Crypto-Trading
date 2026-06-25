param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Output = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "Investment_Project_Export.md")
)

$ErrorActionPreference = "Stop"
$textExtensions = @(
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".md", ".txt", ".json", ".toml", ".yaml", ".yml",
    ".ps1", ".bat", ".cmd", ".csv", ".tsv", ".html", ".css",
    ".sql", ".ini", ".cfg", ".conf", ".gitignore"
)
$languageMap = @{
    ".py" = "python"; ".js" = "javascript"; ".mjs" = "javascript"; ".cjs" = "javascript"
    ".ts" = "typescript"; ".tsx" = "tsx"; ".jsx" = "jsx"; ".md" = "markdown"
    ".json" = "json"; ".toml" = "toml"; ".yaml" = "yaml"; ".yml" = "yaml"
    ".ps1" = "powershell"; ".bat" = "batch"; ".cmd" = "batch"; ".csv" = "csv"
    ".tsv" = "tsv"; ".html" = "html"; ".css" = "css"; ".sql" = "sql"
}

function Redact-Secrets([string]$Content, [string]$Name) {
    if ($Name -eq ".env") {
        return (($Content -split "`r?`n") | ForEach-Object {
            if ($_ -match '^\s*([^#=\s]+)\s*=(.*)$') {
                "$($Matches[1])=<REDACTED>"
            } else {
                $_
            }
        }) -join "`n"
    }
    $patterns = @(
        '(?im)^(\s*(?:TELEGRAM_BOT_TOKEN|BOT_TOKEN|API_KEY|API_SECRET|SECRET_KEY|PASSWORD|PRIVATE_KEY|ACCESS_TOKEN|REFRESH_TOKEN)\s*[=:]\s*)[^\r\n,}]+',
        '(?i)("?(?:api[_-]?key|api[_-]?secret|bot[_-]?token|access[_-]?token|refresh[_-]?token|password|private[_-]?key)"?\s*:\s*")[^"]+(")'
    )
    $result = $Content
    $result = [regex]::Replace($result, $patterns[0], '$1<REDACTED>')
    $result = [regex]::Replace($result, $patterns[1], '$1<REDACTED>$2')
    return $result
}

$excludeRegex = '(^|[\\/])(\.git|__pycache__|node_modules|\.venv|venv)([\\/]|$)|\.pyc$|Investment_Project_Export\.md$'
$files = Get-ChildItem -LiteralPath $Root -Recurse -File -Force |
    Where-Object { $_.FullName -notmatch $excludeRegex } |
    Sort-Object FullName
$rootPrefix = $Root.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar

$writer = [System.IO.StreamWriter]::new($Output, $false, [System.Text.UTF8Encoding]::new($false))
try {
    $writer.WriteLine("# Investment Project Export")
    $writer.WriteLine("")
    $writer.WriteLine("- Exported: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')")
    $writer.WriteLine('- Root: `' + $Root + '`')
    $writer.WriteLine("- Files: $($files.Count)")
    $writer.WriteLine("- Security: recognizable secrets and all `.env` values are redacted.")
    $writer.WriteLine("")
    $writer.WriteLine("## Project tree")
    $writer.WriteLine("")
    $writer.WriteLine('```text')
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($rootPrefix.Length).Replace("\", "/")
        $writer.WriteLine("$relative ($($file.Length) bytes)")
    }
    $writer.WriteLine('```')
    $writer.WriteLine("")
    $writer.WriteLine("## File contents")

    foreach ($file in $files) {
        $relative = $file.FullName.Substring($rootPrefix.Length).Replace("\", "/")
        $extension = $file.Extension.ToLowerInvariant()
        $isText = ($textExtensions -contains $extension) -or $file.Name -in @(".env", ".gitignore")
        $writer.WriteLine("")
        $writer.WriteLine('### `' + $relative + '`')
        $writer.WriteLine("")
        if (-not $isText) {
            $writer.WriteLine("> Binary or unsupported file. Size: $($file.Length) bytes. Content not embedded.")
            continue
        }
        try {
            $content = [System.IO.File]::ReadAllText($file.FullName)
            $content = Redact-Secrets $content $file.Name
            $fence = '```'
            if ($content.Contains('```')) { $fence = '````' }
            $language = if ($languageMap.ContainsKey($extension)) { $languageMap[$extension] } else { "text" }
            $writer.WriteLine("$fence$language")
            $writer.WriteLine($content)
            $writer.WriteLine($fence)
        } catch {
            $writer.WriteLine("> Could not read as text: $($_.Exception.Message)")
        }
    }
} finally {
    $writer.Dispose()
}

$result = Get-Item -LiteralPath $Output
[pscustomobject]@{
    Output = $result.FullName
    Files = $files.Count
    SizeMB = [math]::Round($result.Length / 1MB, 2)
}
