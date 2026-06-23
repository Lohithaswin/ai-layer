# ============================================================
# PROJECT_NAME Bot — Nightly Ingestion Script (Windows PowerShell)
# ============================================================
# Runs at 1:00 AM via Windows Task Scheduler.
# Only processes files that were queued by the file watcher.
# If no queue exists, falls back to a full scan.
#
# To register the scheduled task, run as Administrator:
#   .\scripts\setup_nightly_task.ps1
# ============================================================

param(
    [switch]$FullScan    # Force a full re-index regardless of queue
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython  = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$QueueFile   = Join-Path $ProjectRoot "data\pending_ingest.json"
$LogDir      = Join-Path $ProjectRoot "logs"
$Timestamp   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# ── Ensure log folder exists ──────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("nightly_ingest_" + (Get-Date -Format "yyyy-MM-dd") + ".log")

function Log($msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Log "========================================"
Log "PROJECT_NAME Nightly Ingestion Started"
Log "========================================"

# ── Verify Python venv exists ─────────────────────────────────────────────────
if (-not (Test-Path $VenvPython)) {
    Log "ERROR: Python venv not found at $VenvPython"
    exit 1
}

Set-Location $ProjectRoot

# ── Read the pending queue ─────────────────────────────────────────────────────
$pendingDocs  = @()
$pendingRoles = @()
$hasQueue     = $false

if ((Test-Path $QueueFile) -and -not $FullScan) {
    try {
        $queue = Get-Content $QueueFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $pendingDocs  = @($queue.pending_docs  | Where-Object { $_ -ne $null -and $_ -ne "" })
        $pendingRoles = @($queue.pending_roles | Where-Object { $_ -ne $null -and $_ -ne "" })
        $hasQueue = ($pendingDocs.Count -gt 0) -or ($pendingRoles.Count -gt 0)
        Log "Queue loaded: $($pendingDocs.Count) doc(s), $($pendingRoles.Count) role file(s)"
    } catch {
        Log "WARNING: Could not read queue file — falling back to full scan. Error: $_"
        $hasQueue = $false
    }
} elseif ($FullScan) {
    Log "Full scan mode (-FullScan flag set)"
} else {
    Log "No queue file found — running full scan"
}

# ── Step 1: Ingest documents ──────────────────────────────────────────────────
Log ""
Log "[1/2] Starting document ingestion..."

if ($hasQueue -and $pendingDocs.Count -eq 0) {
    Log "[1/2] No new documents queued — skipping doc ingestion."
} else {
    try {
        & $VenvPython -m src.ingest_batch
        if ($LASTEXITCODE -ne 0) { throw "ingest_batch exited with code $LASTEXITCODE" }
        Log "[1/2] Document ingestion complete."
    } catch {
        Log "[1/2] ERROR during document ingestion: $_"
        exit 1
    }
}

# ── Step 2: Ingest role attributes ───────────────────────────────────────────
Log ""
Log "[2/2] Starting role attribute ingestion..."

# Find the role ingestor script
$roleScript = Join-Path $ProjectRoot "src\role_ingestor.py"
if (-not (Test-Path $roleScript)) {
    $roleScript = Join-Path $ProjectRoot "scripts\ingest_roles.py"
}

if ($hasQueue -and $pendingRoles.Count -eq 0) {
    Log "[2/2] No new role files queued — skipping role ingestion."
} elseif (Test-Path $roleScript) {
    try {
        & $VenvPython $roleScript
        if ($LASTEXITCODE -ne 0) { throw "role ingestor exited with code $LASTEXITCODE" }
        Log "[2/2] Role attribute ingestion complete."
    } catch {
        Log "[2/2] ERROR during role ingestion: $_"
        exit 1
    }
} else {
    Log "[2/2] WARNING: Role ingestor script not found — skipping."
}

# ── Clear the queue after successful ingestion ────────────────────────────────
if (Test-Path $QueueFile) {
    $empty = @{ pending_docs = @(); pending_roles = @(); last_updated = $null; last_cleared = (Get-Date -Format "o") }
    $empty | ConvertTo-Json -Depth 3 | Set-Content $QueueFile -Encoding UTF8
    Log ""
    Log "Queue cleared."
}

Log ""
Log "========================================"
Log "Nightly ingestion COMPLETE"
Log "========================================"
exit 0
