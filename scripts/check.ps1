# Pre-deploy checks — run this before a Docker rebuild to catch problems fast.
# Mirrors what CI runs: backend lint + tests, and the web type-check/build
# (which is what surfaces TypeScript/React errors without shipping to Docker).
$ErrorActionPreference = "Stop"
$root = "$PSScriptRoot\.."

Write-Host "== ruff (backend lint) ==" -ForegroundColor Cyan
Set-Location $root\backend
if (-not (Test-Path .venv)) {
    python -m venv .venv
    & .\.venv\Scripts\pip.exe install -e ".[dev]"
}
& .\.venv\Scripts\python.exe -m ruff check src tests ..\tools

Write-Host "`n== pytest (backend tests) ==" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pytest -q

Write-Host "`n== tsc + vite build (web type-check) ==" -ForegroundColor Cyan
Set-Location $root\web
if (-not (Test-Path node_modules)) { npm install }
npm run build

Write-Host "`nAll checks passed. Safe to rebuild Docker." -ForegroundColor Green
