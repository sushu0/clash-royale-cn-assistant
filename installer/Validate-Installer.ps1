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
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
