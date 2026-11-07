# Upgrades an already-installed server in place from a newly-built release
# zip -- stops the app, swaps in the new backend\app + backend\static +
# backend\models (custom weights, if any; keeping
# venv/data/config.ps1 untouched), restarts it, and verifies it
# comes back up. Automatically rolls back to the previous version if the
# health check fails after restart.
#
#   powershell -ExecutionPolicy Bypass -File .\update-release.ps1 `
#       -ReleaseZip "C:\path\to\APL-SecurityMonitor-<version>.zip" `
#       -InstallDir "C:\APL-SecurityMonitor"
#
# -InstallDir is the folder that already contains config.ps1, backend\venv,
# backend\data, etc. (wherever install.ps1 was originally run).
param(
    [Parameter(Mandatory = $true)][string]$ReleaseZip,
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [string]$TaskName = "APL Security Monitor",
    [int]$HealthCheckTimeoutSec = 60
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ReleaseZip)) { throw "Release zip not found: $ReleaseZip" }
if (-not (Test-Path (Join-Path $InstallDir "config.ps1"))) {
    throw "config.ps1 not found under $InstallDir -- is this the right -InstallDir?"
}

$backendDir = Join-Path $InstallDir "backend"
$venvPy = Join-Path $backendDir "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "$venvPy not found -- is this the right -InstallDir?" }

. (Join-Path $InstallDir "config.ps1")  # for $Port, used by the health check below

# --- extract the release zip into a scratch folder --------------------------
$scratch = Join-Path $env:TEMP ("securitycam_update_" + [guid]::NewGuid().ToString("N"))
Write-Host "Extracting $ReleaseZip ..." -ForegroundColor Cyan
Expand-Archive -Path $ReleaseZip -DestinationPath $scratch -Force
# Expand-Archive of "APL-SecurityMonitor-<version>\..." creates one
# top-level folder inside $scratch -- descend into it.
$releaseRoot = Get-ChildItem $scratch -Directory | Select-Object -First 1
if ($null -eq $releaseRoot) { throw "Release zip did not contain the expected folder layout" }
$newRequirements = Join-Path $releaseRoot.FullName "backend\requirements.txt"
if (-not (Test-Path (Join-Path $releaseRoot.FullName "backend\app")) -or
    -not (Test-Path (Join-Path $releaseRoot.FullName "backend\static"))) {
    throw "Release zip is missing backend\app or backend\static"
}
# Folders swapped as a unit (backed up, replaced, rolled back together).
# models is optional so a zip built without weights still installs.
$swapDirs = @("app", "static")
if (Test-Path (Join-Path $releaseRoot.FullName "backend\models")) { $swapDirs += "models" }

# --- warn (don't auto-act) if Python deps changed ---------------------------
$oldRequirements = Join-Path $backendDir "requirements.txt"
if ((Test-Path $oldRequirements) -and (Test-Path $newRequirements)) {
    $diff = Compare-Object (Get-Content $oldRequirements) (Get-Content $newRequirements)
    if ($diff) {
        Write-Warning "requirements.txt changed in this release -- after this update completes, run install.ps1 in $InstallDir to pick up new/changed dependencies."
    }
}

# --- stop the running app ----------------------------------------------------
Write-Host "Stopping scheduled task '$TaskName' ..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName $TaskName
$deadline = (Get-Date).AddSeconds(30)
while ((Get-ScheduledTask -TaskName $TaskName).State -ne "Ready" -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
}
if ((Get-ScheduledTask -TaskName $TaskName).State -ne "Ready") {
    throw "Task '$TaskName' did not stop within 30s -- aborting before touching any files"
}

# --- back up the currently-live folders (never deleted, just moved aside) ---
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backups = @()  # live folders actually moved aside (models may not exist on an old install)
Write-Host "Backing up current $($swapDirs -join ' / ') to <name>.bak-$stamp ..." -ForegroundColor Cyan
foreach ($d in $swapDirs) {
    $live = Join-Path $backendDir $d
    if (Test-Path $live) {
        Rename-Item $live "$d.bak-$stamp"
        $backups += $d
    }
}

function Restore-Backup {
    Write-Host "Rolling back to previous version ..." -ForegroundColor Yellow
    foreach ($d in $swapDirs) {
        $live = Join-Path $backendDir $d
        if (Test-Path $live) { Remove-Item $live -Recurse -Force }
        if ($backups -contains $d) { Rename-Item (Join-Path $backendDir "$d.bak-$stamp") $live }
    }
    Start-ScheduledTask -TaskName $TaskName
}

try {
    # --- copy in the new version ---------------------------------------------
    Write-Host "Copying new backend\$($swapDirs -join ', backend\') into place ..." -ForegroundColor Cyan
    foreach ($d in $swapDirs) {
        Copy-Item (Join-Path $releaseRoot.FullName "backend\$d") (Join-Path $backendDir $d) -Recurse
    }

    # --- restart and health-check --------------------------------------------
    Write-Host "Starting scheduled task '$TaskName' ..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $TaskName

    Write-Host "Waiting for the app to respond on port $Port ..." -ForegroundColor Cyan
    $healthy = $false
    $deadline = (Get-Date).AddSeconds($HealthCheckTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:$Port/api/health" -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -eq 200) { $healthy = $true; break }
        } catch { Start-Sleep -Seconds 2 }
    }

    if (-not $healthy) {
        Write-Warning "App did not respond healthy on port $Port within $HealthCheckTimeoutSec s."
        Restore-Backup
        throw "Update failed health check -- rolled back to the previous version. Check logs\server.log in $InstallDir for what went wrong before retrying."
    }

    Write-Host "Update complete and healthy. Previous version kept as <name>.bak-$stamp in $backendDir (delete manually once you're confident, or keep as a rollback point)." -ForegroundColor Green
} catch {
    Write-Error $_
    exit 1
} finally {
    Remove-Item $scratch -Recurse -Force -ErrorAction SilentlyContinue
}
