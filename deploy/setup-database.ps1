# One-time: checks the app can reach its SQL Server database, creating it
# first if it doesn't exist (needs CREATE DATABASE permission -- otherwise ask
# your DBA to create an empty one). The app creates its own tables on first
# start.
#
# Windows authentication ($SqlUsername blank in config.ps1): run as a user
# who is a sysadmin on the instance; it also grants the SYSTEM account (which
# runs the app via the startup task) db_owner on the database.
#
#   powershell -ExecutionPolicy Bypass -File .\setup-database.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
. (Join-Path $root "config.ps1")
. (Join-Path $root "sql-connection.ps1")
$py = Join-Path $root "backend\venv\Scripts\python.exe"

$env:SC_ODBC_MASTER = Get-OdbcConnectionString "master"
$env:SC_ODBC_APP = Get-OdbcConnectionString $SqlDatabase
$env:SC_DB = $SqlDatabase
$env:SC_GRANT_SYSTEM = if ($SqlUsername) { "" } else { "1" }

$script = @'
import os, pyodbc
name = os.environ["SC_DB"]
db = name.replace("]", "]]")
try:
    pyodbc.connect(os.environ["SC_ODBC_APP"], autocommit=True).close()
    print(f"Database '{name}' exists and is reachable.")
except pyodbc.Error:
    print(f"Database '{name}' not reachable -- trying to create it...")
    conn = pyodbc.connect(os.environ["SC_ODBC_MASTER"], autocommit=True)
    conn.cursor().execute(f"IF DB_ID(N'{name}') IS NULL CREATE DATABASE [{db}]")
    conn.close()
    pyodbc.connect(os.environ["SC_ODBC_APP"], autocommit=True).close()
    print(f"Database '{name}' created.")
if os.environ["SC_GRANT_SYSTEM"]:
    conn = pyodbc.connect(os.environ["SC_ODBC_APP"], autocommit=True)
    cur = conn.cursor()
    cur.execute("IF SUSER_ID(N'NT AUTHORITY\\SYSTEM') IS NULL CREATE LOGIN [NT AUTHORITY\\SYSTEM] FROM WINDOWS")
    cur.execute("IF USER_ID(N'NT AUTHORITY\\SYSTEM') IS NULL CREATE USER [NT AUTHORITY\\SYSTEM] FOR LOGIN [NT AUTHORITY\\SYSTEM]")
    cur.execute("ALTER ROLE db_owner ADD MEMBER [NT AUTHORITY\\SYSTEM]")
    print("SYSTEM account granted db_owner.")
'@
# Via a temp file: PowerShell 5.1 mangles embedded double quotes in -c args.
$tmp = Join-Path $env:TEMP "securitycam_setup_db.py"
Set-Content $tmp $script -Encoding ascii
try {
    & $py $tmp
    if ($LASTEXITCODE -ne 0) { throw "Database setup failed" }
} finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
Write-Host "Next: register-startup-task.ps1 (as Administrator)" -ForegroundColor Green
