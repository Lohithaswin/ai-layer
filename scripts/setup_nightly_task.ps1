# ============================================================
# PROJECT_NAME Bot — One-Click Task Scheduler Setup
# ============================================================
# Run this ONCE as Administrator to register the nightly
# ingestion job with Windows Task Scheduler.
#
# Usage (as Administrator):
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_nightly_task.ps1
#
# The task will run nightly_ingest.ps1 every night at 01:00 AM.
# Logs are saved to logs/nightly_ingest_YYYY-MM-DD.log
# ============================================================

$ErrorActionPreference = "Stop"

$TaskName    = "PROJECT_NAME-Bot-NightlyIngest"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Script      = Join-Path $ProjectRoot "scripts\nightly_ingest.ps1"
$RunAt       = "01:00"   # 1:00 AM

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " PROJECT_NAME Nightly Ingest — Task Scheduler Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project root : $ProjectRoot"
Write-Host "Script       : $Script"
Write-Host "Runs at      : $RunAt daily"
Write-Host ""

# Check Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator." -ForegroundColor Red
    Write-Host "Right-click PowerShell -> 'Run as administrator', then re-run." -ForegroundColor Yellow
    exit 1
}

# Remove existing task if it exists
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Build the action: run nightly_ingest.ps1 via PowerShell
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -NonInteractive -File `"$Script`"" `
    -WorkingDirectory $ProjectRoot

# Trigger: every day at 1:00 AM
$trigger = New-ScheduledTaskTrigger -Daily -At $RunAt

# Settings: run even if on battery, wake machine if sleeping
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 30)

# Principal: run as current user
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Highest

# Register
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "PROJECT_NAME Bot: Nightly document ingestion at 1:00 AM. Processes files queued by the file watcher without affecting bot response time." `
    | Out-Null

Write-Host ""
Write-Host "Task '$TaskName' registered successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "What happens now:" -ForegroundColor Cyan
Write-Host "  1. The file watcher (src/file_queue_watcher.py) runs alongside the bot."
Write-Host "     When a new PDF/Excel/Word file is added to DOCS_DIR or ROLE_ATTR_DIR,"
Write-Host "     it silently adds it to data/pending_ingest.json — zero bot impact."
Write-Host ""
Write-Host "  2. At 1:00 AM, Task Scheduler wakes and runs nightly_ingest.ps1."
Write-Host "     Only the queued new files are ingested. Logs go to logs/ folder."
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  View task    : Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "  Run now      : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Remove task  : Unregister-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Manual ingest: powershell -File .\scripts\nightly_ingest.ps1"
Write-Host "  Force full   : powershell -File .\scripts\nightly_ingest.ps1 -FullScan"
Write-Host ""
