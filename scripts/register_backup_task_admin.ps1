<# 
.SYNOPSIS
    Run this ONCE as Administrator to register the daily backup task.

.DESCRIPTION
    Creates a scheduled task that runs daily at 3:00 AM to backup the project.
    Prompts for your Windows password securely (required for Task Scheduler).
#>

# Requires Admin
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run this script as Administrator (right-click PowerShell → Run as Administrator)"
    exit 1
}

$TaskName = "SteamGameOrganizer_AutoBackup"
$PythonPath = "E:\Game Installers\0. Steam Game Organizer\runtime\python.exe"
$ScriptPath = "E:\Game Installers\0. Steam Game Organizer\tools\auto_backup.py"
$WorkingDir = "E:\Game Installers\0. Steam Game Organizer"
$RunTime = "03:00"

# Verify paths
foreach ($p in $PythonPath, $ScriptPath, $WorkingDir) {
    if (-not (Test-Path $p)) { Write-Error "Not found: $p"; exit 1 }
}

# Get credentials securely
Write-Host "Enter your Windows password for user: $env:USERNAME"
$password = Read-Host -AsSecureString
$credential = New-Object System.Management.Automation.PSCredential("$env:USERDOMAIN\$env:USERNAME", $password)

# Build action & trigger
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`"" -WorkingDirectory $WorkingDir
$trigger = New-ScheduledTaskTrigger -Daily -At $RunTime
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Password -RunLevel Highest

# Register
try {
    Register-ScheduledTask -TaskName $TaskName -Description "Daily automated backup of Steam Game Organizer (30-day retention, test-gated)" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
    Write-Host "✅ Task '$TaskName' registered successfully."
    Write-Host "   Runs daily at $RunTime"
    Write-Host "   Will only backup if tests pass and no backup in last 3 days"
}
catch {
    Write-Error "Failed: $_"
    exit 1
}