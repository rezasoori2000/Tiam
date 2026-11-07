# One-time install on the server: creates backend\venv with CUDA PyTorch +
# the app's Python dependencies, and creates config.ps1 from the example.
#
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Prerequisites: Python 3.12 (py launcher), NVIDIA driver, ODBC Driver 17.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$py = Join-Path $backend "venv\Scripts\python.exe"

function Invoke-Native([string]$what, [scriptblock]$cmd) {
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

if (-not (Test-Path $py)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    Invoke-Native "venv" { py -3.12 -m venv (Join-Path $backend "venv") }
}

Invoke-Native "pip upgrade" { & $py -m pip install --upgrade pip }

# RTX 50-series (Blackwell) needs a CUDA 12.8+ PyTorch build. Must be
# installed BEFORE requirements.txt, otherwise ultralytics pulls in the
# CPU-only torch from PyPI.
Write-Host "Installing PyTorch (CUDA 12.8)..." -ForegroundColor Cyan
Invoke-Native "torch install" {
    & $py -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
}

Write-Host "Installing app dependencies..." -ForegroundColor Cyan
Invoke-Native "requirements install" { & $py -m pip install -r (Join-Path $backend "requirements.txt") }

Write-Host "Checking GPU..." -ForegroundColor Cyan
Invoke-Native "GPU check" {
    & $py -c "import torch; assert torch.cuda.is_available(), 'CUDA NOT AVAILABLE - check NVIDIA driver'; print('GPU OK:', torch.cuda.get_device_name(0))"
}

$config = Join-Path $root "config.ps1"
if (-not (Test-Path $config)) {
    Copy-Item (Join-Path $root "config.example.ps1") $config
    Write-Host "Created config.ps1 -- review it before continuing." -ForegroundColor Yellow
}
Write-Host "Install complete. Next: setup-database.ps1" -ForegroundColor Green
