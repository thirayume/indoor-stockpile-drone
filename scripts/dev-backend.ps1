# Backend hot-reload dev server. Edit anything under backend/src and uvicorn
# restarts automatically; Python errors print full tracebacks right in this
# terminal (far easier to debug than a Docker rebuild).
#
# Usage:   .\scripts\dev-backend.ps1        # http://localhost:8000  (docs at /docs)
#
# Note: OpenSfM is NOT installed locally, so POST /volume/jobs (a real
# reconstruction) returns a clean "OpenSfM CLI not found" error here. Every
# other endpoint — datasets, image gallery, orbit sim, and the 3D viewer
# reading an existing merged.ply — works fully. For real reconstructions run
# the backend in Docker instead (it has the OpenSfM CLI baked in).
#
# Stop the Docker backend first so it doesn't hold port 8000:
#   docker compose stop backend
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\backend"
if (-not (Test-Path .venv)) {
    Write-Host "Creating virtualenv + installing deps (first run only)…" -ForegroundColor Cyan
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    & .\.venv\Scripts\pip.exe install -e ".[dev]"
}
Write-Host "FastAPI (reload) -> http://localhost:8000   docs -> http://localhost:8000/docs" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --app-dir src --port 8000
