<# 
.SYNOPSIS
    Registers a daily Task Scheduler task to run the auto_backup.py script.

.DESCRIPTION
    Creates a scheduled task that runs daily at 3:00 AM (configurable) to create
    automated backups of the Steam Game Organizer project with retention policy.
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$TaskName = "SteamGameOrganizer_AutoBackup",

    [Parameter(Mandatory=$false)]
    [string]$Description = "Daily automated backup of Steam Game Organizer project with 30-day retention",

    [Parameter(Mandatory=$false)]
    [string]$RunTime = "03:00",  # 3 AM daily

    [Parameter(Mandatory=$false)]
    [string]$PythonPath = "E:\Game Installers\0. Steam Game Organizer\runtime\python.exe",

    [Parameter(Mandatory=$false)]
    [string]$ScriptPath = "E:\Game Installers\0. Steam Game Organizer\tools\auto_backup.py",

    [Parameter(Mandatory=$false)]
    [string]$WorkingDir = "E:\Game Installers\0. Steam Game Organizer",

    [Parameter(Mandatory=$false)]
    [switch]$RunAsNetworkService = $false,

    [Parameter(Mandatory=$false)]
    [switch]$Delete = $false  # Use -Delete to remove the task
)

# Requires Administrator for task registration
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "This script must be run as Administrator to register a scheduled task."
    exit 1
}

if ($Delete) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Deleted scheduled task: $TaskName"
    } else {
        Write-Host "Task '$TaskName' does not exist."
    }
    exit 0
}

# Verify paths exist
if (-not (Test-Path $PythonPath)) {
    Write-Error "Python not found at: $PythonPath"
    exit 1
}
if (-not (Test-Path $ScriptPath)) {
    Write-Error "Script not found at: $ScriptPath"
    exit 1
}
if (-not (Test-Path $WorkingDir)) {
    Write-Error "Working directory not found: $WorkingDir"
    exit 1
}

# Build action
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument $ScriptPath -WorkingDirectory $WorkingDir

# Build trigger (daily at specified time)
$trigger = New-ScheduledTaskTrigger -Daily -At $RunTime

# Build settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

# Principal (run as current user by default, or NetworkService)
if ($RunAsNetworkService) {
    $principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\NETWORK SERVICE" -LogonType ServiceAccount -RunLevel Highest
} else {
    $principal = New-ScheduledTaskPrincipal -UserId (whoami) -LogonType Interactive -RunLevel Highest
}

# Register task
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description $Description `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force

    Write-Host "Successfully registered scheduled task: $TaskName"
    Write-Host "  Runs daily at $RunTime"
    Write-Host "  Command: $PythonPath $ScriptPath"
    Write-Host "  Working directory: $WorkingDir"
}
catch {
    Write-Error "Failed to register task: $_"
    exit 1
}