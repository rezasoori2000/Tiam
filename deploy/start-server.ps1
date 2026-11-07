# Starts the app (web UI + API + camera workers) in the foreground. Used by
# the startup task; can also be run by hand to see it working. Logs go to
# logs\server.log.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
. (Join-Path $root "config.ps1")
. (Join-Path $root "sql-connection.ps1")
$backend = Join-Path $root "backend"
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logs | Out-Null

$odbc = Get-OdbcConnectionString $SqlDatabase
$env:SECURITYCAM_DATABASE_URL = "mssql+pyodbc:///?odbc_connect=" + [uri]::EscapeDataString($odbc)
if ($AzureEmailConnectionString) { $env:AzureCommunicationServiceConnectionString = $AzureEmailConnectionString }
if ($AzureEmailSender) { $env:AzureCommunicationServicesSenderEmail = $AzureEmailSender }
if ($TiamSecretKey) { $env:TIAM_SECRET_KEY = $TiamSecretKey }

# Model paths like "yolov8s.pt" are relative, so run from backend\.
Set-Location $backend
$uvicorn = Join-Path $backend "venv\Scripts\uvicorn.exe"
$log = Join-Path $logs "server.log"
Add-Content $log "`n===== $(Get-Date -Format s) starting on port $Port ====="
# Via cmd so uvicorn's stderr goes to the log as plain text.
cmd /c "`"$uvicorn`" app.main:app --host 0.0.0.0 --port $Port >> `"$log`" 2>&1"
exit $LASTEXITCODE
