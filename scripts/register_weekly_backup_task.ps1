param(
    [string]$BackupDirectory,
    [string]$Profile,
    [switch]$AllProfiles,
    [switch]$Local,
    [switch]$GoogleDrive,
    [string]$TaskName = "Tabula Rosa Weekly Backup"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backupScript = Join-Path $projectRoot "scripts\backup_google_sheets.py"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Project Python executable was not found: $pythonPath"
}
if (-not (Test-Path -LiteralPath $backupScript -PathType Leaf)) {
    throw "Backup script was not found: $backupScript"
}
if ($BackupDirectory -and -not (Test-Path -LiteralPath $BackupDirectory -PathType Container)) {
    throw "Backup directory was not found: $BackupDirectory"
}
if ($BackupDirectory -and $GoogleDrive) {
    throw "BackupDirectory cannot be combined with GoogleDrive."
}
if ($BackupDirectory -and $AllProfiles) {
    throw "BackupDirectory is only available for a single profile."
}
if ($Profile -and $AllProfiles) {
    throw "Profile cannot be combined with AllProfiles."
}
if ($Local -and $GoogleDrive) {
    throw "Local cannot be combined with GoogleDrive."
}
if ($BackupDirectory -and $Local) {
    throw "BackupDirectory cannot be combined with Local."
}
if (-not $Profile -and -not $AllProfiles -and -not $BackupDirectory) {
    $AllProfiles = $true
}

$arguments = '"{0}" --keep 30 --once-per-week' -f $backupScript
if ($AllProfiles) {
    $arguments += ' --all-profiles'
}
if ($GoogleDrive -or ($AllProfiles -and -not $Local)) {
    $arguments += ' --google-drive'
}
if ($Local) {
    $arguments += ' --local-dir'
}
if ($BackupDirectory) {
    $arguments += ' --local-dir "{0}"' -f $BackupDirectory
}
if ($Profile) {
    $arguments += ' --profile "{0}"' -f $Profile
}
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument $arguments `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -WeeksInterval 1 `
    -DaysOfWeek Monday, Tuesday, Wednesday `
    -At 10:00PM
$executionTimeLimit = if ($AllProfiles) {
    # Allow the aggregate run to use Task Scheduler's documented three-day
    # default so a fixed per-profile limit cannot starve later profiles.
    New-TimeSpan -Days 3
} else {
    New-TimeSpan -Minutes 15
}
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit $executionTimeLimit `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Create one verified Tabula Rosa backup weekly; Monday with Tuesday/Wednesday retry opportunities." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, Description
