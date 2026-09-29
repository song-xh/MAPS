$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$taskName = 'MAPS-RLCAPA-Chengdu-Progress'
$logPath = Join-Path $repoRoot 'output\presets\rl-capa-monitor.log'
$comparisonPath = Join-Path $repoRoot 'output\presets\chengdu\rl-capa-comparison.json'
$chunkPath = Join-Path $repoRoot 'output\presets\chengdu\rl-capa-recomputed'

if (Test-Path -LiteralPath $comparisonPath) {
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) Complete; replay verified."
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    exit 0
}

$chunks = @(Get-ChildItem -LiteralPath $chunkPath -Filter 'frames-*.json.gz' -File -ErrorAction SilentlyContinue).Count
$running = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -match 'scripts.rerun_chengdu_rlcapa'
}
Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) Chengdu RL-CAPA: $chunks/22 saved chunks."
if ($running) {
    exit 2
}
Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) Run stopped before verification."
Disable-ScheduledTask -TaskName $taskName | Out-Null
exit 1
