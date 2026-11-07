<#
Starts the backend (uvicorn, port 8000) and frontend (vite dev server) for local
development, each in its own PowerShell window so their logs stay visible.
Stop both with .\stop-dev.ps1

  powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
#>
$root = $PSScriptRoot
$pidFile = Join-Path $root ".dev-pids.json"

# Don't start a second copy on top of a running one.
if (Test-Path $pidFile) {
    $old = Get-Content $pidFile | ConvertFrom-Json
    $alive = @($old.backend, $old.frontend) | Where-Object { $_ -and (Get-Process -Id $_ -ErrorAction SilentlyContinue) }
    if ($alive) {
        Write-Host "Dev servers already running (run .\stop-dev.ps1 first)." -ForegroundColor Yellow
        exit 1
    }
}

$backendCmd = "`$Host.UI.RawUI.WindowTitle = 'APL Backend'; Set-Location '$root\backend'; .\venv\Scripts\Activate.ps1; uvicorn app.main:app --host 127.0.0.1 --port 8000"
$frontendCmd = "`$Host.UI.RawUI.WindowTitle = 'APL Frontend'; Set-Location '$root\frontend'; npm run dev"

$backend = Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCmd -PassThru
$frontend = Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $frontendCmd -PassThru

@{ backend = $backend.Id; frontend = $frontend.Id } | ConvertTo-Json | Set-Content $pidFile

Write-Host "Backend  : http://127.0.0.1:8000  (window 'APL Backend', pid $($backend.Id))"
Write-Host "Frontend : http://localhost:5173  (window 'APL Frontend', pid $($frontend.Id))"
Write-Host "Stop both: .\stop-dev.ps1"
