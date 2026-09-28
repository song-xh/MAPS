param([string]$PythonExe = 'python')

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$logPath = Join-Path $repoRoot 'output\presets\monitor.log'
$reportPath = Join-Path $repoRoot 'output\presets\verification.json'
$taskName = 'MAPS-Preset-Progress'

if (Test-Path -LiteralPath $reportPath) {
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($report.status -eq 'passed') {
        Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) Complete; verification passed."
        Disable-ScheduledTask -TaskName $taskName | Out-Null
        exit 0
    }
}

$status = & $PythonExe -m scripts.preset_progress 2>&1
Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) $status"
if ($LASTEXITCODE -eq 0) {
    & $PythonExe -m scripts.verify_preset_experiments *>> $logPath
    if ($LASTEXITCODE -eq 0) {
        Disable-ScheduledTask -TaskName $taskName | Out-Null
        exit 0
    }
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) Verification failed; task stopped."
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    exit 1
}
exit 2
