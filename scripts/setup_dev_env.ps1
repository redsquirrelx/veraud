$ErrorActionPreference = "Stop"
$projectRootPath = (Get-Location).Path

Write-Host ""
Write-Host "Setting up dev environment..."
Write-Host ""
Write-Host ""

uv python install
fnm install
fnm use

$currentPath = Join-Path $projectRootPath "\backend"
Set-Location $currentPath
pnpm install

$currentPath = Join-Path $projectRootPath "\frontend"
Set-Location $currentPath
pnpm install

$currentPath = Join-Path $projectRootPath "\agent-server"
Set-Location $currentPath
uv sync

Set-Location $projectRootPath
Write-Host ""
Write-Host ""
Write-Host "Development environment ready."
Write-Host ""
