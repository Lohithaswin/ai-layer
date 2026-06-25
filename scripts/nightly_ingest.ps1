# ============================================================
# PROJECT_NAME Bot — Nightly Ingestion Script (Windows PowerShell)
# ============================================================
# Runs at 1:00 AM via Windows Task Scheduler.
# Only processes files that were queued by the file watcher.
# If no queue exists, falls back to a full scan.
#
# Data sources:
#   Docs  → Local OneDrive synced folder (DOCS_DIR in .env)
#   Roles → MSSQL live query when ROLE_DATA_SOURCE=mssql
#            Excel files when ROLE_DATA_SOURCE=excel
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

# ── Detect ROLE_DATA_SOURCE from .env ─────────────────────────────────────────
$envFile = Join-Path $ProjectRoot ".env"
$RoleDataSource = "excel"   # safe default
if (Test-Path $envFile) {
    $envContent = Get-Content $envFile -Encoding UTF8
    $roleLine = $envContent | Where-Object { $_ -match "^\s*ROLE_DATA_SOURCE\s*=" }
    if ($roleLine) {
        $RoleDataSource = ($roleLine -split "=", 2)[1].Trim().Trim('"').ToLower()
    }
}
Log "Role data source detected: $RoleDataSource"
Log "Docs source: local OneDrive folder (DOCS_DIR from .env)"

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

# ── Step 1: Ingest documents from local OneDrive folder ───────────────────────
Log ""
Log "[1/2] Document ingestion (source: local OneDrive folder via DOCS_DIR)..."

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

# ── Step 2: Role attribute ingestion ──────────────────────────────────────────
Log ""
Log "[2/2] Role attribute ingestion (source: $RoleDataSource)..."

# For MSSQL: always run (roles change in the DB independently of the file queue)
# For Excel: only run if role files are queued or it's a full scan
if ($hasQueue -and $pendingRoles.Count -eq 0 -and $RoleDataSource -ne "mssql") {
    Log "[2/2] No new role files queued — skipping role ingestion."
} else {
    try {
        if ($RoleDataSource -eq "mssql") {
            # Sync roles via the RDP Sync API (laptop → API → MSSQL)
            Log "[2/2] Syncing roles from RDP Sync API..."
            $syncScript = Join-Path $ProjectRoot "scripts\sync_roles_from_api.py"
            if (Test-Path $syncScript) {
                & $VenvPython $syncScript
                if ($LASTEXITCODE -ne 0) { throw "sync_roles_from_api exited with code $LASTEXITCODE" }
            } else {
                Log "[2/2] sync_roles_from_api.py not found — falling back to JSON export/import"
                $syncScript = Join-Path $ProjectRoot "scripts\sync_roles_from_mssql.py"
                & $VenvPython $syncScript
                if ($LASTEXITCODE -ne 0) { throw "sync_roles_from_mssql exited with code $LASTEXITCODE" }
            }
        } else {
            # Load from Excel files in ROLE_ATTR_DIR
            Log "[2/2] Loading roles from Excel files (ROLE_ATTR_DIR)..."
            & $VenvPython -m src.role_ingestor --source excel
            if ($LASTEXITCODE -ne 0) { throw "role_ingestor exited with code $LASTEXITCODE" }
        }
        Log "[2/2] Role attribute ingestion complete."
    } catch {
        Log "[2/2] ERROR during role ingestion: $_"
        Log "[2/2] WARNING: Role sync failed — docs are still indexed. Check MSSQL connectivity."
        # Non-fatal: docs pipeline is independent of role sync
    }
}

# ── Clear the queue after successful run ──────────────────────────────────────
if (Test-Path $QueueFile) {
    $empty = @{
        pending_docs  = @()
        pending_roles = @()
        last_updated  = $null
        last_cleared  = (Get-Date -Format "o")
    }
    $empty | ConvertTo-Json -Depth 3 | Set-Content $QueueFile -Encoding UTF8
    Log ""
    Log "Queue cleared."
}

Log ""
Log "========================================"
Log "Nightly ingestion COMPLETE"
Log "========================================"
exit 0
