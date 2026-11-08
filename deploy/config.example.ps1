# Server configuration. install.ps1 copies this to config.ps1 -- edit
# config.ps1 (not this file). config.ps1 is read by setup-database.ps1 and
# start-server.ps1.

# SQL Server instance + database. Use a database dedicated to this app -- it
# creates its own tables (users, roles, events, ...) on first start.
$SqlServer   = "localhost\SQLEXPRESS"
$SqlDatabase = "SecurityCamera"
$OdbcDriver  = "ODBC Driver 17 for SQL Server"

# SQL Server login. Leave $SqlUsername blank to use Windows authentication
# instead (the app runs as SYSTEM; setup-database.ps1 grants it access).
# This file then holds a password -- keep it readable by admins only.
$SqlUsername = ""
$SqlPassword = ""

# Port the app listens on (web UI + API + live video, all on this one port).
$Port = 8000

# Optional: Azure Communication Services, for "Email incident" in the
# Coaching Workbench. Leave blank to skip setting them.
$AzureEmailConnectionString = ""
$AzureEmailSender           = ""

# Encrypts stored secrets (AI verification API keys, device passwords). install.ps1 fills it in.
# Keep it secret and back it up: if it is lost or changed, stored keys must be re-entered.
$TiamSecretKey = "sk-aee5018ff0701c8e-411fi9-cf86d2d7"
