param(
    [string]$Executable = 'D:\codex\CodexWork\clash\outputs\desktop-app-20261004\ClashAssistant.exe',
    [string]$EvidenceDirectory = 'D:\codex\CodexWork\clash\work\desktop-app-20261004'
)

$ErrorActionPreference = 'Stop'
. 'D:\codex\bin\Initialize-CodexEnvironment.ps1'
$resolvedExe = (Resolve-Path -LiteralPath $Executable).Path
$resolvedEvidence = [IO.Path]::GetFullPath($EvidenceDirectory)
if (-not $resolvedExe.StartsWith('D:\codex\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The portable executable must stay under D:\codex.'
}
if (-not $resolvedEvidence.StartsWith('D:\codex\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Shortcut evidence must stay under D:\codex.'
}
[IO.Directory]::CreateDirectory($resolvedEvidence) | Out-Null
$userShellFolders = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
$shellFolders = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
$desktop = [Environment]::ExpandEnvironmentVariables($userShellFolders.Desktop)
if (-not (Test-Path -LiteralPath $desktop -PathType Container)) {
    throw "Current Explorer desktop is absent: $desktop"
}
if ($desktop -ne $shellFolders.Desktop) {
    throw 'Explorer desktop registry values disagree; determine the current desktop before writing.'
}
$shortcutPath = Join-Path $desktop '皇室战争助手.lnk'
$priorShortcut = $null
if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
    $backupDirectory = Join-Path $resolvedEvidence 'shortcut-backup'
    [IO.Directory]::CreateDirectory($backupDirectory) | Out-Null
    $backupName = '皇室战争助手-' + (Get-Date -Format 'yyyyMMdd-HHmmss-ffff') + '.lnk'
    $backupPath = Join-Path $backupDirectory $backupName
    Copy-Item -LiteralPath $shortcutPath -Destination $backupPath
    $priorShortcut = @{ path = $backupPath; sha256 = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash }
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $resolvedExe
$shortcut.WorkingDirectory = Split-Path -Path $resolvedExe -Parent
$shortcut.Arguments = ''
$shortcut.IconLocation = $resolvedExe + ',0'
$shortcut.WindowStyle = 1
$shortcut.Description = '皇室战争助手：打开主界面，点击开始后运行；支持任务栏与系统托盘。'
$shortcut.Save()
$identitySource = Join-Path $PSScriptRoot 'cn_desktop_shortcut.cs'
if (-not ('Codex.ClashDesktopPackage.ShortcutIdentity' -as [type])) {
    Add-Type -Path $identitySource
}
$appId = 'Codex.ClashAssistant.Desktop.2026'
$savedAppId = [Codex.ClashDesktopPackage.ShortcutIdentity]::SetAndRead($shortcutPath, $appId)
if ($savedAppId -ne $appId) { throw 'Saved shortcut AppUserModelID does not match the desktop window.' }
$saved = $shell.CreateShortcut($shortcutPath)
if ($saved.TargetPath -ne $resolvedExe -or $saved.WorkingDirectory -ne (Split-Path -Path $resolvedExe -Parent) -or $saved.Arguments) {
    throw 'Saved desktop shortcut does not match the native GUI executable.'
}
$evidence = [ordered]@{
    shortcut = $shortcutPath
    target = $saved.TargetPath
    working_directory = $saved.WorkingDirectory
    icon_location = $saved.IconLocation
    arguments = $saved.Arguments
    window_style = $saved.WindowStyle
    app_user_model_id = $savedAppId
    desktop_registry = $desktop
    desktop_registry_second = $shellFolders.Desktop
    executable_exists = (Test-Path -LiteralPath $saved.TargetPath -PathType Leaf)
    shortcut_sha256 = (Get-FileHash -LiteralPath $shortcutPath -Algorithm SHA256).Hash
    executable_sha256 = (Get-FileHash -LiteralPath $resolvedExe -Algorithm SHA256).Hash
    replaced_shortcut_backup = $priorShortcut
    verified_at = (Get-Date).ToString('o')
}
$evidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $resolvedEvidence 'desktop-shortcut.json') -Encoding utf8
$evidence | ConvertTo-Json -Depth 4
