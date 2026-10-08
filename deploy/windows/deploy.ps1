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

function Invoke-Native([string]$Description, [scriptblock]$Command) {
    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit $LASTEXITCODE)" }
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
        Invoke-Native 'pip install' { & $Python -m pip install -r requirements.txt }
    }

    # The admin web is static files served by Caddy, so it can be built while the site is up.
    $admin = Join-Path $AppDir 'frontends\admin'
    if (($changed -contains 'frontends/admin/package-lock.json') -or -not (Test-Path "$admin\node_modules")) {
        Invoke-Native 'admin npm ci' { npm ci --prefix $admin }
    }
    Invoke-Native 'admin build' { npm run build --prefix $admin }

    foreach ($name in $Services) {
        Write-Host "==> stop $name"
        Stop-Service $name -ErrorAction SilentlyContinue
    }

    Invoke-Native 'alembic upgrade head' { & $Python -m alembic upgrade head }

    # `next build` writes the standalone server that chatbot-web runs from, so it needs the service stopped.
    $widget = Join-Path $AppDir 'frontends\widget'
    if (($changed -contains 'frontends/widget/package-lock.json') -or -not (Test-Path "$widget\node_modules")) {
        Invoke-Native 'widget npm ci' { npm ci --prefix $widget }
    }
    Invoke-Native 'widget build' { npm run build --prefix $widget }
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
