param([int]$WaitForPid = 0)

$ErrorActionPreference = 'Stop'
if ($WaitForPid -gt 0) {
    Wait-Process -Id $WaitForPid -ErrorAction SilentlyContinue
}

Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
python -m maps_demo.presets all
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

python -m scripts.verify_preset_experiments
exit $LASTEXITCODE
