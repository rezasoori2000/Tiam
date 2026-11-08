# Builds a self-contained release folder + zip under .\release\ that can be
# copied to the production server and installed with deploy\install.ps1.
#
#   powershell -ExecutionPolicy Bypass -File .\build-release.ps1
#
# Layout of the output:
#   APL-SecurityMonitor-<version>\
#     backend\app\            FastAPI app source
#     backend\static\         built frontend (served by FastAPI -- one port, no CORS)
#     backend\yolov8s.pt      main detector weights
#     backend\requirements.txt
#     install.ps1, setup-database.ps1, start-server.ps1,
#     register-startup-task.ps1, config.example.ps1, README.txt
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

function Invoke-Native([string]$what, [scriptblock]$cmd) {
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

$sha = (git -C $repo rev-parse --short HEAD).Trim()
if (git -C $repo status --porcelain) { $sha = "$sha-dirty" }
$version = "{0}-{1}" -f (Get-Date -Format "yyyy.MM.dd"), $sha
$name = "APL-SecurityMonitor-$version"
$releaseRoot = Join-Path $repo "release"
$out = Join-Path $releaseRoot $name
Write-Host "Building $name" -ForegroundColor Cyan

# --- frontend -------------------------------------------------------------
$frontend = Join-Path $repo "frontend"
Push-Location $frontend
try {
    if (-not (Test-Path "node_modules")) { Invoke-Native "npm ci" { npm ci } }
    Invoke-Native "npm run build" { npm run build }
} finally { Pop-Location }

# --- assemble -------------------------------------------------------------
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
$backendOut = Join-Path $out "backend"
New-Item -ItemType Directory -Force (Join-Path $backendOut "models") | Out-Null

Copy-Item (Join-Path $repo "backend\app") (Join-Path $backendOut "app") -Recurse
Get-ChildItem (Join-Path $backendOut "app") -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force
Copy-Item (Join-Path $repo "backend\requirements.txt") $backendOut
Copy-Item (Join-Path $frontend "dist") (Join-Path $backendOut "static") -Recurse

$weights = @("yolov8s.pt")
foreach ($w in $weights) {
    $src = Join-Path $repo "backend\$w"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $backendOut $w)
    } else {
        Write-Warning "backend\$w not found -- not included (feature will be disabled or auto-downloaded)"
    }
}

# pose model for the fight rule (app/analytics/pose.py reads backend\models)
$pose = Join-Path $repo "backend\models\yolov8s-pose.pt"
if (Test-Path $pose) { Copy-Item $pose (Join-Path $backendOut "models") }
else { Write-Warning "backend\models\yolov8s-pose.pt not found -- fight detection will be disabled" }

Copy-Item (Join-Path $repo "deploy\*") $out
Set-Content (Join-Path $out "VERSION.txt") $version -Encoding utf8

# --- zip ------------------------------------------------------------------
$zip = Join-Path $releaseRoot "$name.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $out -DestinationPath $zip
Write-Host "Done: $zip" -ForegroundColor Green
