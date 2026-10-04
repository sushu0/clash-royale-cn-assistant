param([ValidateSet('567','hog','random')][string]$Strategy = 'random')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $repo '..')).Path
$python = Join-Path $taskRoot 'work\venv\Scripts\python.exe'
$config = Join-Path $taskRoot 'work\runtime-config.json'
if ($env:PYCLASHBOT_CONFIG) { $config = $env:PYCLASHBOT_CONFIG }
if (Test-Path -LiteralPath $config -PathType Leaf) {
    $settings = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
    if ($settings.python) { $python = $settings.python }
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Required Python missing: $python" }
Push-Location -LiteralPath $repo
try {
    & $python 'scripts\start_cn_bot.py' '--strategy' $Strategy
    if ($LASTEXITCODE -ne 0) { throw "Bot startup failed with exit $LASTEXITCODE" }
} finally {
    Pop-Location
}
