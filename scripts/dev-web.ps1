# Frontend hot-reload dev server. Edit anything under web/src and the browser
# refreshes instantly — no Docker rebuild. /api is proxied to VITE_API_URL
# (default http://localhost:8000, where the Docker backend is published), so
# the real backend (including OpenSfM reconstruction) works behind it.
#
# Usage:   .\scripts\dev-web.ps1            # http://localhost:5174
#          $env:DEV_PORT=5300; .\scripts\dev-web.ps1
#
# Keep the Docker backend running for a full app:
#   docker compose -f docker-compose.yml -f docker-compose.opensfm.yml up -d backend
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\web"
if (-not (Test-Path node_modules)) { npm install }
Write-Host "Vite dev server -> http://localhost:$(if ($env:DEV_PORT) { $env:DEV_PORT } else { 5174 })  (proxying /api to $(if ($env:VITE_API_URL) { $env:VITE_API_URL } else { 'http://localhost:8000' }))" -ForegroundColor Cyan
npm run dev
