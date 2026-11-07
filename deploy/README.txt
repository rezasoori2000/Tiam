APL Security Monitor - server install
=====================================

Prerequisites (install once): NVIDIA driver, Python 3.12, ODBC Driver 17 for
SQL Server, and a SQL Server to use (local SQL Server Express, or an existing
server -- set $SqlServer / $SqlUsername / $SqlPassword in config.ps1).

Then, from this folder in PowerShell:

  1. powershell -ExecutionPolicy Bypass -File .\install.ps1
  2. notepad .\config.ps1            (check SQL Server name / port)
  3. powershell -ExecutionPolicy Bypass -File .\setup-database.ps1
  4. (as Administrator)
     powershell -ExecutionPolicy Bypass -File .\register-startup-task.ps1
  5. Browse to http://<server-name>:8000 and log in; change the admin password.

Logs: logs\server.log
Stop / start:  Stop-ScheduledTask "APL Security Monitor" / Start-ScheduledTask "APL Security Monitor"

Upgrading: stop the task, replace backend\app and backend\static with the new
release's copies (keep backend\venv, backend\data, config.ps1), run install.ps1
again if requirements changed, then start the task.
