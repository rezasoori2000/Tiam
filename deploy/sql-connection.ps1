# Shared by setup-database.ps1 and start-server.ps1 (dot-source after
# config.ps1). Builds the ODBC connection string from config.ps1: SQL Server
# login when $SqlUsername is set, otherwise Windows (trusted) authentication.
function Get-OdbcConnectionString([string]$Database) {
    # ODBC values containing ; { } must be wrapped in braces, with } doubled.
    function Quote([string]$v) { "{" + $v.Replace("}", "}}") + "}" }
    $s = "Driver={$OdbcDriver};Server=$SqlServer;Database=$(Quote $Database);TrustServerCertificate=yes;"
    if ($SqlUsername) {
        $s += "UID=$(Quote $SqlUsername);PWD=$(Quote $SqlPassword);"
    } else {
        $s += "Trusted_Connection=yes;"
    }
    $s
}
