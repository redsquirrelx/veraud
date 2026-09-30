$ErrorActionPreference = "Stop"
$projectRootPath = (Get-Location).Path

Write-Host "#### Setting up dev environment... ####"
Write-Host ""
Write-Host ""

if (-not (Test-Path (Join-Path $projectRootPath ".env"))) {
    Write-Host ".env file doesn't exist... Creating one from .env.template."
    Copy-Item -Path (Join-Path $projectRootPath ".env.template") -Destination (Join-Path $projectRootPath ".env")
}

try {
    Write-Host "#### Installing runtimes... ####"
    uv python install
    fnm install
    fnm use

    Write-Host "#### Installing dependencies... ####"
    $currentPath = Join-Path $projectRootPath "\backend"
    Set-Location $currentPath
    pnpm install
    pnpm prisma generate
    pnpm prisma migrate dev

    $currentPath = Join-Path $projectRootPath "\frontend"
    Set-Location $currentPath
    pnpm install

    $currentPath = Join-Path $projectRootPath "\agent-server"
    Set-Location $currentPath
    uv sync

    Write-Host ""
    Write-Host "#### A .env file was created from the template. Update the values if needed. ####"
    Copy-Item -Path (Join-Path $projectRootPath ".env.template") -Destination (Join-Path $projectRootPath ".env")

    Write-Host ""
    Write-Host "#### Development environment ready. ####"
    Write-Host ""
}
catch {
    Write-Warning "#### Failed to prepare the environment. ####"
}
finally {
    Set-Location $projectRootPath
}
