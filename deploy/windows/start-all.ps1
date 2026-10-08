<#
Start every demo service that is not running, in dependency order, then print their status.

Run from an elevated PowerShell on the server whenever the demo is unreachable. Safe to run at any time:
services that are already running are left alone.
#>
$Services = @(
    'chatbot-pg17', 'chatbot-model-server', 'chatbot-api',
    'chatbot-worker', 'chatbot-web', 'chatbot-caddy'
)
$HealthUrl = 'http://127.0.0.1:8500/health/live'
$HealthTimeoutSeconds = 5

foreach ($name in $Services) {
    if ((Get-Service $name).Status -ne 'Running') {
        Write-Host "==> start $name"
        Start-Service $name
    }
}
Get-Service $Services | Format-Table Name, Status -AutoSize

try {
    $code = (Invoke-WebRequest $HealthUrl -UseBasicParsing -TimeoutSec $HealthTimeoutSeconds).StatusCode
    Write-Host "API health: $code"
}
catch { Write-Host "API health check failed (it may still be starting): $($_.Exception.Message)" }
