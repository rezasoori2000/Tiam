#Requires -RunAsAdministrator
# Registers a Windows scheduled task that starts the app at boot (as SYSTEM,
# no login needed) and restarts it if it stops, opens the firewall port,
# and starts it now.
#
#   powershell -ExecutionPolicy Bypass -File .\register-startup-task.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
. (Join-Path $root "config.ps1")
$taskName = "APL Security Monitor"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $root 'start-server.ps1')`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

$ruleName = "APL Security Monitor (TCP $Port)"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP `
        -LocalPort $Port -Action Allow -Profile Domain,Private | Out-Null
}

Start-ScheduledTask -TaskName $taskName
Write-Host "Started. Open http://$($env:COMPUTERNAME):$Port  (log: logs\server.log)" -ForegroundColor Green
