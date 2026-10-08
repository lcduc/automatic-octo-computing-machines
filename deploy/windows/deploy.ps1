<#
Update the Windows (no Docker) demo server to origin/main.

Run by the self-hosted GitHub runner on the server (see .github/workflows/deploy.yml), or by hand
from an elevated PowerShell. Pulls the code, installs changed dependencies, builds the admin web,
migrates the database, rebuilds the chat widget and restarts the app services. The database and
model-server services are left running.
#>
param(
    [string]$AppDir = 'C:\TNT\Chatbot_Demo\automatic-octo-computing-machines'
)

$ErrorActionPreference = 'Stop'
$Services = @('chatbot-web', 'chatbot-worker', 'chatbot-api')   # stop order; started in reverse
$Node = Join-Path $AppDir 'data\runtime\node'
$Python = Join-Path $AppDir 'venv\Scripts\python.exe'
$HealthUrl = 'http://127.0.0.1:8500/health/live'
$HealthAttempts = 30
$StopTimeoutSeconds = 30
$BuildAttempts = 3
$BuildRetrySeconds = 5
$OwnerRole = 'chatbot'
$OwnerPasswordFile = Join-Path $AppDir 'data\runtime\secrets\pg_owner'

function Invoke-Native([string]$Description, [scriptblock]$Command) {
    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit $LASTEXITCODE)" }
}

function Stop-AppService([string]$Name) {
    <# Stop a service and prove it is down. Stop-Service can return while NSSM's child process lives on,
       and NSSM restarts that child when it is killed, so a service that did not stop is ended as a tree. #>
    Write-Host "==> stop $Name"
    $service = Get-Service $Name
    $timeout = [TimeSpan]::FromSeconds($StopTimeoutSeconds)
    if ($service.Status -ne 'Stopped') {
        try {
            Stop-Service $Name -Force -ErrorAction Stop
            $service.WaitForStatus('Stopped', $timeout)
        }
        catch { Write-Host "Stop-Service $Name did not finish: $($_.Exception.Message)" }
    }
    $service.Refresh()
    if ($service.Status -ne 'Stopped') {
        $servicePid = (Get-CimInstance Win32_Service -Filter "Name = '$Name'").ProcessId
        Write-Host "==> $Name is still $($service.Status); ending its process tree (pid $servicePid)"
        if ($servicePid) { & taskkill /PID $servicePid /T /F | Out-Host }
        $service.WaitForStatus('Stopped', $timeout)
    }
}

function Get-Git { & git -c "safe.directory=$($AppDir.Replace('\', '/'))" -C $AppDir @args }

Set-Location $AppDir
$env:PATH = "$Node;$env:PATH"
$oldHead = (Get-Git rev-parse HEAD).Trim()

Invoke-Native 'git fetch' { Get-Git fetch origin main }
Invoke-Native 'git merge --ff-only' { Get-Git merge --ff-only origin/main }
$newHead = (Get-Git rev-parse HEAD).Trim()
$changed = @(Get-Git diff --name-only $oldHead $newHead)
Write-Host "Deploying $oldHead -> $newHead ($($changed.Count) files changed)"

try {
    if ($changed -contains 'requirements.txt') {
        # docling 2.132 moved its code into the docling-slim package, which installs into the same `docling\`
        # folder the old docling package owned. Upgrading in place lets pip delete the new files when it
        # removes the old package (every `docling.*` import then fails), so remove docling first.
        Invoke-Native 'pip uninstall docling' { & $Python -m pip uninstall -y docling }
        Invoke-Native 'pip install' { & $Python -m pip install -r requirements.txt }
    }

    # The admin web is static files served by Caddy, so it can be built while the site is up.
    $admin = Join-Path $AppDir 'frontends\admin'
    if (($changed -contains 'frontends/admin/package-lock.json') -or -not (Test-Path "$admin\node_modules")) {
        Invoke-Native 'admin npm ci' { npm ci --prefix $admin }
    }
    Invoke-Native 'admin build' { npm run build --prefix $admin }

    foreach ($name in $Services) { Stop-AppService $name }

    # The API's role (chatbot_app) cannot change the schema; migrations run as the schema owner.
    $env:POSTGRES_USER = $OwnerRole
    $env:POSTGRES_PASSWORD = (Get-Content $OwnerPasswordFile -Raw).Trim()
    try { Invoke-Native 'alembic upgrade head' { & $Python -m alembic upgrade head } }
    finally { Remove-Item Env:\POSTGRES_USER, Env:\POSTGRES_PASSWORD }

    # `next build` writes the standalone server that chatbot-web runs from, so it needs the service stopped.
    $widget = Join-Path $AppDir 'frontends\widget'
    if (($changed -contains 'frontends/widget/package-lock.json') -or -not (Test-Path "$widget\node_modules")) {
        Invoke-Native 'widget npm ci' { npm ci --prefix $widget }
    }
    # A Node process still running the widget keeps `.next\standalone` (its working directory) locked, which
    # makes `next build` fail with EBUSY. The services are verified stopped above, so anything left is an
    # orphan: end it, then retry the build briefly.
    Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
        Where-Object { $_.CommandLine -like '*server.js*' -and $_.ExecutablePath -like "$Node*" } |
        ForEach-Object { Write-Host "==> end leftover node process $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force }
    for ($attempt = 1; ; $attempt++) {
        try { Invoke-Native 'widget build' { npm run build --prefix $widget }; break }
        catch {
            if ($attempt -ge $BuildAttempts) { throw }
            Write-Host "Widget build failed (attempt $attempt of $BuildAttempts), retrying in $BuildRetrySeconds s"
            Start-Sleep -Seconds $BuildRetrySeconds
        }
    }
    $standalone = Join-Path $widget '.next\standalone'
    Copy-Item (Join-Path $widget '.next\static') (Join-Path $standalone '.next') -Recurse -Force
    if (Test-Path (Join-Path $widget 'public')) {
        Copy-Item (Join-Path $widget 'public') $standalone -Recurse -Force
    }
}
finally {
    # Always bring the app back, even when a step failed, so a bad deploy is not also an outage.
    [array]::Reverse($Services)
    foreach ($name in $Services) {
        Write-Host "==> start $name"
        Start-Service $name
    }
}

Write-Host "==> health check $HealthUrl"
for ($attempt = 1; $attempt -le $HealthAttempts; $attempt++) {
    try {
        if ((Invoke-WebRequest $HealthUrl -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) {
            Write-Host "API is up after $attempt check(s). Deployed $newHead."
            exit 0
        }
    }
    catch { Start-Sleep -Seconds 2 }
}
throw "API did not answer $HealthUrl after $HealthAttempts attempts"
