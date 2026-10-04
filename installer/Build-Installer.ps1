[CmdletBinding()]
param(
    [string]$PayloadZip = (Join-Path $PSScriptRoot '..\dist\ClashAssistant-Windows-x64-portable.zip'),
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\dist\installer')
)
$ErrorActionPreference = 'Stop'
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$buildRoot = Join-Path $repositoryRoot '.build\installer'
$payloadPath = (Resolve-Path -LiteralPath $PayloadZip -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $payloadPath -PathType Leaf)) {
    throw 'Payload ZIP must be a file.'
}
$outputLocation = if ([IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory
} else {
    Join-Path (Get-Location).Path $OutputDirectory
}
$outputPath = [IO.Path]::GetFullPath($outputLocation)
if (Test-Path -LiteralPath $outputPath) {
    if (-not (Test-Path -LiteralPath $outputPath -PathType Container)) {
        throw 'Output directory must be a directory.'
    }
    if (@(Get-ChildItem -LiteralPath $outputPath -Force).Count -ne 0) {
        throw 'Output directory must be new or empty; existing output will not be overwritten.'
    }
}
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw 'Install the .NET 10 SDK and make dotnet available on PATH.'
}
$savedEnvironment = @{}
foreach ($name in @('TEMP', 'TMP', 'NUGET_PACKAGES', 'DOTNET_CLI_HOME')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:TEMP = Join-Path $buildRoot 'temp'
    $env:TMP = $env:TEMP
    if (-not $env:NUGET_PACKAGES) { $env:NUGET_PACKAGES = Join-Path $buildRoot 'nuget\packages' }
    if (-not $env:DOTNET_CLI_HOME) { $env:DOTNET_CLI_HOME = Join-Path $buildRoot 'dotnet-home' }
    New-Item -ItemType Directory -Force -Path $env:TEMP, $env:NUGET_PACKAGES, $env:DOTNET_CLI_HOME, $outputPath | Out-Null
    $intermediatePath = Join-Path $buildRoot 'obj'
    $binaryPath = Join-Path $buildRoot 'bin'
    $publishArguments = @(
        'publish', (Join-Path $PSScriptRoot 'ClashAssistant.Installer.csproj'),
        '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true',
        '-p:PublishSingleFile=true', "-p:PayloadZipPath=$payloadPath",
        "-p:BaseIntermediateOutputPath=$intermediatePath/", "-p:BaseOutputPath=$binaryPath/",
        '-o', $outputPath
    )
    & dotnet @publishArguments
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed ($LASTEXITCODE)." }
    $result = Join-Path $outputPath 'ClashAssistant-Setup.exe'
    if (-not (Test-Path -LiteralPath $result -PathType Leaf)) { throw 'Installer executable was not created.' }
    [ordered]@{
        installer = $result
        installer_sha256 = (Get-FileHash -LiteralPath $result -Algorithm SHA256).Hash
        payload = $payloadPath
        payload_sha256 = (Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256).Hash
        runtime = 'win-x64'
        self_contained = $true
    } | ConvertTo-Json
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
