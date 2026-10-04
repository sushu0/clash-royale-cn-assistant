param()
$ErrorActionPreference = 'Stop'
. 'D:\codex\bin\Initialize-CodexEnvironment.ps1'
Set-Location -LiteralPath 'D:\codex\CodexWork\clash'
$repairDir = 'D:\codex\CodexWork\clash\work\emulator-repair-20261003'
$baseline = Get-Content -LiteralPath "$repairDir\config-before.json" -Raw | ConvertFrom-Json
$memucExe = 'D:\codex\CodexWork\clash\work\downloads\Microvirt\MEmu\memuc.exe'
$activeRunner = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'scripts[\\/](run_cn_1v1|watch_cn_1v1)\.py'
}
if ($activeRunner) { throw 'Stop the battle runner in its control window before restoring emulator settings.' }
& $memucExe stop -i 0
if ($LASTEXITCODE -ne 0) { throw 'Graceful emulator stop failed; no settings were restored.' }
$stillRunning = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('MEmu.exe','MEmuHeadless.exe') -and $_.ExecutablePath -like 'D:\codex\CodexWork\clash\work\downloads\Microvirt\*'
}
if ($stillRunning) { throw 'Emulator processes are still active; settings were not restored.' }
foreach ($configKey in @('cpus','memory','graphics_render_mode','fps')) {
    & $memucExe setconfigex -i 0 $configKey ([string]$baseline.$configKey)
    if ($LASTEXITCODE -ne 0) { throw "Restore failed: $configKey" }
}
& $memucExe setconfigex -i 0 custom_resolution 419 633 160
if ($LASTEXITCODE -ne 0) { throw 'Restore failed: resolution' }
Set-ItemProperty -LiteralPath $baseline.gpu_registry_path -Name $baseline.gpu_value_name -Value $baseline.gpu_before
$memuGui = Join-Path (Split-Path -LiteralPath $memucExe -Parent) 'MEmu.exe'
if (-not (Test-Path -LiteralPath $memuGui)) { throw 'Settings restored, but emulator GUI was not found.' }
& $memuGui
Write-Output 'Original 8 CPU / 6144 MB / DirectX settings restored. Game data and bot source were preserved.'
