. 'D:\codex\bin\Initialize-CodexEnvironment.ps1'
$ErrorActionPreference = 'Stop'
$checkRoot = Join-Path $PSScriptRoot ('fake-tool-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $checkRoot | Out-Null
$fakeTool = Join-Path $PSScriptRoot 'FakeTool\bin\Debug\net10.0\FakeTool.exe'
$running = & $fakeTool isvmrunning -i 0
if ($LASTEXITCODE -ne 0 -or $running -ne 'running') { throw 'simulated VM query failed' }
$unexpected = Start-Process -FilePath $fakeTool -ArgumentList @('unsupported-command') -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $checkRoot 'unsupported.stdout') -RedirectStandardError (Join-Path $checkRoot 'unsupported.stderr')
if ($unexpected.ExitCode -ne 64) { throw 'unsupported simulated command was not rejected' }
$previousMarker = $env:CLASH_FAKE_TOOL_MARKER
$marker = Join-Path $checkRoot 'get-state.marker.json'
$process = $null
try {
    $env:CLASH_FAKE_TOOL_MARKER = $marker
    $process = Start-Process -FilePath $fakeTool -ArgumentList @('-s', 'fixture-only', 'get-state') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $checkRoot 'get-state.stdout') -RedirectStandardError (Join-Path $checkRoot 'get-state.stderr')
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $marker)) {
        if ($watch.Elapsed.TotalSeconds -ge 5) { throw 'get-state phase marker not written' }
        Start-Sleep -Milliseconds 25
    }
    $phase = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($phase.phase -ne 'waiting-for-get-state' -or $phase.pid -ne $process.Id -or $phase.real_device_access -ne $false) { throw 'get-state phase marker invalid' }
    if ($process.HasExited) { throw 'get-state simulation should still be waiting' }
    $result = [ordered]@{ passed = $true; executable = $fakeTool; marker = $marker; owned_process_id = $process.Id; vm_query = 'running'; unknown_command_exit_code = 64; phase = $phase.phase; real_device_access = $false }
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'fake-tool-verification.json') -Encoding utf8
    $result | ConvertTo-Json
}
finally {
    if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    $env:CLASH_FAKE_TOOL_MARKER = $previousMarker
}
