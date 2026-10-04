[CmdletBinding()]
param(
    [switch]$Invoke,
    [int]$AssistantPid = 19368,
    [string]$ExpectedCreatedUtc = '2026-10-04T16:35:00.3081295Z'
)

$ErrorActionPreference = 'Stop'
. 'D:\codex\bin\Initialize-CodexEnvironment.ps1'
$taskRoot = 'D:\codex\CodexWork\clash'
$scriptRoot = "$taskRoot\work\startup-resume-repair-20261005"
$expectedExe = "$taskRoot\outputs\wpf-desktop-20261004\app\ClashAssistant.Desktop.exe"

# UI Automation uses the existing Windows .NET Framework runtime. Run its
# helper without a console window when this script is called from PowerShell 7.
if ($PSVersionTable.PSEdition -eq 'Core') {
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $windowsPowerShell -PathType Leaf)) {
        throw 'The installed Windows PowerShell runtime was not found.'
    }
    $helperInfo = [Diagnostics.ProcessStartInfo]::new($windowsPowerShell)
    $helperInfo.WorkingDirectory = $taskRoot
    $helperInfo.UseShellExecute = $false
    $helperInfo.CreateNoWindow = $true
    $helperInfo.RedirectStandardOutput = $true
    $helperInfo.RedirectStandardError = $true
    $helperInfo.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $helperInfo.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    foreach ($argument in @('-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass',
        '-File',$PSCommandPath,'-AssistantPid',[string]$AssistantPid,'-ExpectedCreatedUtc',$ExpectedCreatedUtc)) {
        $helperInfo.ArgumentList.Add($argument)
    }
    if ($Invoke) { $helperInfo.ArgumentList.Add('-Invoke') }
    $helper = [Diagnostics.Process]::new()
    $helper.StartInfo = $helperInfo
    try {
        if (-not $helper.Start()) { throw 'Unable to start the hidden inspection helper.' }
        $outputTask = $helper.StandardOutput.ReadToEndAsync()
        $errorTask = $helper.StandardError.ReadToEndAsync()
        if (-not $helper.WaitForExit(30000)) {
            $helper.Kill()
            throw 'The UI Automation helper exceeded its 30-second budget; no retry was issued.'
        }
        $helperOutput = $outputTask.GetAwaiter().GetResult()
        $helperError = $errorTask.GetAwaiter().GetResult()
        if ($helperOutput.Trim()) { Write-Output $helperOutput.Trim() }
        if ($helper.ExitCode -ne 0) { throw "The hidden helper failed: $helperError" }
    } finally { $helper.Dispose() }
    return
}

[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$expectedCreated = [DateTime]::Parse($ExpectedCreatedUtc,[Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()

function Assert-AssistantIdentity {
    $owner = Get-Process -Id $AssistantPid -ErrorAction Stop
    try {
        if (-not $owner.MainModule.FileName.Equals($expectedExe,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'The assistant executable path does not match the authorized installation.'
        }
        if ($owner.StartTime.ToUniversalTime().Ticks -ne $expectedCreated.Ticks) {
            throw 'The assistant creation time changed; the PID may have been reused.'
        }
        return [pscustomobject]@{
            pid = $owner.Id
            executable = $owner.MainModule.FileName
            created_utc = $owner.StartTime.ToUniversalTime().ToString('O')
            main_window_handle = $owner.MainWindowHandle.ToInt64()
        }
    } finally { $owner.Dispose() }
}

$receipt = [ordered]@{
    inspected_at = [DateTimeOffset]::Now.ToString('O')
    mode = $(if ($Invoke) { 'invoke' } else { 'inspect_only' })
    status = 'INSPECTION_PENDING'
    assistant = $null
    button = $null
    invoke_issued = $false
    mouse_keyboard_input = $false
    foreground_activation_requested = $false
    error = $null
}
$receiptSuffix = [guid]::NewGuid().ToString('N').Substring(0,8)
$receiptPath = Join-Path $scriptRoot ("start-task-{0}-{1}-{2}.json" -f $receipt.mode,
    [DateTime]::Now.ToString('yyyyMMdd-HHmmss-fff'),$receiptSuffix)
$failure = $null
try {
    $identity = Assert-AssistantIdentity
    $receipt.assistant = $identity
    if ($identity.main_window_handle -eq 0) {
        throw 'The assistant has no accessible main window; it will not be shown or activated.'
    }
    $window = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$identity.main_window_handle)
    if ($null -eq $window -or $window.Current.ProcessId -ne $AssistantPid) {
        throw 'The UI Automation window does not belong to the verified assistant process.'
    }
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty,'StartTask')
    $buttons = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
    if ($buttons.Count -ne 1) { throw "Expected one StartTask button, found $($buttons.Count)." }
    $button = $buttons.Item(0)
    $current = $button.Current
    if ($current.ProcessId -ne $AssistantPid -or
        $current.ControlType -ne [System.Windows.Automation.ControlType]::Button) {
        throw 'The StartTask element is not a button in the authorized assistant.'
    }
    $invokePattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    if ($invokePattern -isnot [System.Windows.Automation.InvokePattern]) {
        throw 'The StartTask button does not support InvokePattern.'
    }
    $receipt.button = [ordered]@{
        automation_id = $current.AutomationId
        name = $current.Name
        enabled = $current.IsEnabled
        offscreen = $current.IsOffscreen
        process_id = $current.ProcessId
        invoke_pattern_supported = $true
    }
    $receipt.status = 'PASS_INSPECTED_ONLY'
    if ($Invoke) {
        $rechecked = Assert-AssistantIdentity
        if ($rechecked.main_window_handle -ne $identity.main_window_handle) {
            throw 'The assistant main window changed before Invoke; no command was issued.'
        }
        $current = $button.Current
        if ($current.ProcessId -ne $AssistantPid -or $current.AutomationId -ne 'StartTask' -or
            -not $current.IsEnabled) {
            throw 'The verified StartTask button is not enabled; no command was issued.'
        }
        # WPF ButtonAutomationPeer calls the same click handler. This issues one
        # Invoke only; it sends no mouse/keyboard input and does not set focus.
        $receipt.status = 'INVOKE_REQUESTED'
        $receipt.invoke_requested_at = [DateTimeOffset]::Now.ToString('O')
        $receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $receiptPath -Encoding utf8
        $invokePattern.Invoke()
        $receipt.invoke_issued = $true
        $receipt.status = 'PASS_INVOKE_ISSUED'
        $receipt.invoke_returned_at = [DateTimeOffset]::Now.ToString('O')
    }
} catch {
    $failure = $_
    $receipt.status = $(if ($receipt.status -eq 'INVOKE_REQUESTED') { 'INVOKE_OUTCOME_UNKNOWN' } else { 'FAILED_NO_INVOKE' })
    $receipt.error = $_.Exception.Message
} finally {
    $receipt.receipt_path = $receiptPath
    $receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $receiptPath -Encoding utf8
    $receipt | ConvertTo-Json -Depth 10 | Write-Output
}
if ($null -ne $failure) { throw $failure }
