param(
    [string]$BackupDirectory,
    [string]$Profile,
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

$arguments = '"{0}" --keep 30 --once-per-week' -f $backupScript
if ($BackupDirectory) {
    $arguments += ' --output-dir "{0}"' -f $BackupDirectory
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
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
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
