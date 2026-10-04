param([switch]$CloseAssistant)

$ErrorActionPreference = 'Stop'
. 'D:\codex\bin\Initialize-CodexEnvironment.ps1'
$repairRoot = 'D:\codex\CodexWork\clash'
$repairWork = "$repairRoot\work\task-stop-repair-20261004"
$repairRelease = "$repairRoot\outputs\wpf-desktop-stop-repair-20261004"
$repairInstalled = "$repairRoot\outputs\wpf-desktop-20261004\app"
$repairExe = "$repairInstalled\ClashAssistant.Desktop.exe"
$repairBridge = "$repairRelease\backend\ClashBackend.exe"
$repairFiles = @('ClashAssistant.Desktop.exe','ClashAssistant.Desktop.dll','ClashAssistant.Desktop.pdb','ClashAssistant.Desktop.deps.json','ClashAssistant.Desktop.runtimeconfig.json')

# Inspect all installation paths before copying any files or stopping an owner.
foreach ($repairPath in @($repairInstalled,$repairRelease,$repairWork)) {
    $resolvedRepairPath = [IO.Path]::GetFullPath($repairPath)
    if (-not $resolvedRepairPath.StartsWith("$repairRoot\",[StringComparison]::OrdinalIgnoreCase)) {
        throw "Installation target escaped the requested project: $resolvedRepairPath"
    }
}
foreach ($repairFile in $repairFiles) {
    if (-not (Test-Path -LiteralPath "$repairRelease\app\$repairFile" -PathType Leaf)) { throw "Missing verified file: $repairFile" }
}
$repairOwners = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'ClashAssistant.Desktop.exe' -and $_.ExecutablePath -eq $repairExe
})
if ($repairOwners.Count -gt 0 -and -not $CloseAssistant) { throw 'The installed assistant is still open. Exit it normally before installing.' }
if ($repairOwners.Count -gt 0) {
    $repairFrontend = Get-Content -LiteralPath "$repairRoot\work\wpf-desktop\frontend-state.json" -Raw | ConvertFrom-Json
    if ($repairFrontend.pid -notin $repairOwners.ProcessId) {
        throw 'Frontend state does not belong to the installed assistant owner.'
    }
}
$repairEmulatorBaseline = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('MEmu.exe','MEmuHeadless.exe','MEmuSVC.exe') -and
    $_.ExecutablePath.StartsWith("$repairRoot\work\downloads\",[StringComparison]::OrdinalIgnoreCase)
} | Select-Object ProcessId,Name,ExecutablePath,CreationDate)
$repairEmulatorBaseline | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$repairWork\installation-emulator-before.json" -Encoding utf8

# A hidden bridge stops exact recorded owners, including previous package paths.
$repairInfo = [Diagnostics.ProcessStartInfo]::new($repairBridge)
$repairInfo.WorkingDirectory = Split-Path -LiteralPath $repairBridge
$repairInfo.UseShellExecute = $false
$repairInfo.CreateNoWindow = $true
$repairInfo.RedirectStandardInput = $true
$repairInfo.RedirectStandardOutput = $true
$repairInfo.RedirectStandardError = $true
$repairInfo.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
$repairInfo.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
$repairInfo.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
$repairInfo.ArgumentList.Add('--data-root')
$repairInfo.ArgumentList.Add($repairRoot)
$repairInfo.Environment['PYCLASHBOT_DATA_ROOT'] = $repairRoot
$repairStopper = [Diagnostics.Process]::new()
$repairStopper.StartInfo = $repairInfo
try {
    if (-not $repairStopper.Start()) { throw 'Unable to start the verified stop bridge.' }
    $repairOutputTask = $repairStopper.StandardOutput.ReadToEndAsync()
    $repairErrorTask = $repairStopper.StandardError.ReadToEndAsync()
    $repairStopper.StandardInput.WriteLine('{"id":"install-stop","command":"stop"}')
    $repairStopper.StandardInput.WriteLine('{"id":"install-shutdown","command":"shutdown"}')
    $repairStopper.StandardInput.Flush()
    $repairStopper.StandardInput.Close()
    if (-not $repairStopper.WaitForExit(15000)) { $repairStopper.Kill(); throw 'Stop was not confirmed within the installation budget.' }
    $repairResponses = @($repairOutputTask.GetAwaiter().GetResult() -split "`n" | Where-Object { $_.Trim().Length -gt 0 } | ForEach-Object { $_ | ConvertFrom-Json })
    $repairStopResult = @($repairResponses | Where-Object id -eq 'install-stop')
    if ($repairStopper.ExitCode -ne 0 -or $repairStopResult.Count -ne 1 -or -not $repairStopResult[0].ok -or $repairStopResult[0].data.state -ne 'stopped') {
        throw 'The verified bridge did not confirm a stopped task; installation has been left unchanged.'
    }
    $repairResponses | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath "$repairWork\installation-stop.json" -Encoding utf8
} finally { $repairStopper.Dispose() }

$repairClosed = @()
$repairOldBridges = @()
foreach ($repairOwner in $repairOwners) {
    $repairOldBridges += @(Get-CimInstance Win32_Process | Where-Object {
        $_.ParentProcessId -eq $repairOwner.ProcessId -and $_.Name -eq 'ClashBackend.exe' -and
        $_.ExecutablePath.StartsWith("$repairRoot\outputs\",[StringComparison]::OrdinalIgnoreCase)
    })
    $repairProcess = [Diagnostics.Process]::GetProcessById($repairOwner.ProcessId)
    try {
        if (-not $repairProcess.MainModule.FileName.Equals($repairExe,[StringComparison]::OrdinalIgnoreCase) -or
            [Math]::Abs(($repairProcess.StartTime - $repairOwner.CreationDate).TotalSeconds) -gt 0.02) {
            throw 'Assistant identity changed before shutdown; installation aborted.'
        }
        $repairFrontend = Get-Content -LiteralPath "$repairRoot\work\wpf-desktop\frontend-state.json" -Raw | ConvertFrom-Json
        if ($repairFrontend.pid -ne $repairOwner.ProcessId) { throw 'The frontend owner changed during installation.' }
        $repairWasEmbedded = $repairFrontend.emulator.embedded -or $repairFrontend.emulator.owner_lock_held
        if ($repairWasEmbedded -or $repairFrontend.visible) {
            # WM_CLOSE invokes this app's own HideToTray/Detach path. No input,
            # foreground activation, or external native-window restore is used.
            if (-not $repairProcess.CloseMainWindow()) { throw 'The assistant did not accept its background close request.' }
            $repairDetachDeadline = [DateTime]::UtcNow.AddSeconds(6)
            do {
                Start-Sleep -Milliseconds 100
                $repairFrontend = Get-Content -LiteralPath "$repairRoot\work\wpf-desktop\frontend-state.json" -Raw | ConvertFrom-Json
                $repairDetached = $repairFrontend.pid -eq $repairOwner.ProcessId -and
                    -not $repairFrontend.visible -and -not $repairFrontend.emulator.embedded -and
                    -not $repairFrontend.emulator.owner_lock_held
            } until ($repairDetached -or [DateTime]::UtcNow -ge $repairDetachDeadline)
            if (-not $repairDetached) { throw 'The assistant did not confirm game-window restoration; it remains open.' }
            if ($repairWasEmbedded) {
                $repairNativeRecovery = Get-Content -LiteralPath "$repairRoot\work\native-window-recovery.json" -Raw | ConvertFrom-Json
                if (-not $repairNativeRecovery.restored) { throw 'The native recovery journal does not confirm restoration.' }
            }
            $repairFrontend | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath "$repairWork\installation-frontend-after-detach.json" -Encoding utf8
        }
        $repairProcess.Kill()
        if (-not $repairProcess.WaitForExit(3000)) { throw 'The assistant did not exit.' }
        $repairClosed += $repairOwner.ProcessId
    } finally { $repairProcess.Dispose() }
}
foreach ($repairOldBridge in $repairOldBridges) {
    $repairProcess = Get-Process -Id $repairOldBridge.ProcessId -ErrorAction SilentlyContinue
    if ($null -ne $repairProcess) {
        try {
            if (-not $repairProcess.WaitForExit(2500)) {
                if (-not $repairProcess.MainModule.FileName.Equals($repairOldBridge.ExecutablePath,[StringComparison]::OrdinalIgnoreCase) -or
                    [Math]::Abs(($repairProcess.StartTime - $repairOldBridge.CreationDate).TotalSeconds) -gt 0.02) {
                    throw 'Old bridge identity changed; installation aborted.'
                }
                $repairProcess.Kill()
                if (-not $repairProcess.WaitForExit(2000)) { throw 'The old bridge did not exit.' }
            }
        } finally { $repairProcess.Dispose() }
    }
}

foreach ($repairFile in $repairFiles) {
    Copy-Item -LiteralPath "$repairRelease\app\$repairFile" -Destination "$repairInstalled\$repairFile" -Force
    if ((Get-FileHash -LiteralPath "$repairInstalled\$repairFile").Hash -ne (Get-FileHash -LiteralPath "$repairRelease\app\$repairFile").Hash) {
        throw "Copied file hash differs: $repairFile"
    }
}
@{data_root=$repairRoot;backend_path=$repairBridge} | ConvertTo-Json | Set-Content -LiteralPath "$repairInstalled\wpf-runtime.json" -Encoding utf8
foreach ($repairEmulator in $repairEmulatorBaseline) {
    $repairCurrentEmulator = Get-CimInstance Win32_Process -Filter "ProcessId=$($repairEmulator.ProcessId)"
    if ($null -eq $repairCurrentEmulator -or $repairCurrentEmulator.CreationDate -ne $repairEmulator.CreationDate -or
        $repairCurrentEmulator.ExecutablePath -ne $repairEmulator.ExecutablePath) {
        throw "The preserved emulator identity changed: $($repairEmulator.Name)"
    }
}
$repairInstallation = [ordered]@{
    status='PASS_INSTALLED_VERIFIED_REPAIR'; installed_at=[DateTimeOffset]::Now.ToString('O');
    version='2026.10.4.4'; installed_executable=$repairExe; backend=$repairBridge;
    closed_assistant_pids=$repairClosed; new_window_launched=$false;
    emulator_processes_preserved=$repairEmulatorBaseline; game_window_restored=$true;
    installed_files=@($repairFiles | ForEach-Object { @{file=$_;sha256=(Get-FileHash -LiteralPath "$repairInstalled\$_").Hash} });
    rollback_app="$repairWork\package-before-app"
}
$repairInstallation | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$repairWork\installation.json" -Encoding utf8
$repairInstallation | ConvertTo-Json -Depth 8
