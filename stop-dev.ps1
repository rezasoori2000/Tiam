<#
Stops the backend and frontend started by .\start-dev.ps1 (the windows and
everything they spawned: uvicorn, node, ...).

  powershell -ExecutionPolicy Bypass -File .\stop-dev.ps1
#>
$pidFile = Join-Path $PSScriptRoot ".dev-pids.json"

function Stop-Tree($id, $name) {
    if ($id -and (Get-Process -Id $id -ErrorAction SilentlyContinue)) {
        taskkill /PID $id /T /F 2>$null | Out-Null
        Write-Host "Stopped $name (pid $id)"
    }
}

if (Test-Path $pidFile) {
    $pids = Get-Content $pidFile | ConvertFrom-Json
    Stop-Tree $pids.backend "backend"
    Stop-Tree $pids.frontend "frontend"
    Remove-Item $pidFile -Force
}

# Fallback for servers started by hand: free the dev ports.
foreach ($port in 8000, 5173) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Tree $_.OwningProcess "process on port $port" }
}
Write-Host "Done."
