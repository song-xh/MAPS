$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$statusPath = Join-Path $repoRoot 'output\presets\update_status.json'
$logPath = Join-Path $repoRoot 'output\presets\update_monitor.log'
$taskName = 'MAPS-Preset-Progress'

if (-not (Test-Path -LiteralPath $statusPath)) {
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) No run status found."
    exit 1
}

$status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
$line = "$(Get-Date -Format o) $($status.state) $($status.city)/$($status.algorithm) $($status.percent)% $($status.label)"
Add-Content -LiteralPath $logPath -Value $line
if ($status.state -eq 'complete' -or $status.state -eq 'failed') {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    exit 0
}

$running = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -match 'scripts.update_preset_algorithms'
}
if (-not $running) {
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) Preset process stopped before completion."
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    exit 1
}
