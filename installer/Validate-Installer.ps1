[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$TestRoot = (Join-Path $PSScriptRoot ('validation-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
)
$ErrorActionPreference = 'Stop'
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$testPath = [IO.Path]::GetFullPath($TestRoot)
if (-not $testPath.StartsWith('D:\codex\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Test output must stay inside D:\codex.'
}
if (Test-Path -LiteralPath $testPath) { throw 'Use a new test directory.' }
New-Item -ItemType Directory -Path $testPath | Out-Null
$savedEnvironment = @{}
foreach ($name in @('DOTNET_BUNDLE_EXTRACT_BASE_DIR', 'TEMP', 'TMP')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:DOTNET_BUNDLE_EXTRACT_BASE_DIR = Join-Path $testPath 'bundle-cache'
    $env:TEMP = Join-Path $testPath 'temp'
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Path $env:TEMP | Out-Null
    $results = [Collections.Generic.List[object]]::new()
    function Invoke-InstallerCheck {
        param([string]$Name, [string[]]$Arguments, [int]$ExpectedCode = 0)
        $stdout = Join-Path $testPath ($Name + '.stdout.json')
        $stderr = Join-Path $testPath ($Name + '.stderr.json')
        $escapedArguments = @($Arguments | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' })
        $process = Start-Process -FilePath $installerPath -ArgumentList $escapedArguments -WorkingDirectory $testPath `
            -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if ($process.ExitCode -ne $ExpectedCode) {
            throw "$Name returned $($process.ExitCode), expected $ExpectedCode. $(Get-Content -LiteralPath $stderr -Raw)"
        }
        $jsonPath = if ($ExpectedCode -eq 0) { $stdout } else { $stderr }
        $json = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
        if ($json.ok -ne ($ExpectedCode -eq 0)) { throw "$Name JSON status mismatch." }
        $results.Add([ordered]@{ name = $Name; passed = $true; exit_code = $process.ExitCode; details = $json })
        return $json
    }
    function Invoke-OfflineProcess {
        param([string]$Name, [string]$Executable, [string[]]$Arguments, [string]$InputData = '', [string]$DataRoot)
        $process = [Diagnostics.Process]::new()
        try {
            $process.StartInfo.FileName = $Executable
            $process.StartInfo.Arguments = (@($Arguments | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' }) -join ' ')
            $process.StartInfo.WorkingDirectory = Split-Path -Parent $Executable
            $process.StartInfo.UseShellExecute = $false
            $process.StartInfo.CreateNoWindow = $true
            $process.StartInfo.RedirectStandardInput = $true
            $process.StartInfo.RedirectStandardOutput = $true
            $process.StartInfo.RedirectStandardError = $true
            $process.StartInfo.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
            $process.StartInfo.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
            $process.StartInfo.EnvironmentVariables['PYTHONUTF8'] = '1'
            $process.StartInfo.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
            if ($DataRoot) { $process.StartInfo.EnvironmentVariables['PYCLASHBOT_DATA_ROOT'] = $DataRoot }
            if (-not $process.Start()) { throw "$Name process did not start." }
            $stdoutTask = $process.StandardOutput.ReadToEndAsync()
            $stderrTask = $process.StandardError.ReadToEndAsync()
            if ($InputData) { $process.StandardInput.Write($InputData) }
            $process.StandardInput.Close()
            if (-not $process.WaitForExit(60000)) {
                $process.Kill()
                $null = $process.WaitForExit(5000)
                throw "$Name exceeded the offline verification timeout."
            }
            $stdout = $stdoutTask.GetAwaiter().GetResult()
            $stderr = $stderrTask.GetAwaiter().GetResult()
            [IO.File]::WriteAllText((Join-Path $testPath ($Name + '.stdout.txt')), $stdout, [Text.UTF8Encoding]::new($false))
            [IO.File]::WriteAllText((Join-Path $testPath ($Name + '.stderr.txt')), $stderr, [Text.UTF8Encoding]::new($false))
            if ($process.ExitCode -ne 0) { throw "$Name failed ($($process.ExitCode)): $stderr" }
            return [ordered]@{ exit_code = $process.ExitCode; stdout = $stdout }
        } finally {
            $process.Dispose()
        }
    }
    $selfCheck = Invoke-InstallerCheck -Name 'self-check' -Arguments @('--self-check')
    $freshTarget = Join-Path $testPath 'fresh-install'
    $null = Invoke-InstallerCheck -Name 'extract-fresh' -Arguments @('--extract-only', $freshTarget)
    foreach ($required in @('app\ClashAssistant.Desktop.exe', 'backend\ClashBackend.exe', 'app\wpf-runtime.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $freshTarget $required) -PathType Leaf)) { throw "Missing installed file: $required" }
    }
    $runtime = Get-Content -LiteralPath (Join-Path $freshTarget 'app\wpf-runtime.json') -Raw | ConvertFrom-Json
    if ($runtime.distribution -ne $true -or $runtime.data_root -ne '../data' -or $runtime.backend_path -ne '../backend/ClashBackend.exe') {
        throw 'Installed runtime configuration mismatch.'
    }
    if (@(Get-ChildItem -LiteralPath (Join-Path $freshTarget 'data') -Force).Count -ne 0) { throw 'New data directory is not empty.' }
    $results.Add([ordered]@{ name = 'runtime-config-and-empty-data'; passed = $true })
    $existingTarget = Join-Path $testPath 'empty-install'
    New-Item -ItemType Directory -Path $existingTarget | Out-Null
    $null = Invoke-InstallerCheck -Name 'extract-empty' -Arguments @('--extract-only', $existingTarget)
    $protectedTarget = Join-Path $testPath 'protected'
    New-Item -ItemType Directory -Path $protectedTarget | Out-Null
    $sentinel = Join-Path $protectedTarget 'existing-user-file.txt'
    [IO.File]::WriteAllText($sentinel, 'Never overwrite existing user data.', [Text.UTF8Encoding]::new($false))
    $sentinelBefore = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
    $null = Invoke-InstallerCheck -Name 'reject-nonempty' -Arguments @('--extract-only', $protectedTarget) -ExpectedCode 1
    if ($sentinelBefore -ne (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -or @(Get-ChildItem -LiteralPath $protectedTarget -Force).Count -ne 1) {
        throw 'Existing destination content changed.'
    }
    $null = Invoke-InstallerCheck -Name 'reject-external' -Arguments @('--extract-only', 'C:\Games\ClashAssistant-Installer-NoWrite-Test') -ExpectedCode 1
    $null = Invoke-InstallerCheck -Name 'reject-relative' -Arguments @('--extract-only', 'relative-target') -ExpectedCode 1
    $junctionBacking = Join-Path $testPath 'junction-backing'
    $junctionPath = Join-Path $testPath 'junction-target'
    New-Item -ItemType Directory -Path $junctionBacking | Out-Null
    New-Item -ItemType Junction -Path $junctionPath -Target $junctionBacking | Out-Null
    $null = Invoke-InstallerCheck -Name 'reject-junction' -Arguments @('--extract-only', $junctionPath) -ExpectedCode 1
    if (@(Get-ChildItem -LiteralPath $junctionBacking -Force).Count -ne 0) { throw 'Reparse backing directory changed.' }
    $unicodeTarget = Join-Path $testPath '中文安装验收 空格'
    $null = Invoke-InstallerCheck -Name 'extract-unicode' -Arguments @('--extract-only', $unicodeTarget)
    $unicodeData = Join-Path $unicodeTarget 'data'
    if (@(Get-ChildItem -LiteralPath $unicodeData -Force).Count -ne 0) { throw 'Unicode installation data directory is not empty.' }
    $settingsOutput = Join-Path $unicodeData 'settings-check.json'
    $null = Invoke-OfflineProcess -Name 'unicode-settings' -Executable (Join-Path $unicodeTarget 'app\ClashAssistant.Desktop.exe') `
        -Arguments @('--settings-check', $settingsOutput) -DataRoot $unicodeData
    $settings = Get-Content -LiteralPath $settingsOutput -Raw | ConvertFrom-Json
    if ($settings.distribution -ne $true -or $settings.backend_exists -ne $true -or $settings.own_paths_valid -ne $true `
        -or $settings.outside_install_rejected -ne $true `
        -or -not [string]::Equals($settings.install_root, $unicodeTarget, [StringComparison]::OrdinalIgnoreCase) `
        -or -not [string]::Equals($settings.data_root, $unicodeData, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unicode desktop settings verification failed.'
    }
    Move-Item -LiteralPath $settingsOutput -Destination (Join-Path $testPath 'unicode-settings.json')
    $results.Add([ordered]@{ name = 'unicode-desktop-settings'; passed = $true; details = $settings })
    $backendExe = Join-Path $unicodeTarget 'backend\ClashBackend.exe'
    $backendCheck = Invoke-OfflineProcess -Name 'unicode-backend-check' -Executable $backendExe `
        -Arguments @('--self-check') -DataRoot $unicodeData
    $backendHealth = $backendCheck.stdout | ConvertFrom-Json
    if ($backendHealth.status -ne 'ok' -or $backendHealth.templates.status -ne 'healthy' -or $backendHealth.hand_samples -le 0 `
        -or -not [string]::Equals($backendHealth.data_root, $unicodeData, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unicode backend resource verification failed.'
    }
    $results.Add([ordered]@{ name = 'unicode-backend-resources'; passed = $true; details = $backendHealth })
    $requests = '{"id":"unicode-snapshot","command":"snapshot"}' + [Environment]::NewLine `
        + '{"id":"unicode-shutdown","command":"shutdown"}' + [Environment]::NewLine
    $readOnly = Invoke-OfflineProcess -Name 'unicode-read-only' -Executable $backendExe `
        -Arguments @('--read-only', '--data-root', $unicodeData) -InputData $requests -DataRoot $unicodeData
    $responses = @($readOnly.stdout -split '\r?\n' | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    if ($responses.Count -ne 2 -or $responses[0].id -ne 'unicode-snapshot' -or $responses[0].ok -ne $true `
        -or $responses[0].data.state -ne 'stopped' -or $responses[0].data.frozen -ne $true `
        -or -not [string]::Equals($responses[0].data.runtime.data_root, $unicodeData, [StringComparison]::OrdinalIgnoreCase) `
        -or $responses[1].id -ne 'unicode-shutdown' -or $responses[1].ok -ne $true -or $responses[1].data.shutdown -ne $true) {
        throw 'Unicode read-only backend protocol verification failed.'
    }
    $results.Add([ordered]@{ name = 'unicode-read-only-snapshot-shutdown'; passed = $true; details = $responses })
    $temporaryStages = @(Get-ChildItem -LiteralPath $testPath -Directory -Force | Where-Object Name -Like '.ClashAssistant-install-*')
    if ($temporaryStages.Count -ne 0) { throw 'Staging directory residue remains.' }
    $report = [ordered]@{
        passed = $true
        installer = $installerPath
        installer_sha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash
        self_check = $selfCheck
        results = @($results)
        test_root = $testPath
        generated_at = (Get-Date).ToString('o')
    }
    $reportPath = Join-Path $testPath 'validation-report.json'
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
    $report | ConvertTo-Json -Depth 8
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        if ($null -eq $savedEnvironment[$name]) {
            [Environment]::SetEnvironmentVariable($name, [NullString]::Value, 'Process')
        } else {
            [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
        }
    }
}
