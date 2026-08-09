# ============================================================
# PROJECT_NAME Role Sync API — Task Scheduler Setup
# ============================================================
# Run this ONCE on the RDP server as Administrator.
# Registers a Windows Task that starts role_sync_api.py
# automatically at boot and restarts it if it crashes.
#
# Usage (on RDP as Admin):
#   powershell -ExecutionPolicy Bypass -File setup_sync_api_task.ps1
# ============================================================

$ErrorActionPreference = "Stop"

# ── Config — adjust these paths to match your server environment ──────────────
$TaskName   = "RoleSyncAPI"
$ScriptPath = "$env:USERPROFILE\\role_sync_api.py"   # adjust to where you placed the script
$PythonExe  = "python"   # assumes Python is on PATH; change to full path if needed
$LogDir     = "$env:USERPROFILE\\logs"
$Port       = 8765

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "role_sync_api.log"

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument $ScriptPath `
    -WorkingDirectory "$env:USERPROFILE"

# Trigger: at system startup
$trigger = New-ScheduledTaskTrigger -AtStartup

# Run as current user, with highest privileges
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName   $TaskName `
    -Action     $action `
    -Trigger    $trigger `
    -Principal  $principal `
    -Settings   $settings `
    -Description "PROJECT_NAME Role Sync API — exposes MSSQL role data on port $Port for laptop sync"

Write-Host ""
Write-Host "Registered Task: $TaskName" -ForegroundColor Green
Write-Host "The API will start automatically at boot on port $Port"
Write-Host ""
Write-Host "To start it NOW without rebooting, run:"
Write-Host "  python `"$ScriptPath`""
Write-Host ""
Write-Host "To check it is running, open a browser on the RDP and visit:"
Write-Host "  http://localhost:$Port/health"
