# Project: Indoor Stockpile Drone (No GPS) – Python + Docker + Web UI

## Goal

Build a prototype repository for:

- Simulating drone flight patterns in GPS-denied indoor environments.
- Running photogrammetry / 3D reconstruction from example image datasets.
- Computing stockpile volumes from 3D models.
- Exposing the workflow via a Python backend (FastAPI) and a simple Web UI.
- All runnable via Docker / docker-compose.

We will NOT control a real drone here. This is a *reference* / prototype repo:
- Flight logic is simulated using SITL (PX4 or ArduPilot) and Python (MAVSDK or DroneKit).
- 3D reconstruction uses example datasets (e.g. ODMdata, OpenSfM sample datasets).
- Volume calculation uses Open3D or similar Python libraries.

## Tech Stack

- Backend: Python 3.11+
  - FastAPI (HTTP API)
  - MAVSDK-Python or DroneKit-Python for simulation
  - OpenSfM CLI for SfM/MVS reconstruction
  - Open3D / NumPy for point cloud / mesh and volume computation
- Web UI: React (Vite or Next.js), TypeScript
- Containerisation: Docker + docker-compose
- Testing: pytest

## Repository Layout

Target structure:

```text
indoor-stockpile-drone/
├── Claude.md
├── Skill.md
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/
│   │   ├── sim/
│   │   │   ├── __init__.py
│   │   │   ├── sitl_runner.py        # Start/stop SITL
│   │   │   └── orbit_capture.py      # Simulate orbit flight & camera triggers
│   │   ├── reconstruction/
│   │   │   ├── __init__.py
│   │   │   ├── opensfm_runner.py     # Wrap OpenSfM CLI
│   │   │   └── volume_compute.py     # Use Open3D to compute volume
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── main.py               # FastAPI app
│   │   │   └── routes/
│   │   │       ├── sim.py            # endpoints to start sim / fetch logs
│   │   │       └── volume.py         # endpoints to run reconstruction & return volume
│   │   └── core/
│   │       ├── config.py
│   │       └── logging.py
│   └── tests/
├── web/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   └── components/
│   │       ├── SimulationPanel.tsx
│   │       ├── VolumePanel.tsx
│   │       └── DatasetSelector.tsx
│   └── public/
└── data/
    ├── odm/                          # git submodule: OpenDroneMap/ODMdata
    └── opensfm_project/              # OpenSfM dataset skeleton
        ├── config.yaml
        ├── images/                   # symlink/copy from odm dataset
        └── gcp_list.txt              # optional, later

## Coding Principles

- Prefer clear, small modules with explicit responsibilities.
- Keep all external tool invocations (OpenSfM CLI, SITL startup) isolated behind Python functions.
- Use type hints for core modules (`sim`, `reconstruction`, `api`).
- Avoid over-engineering: this is a reference prototype, not production.

## Docker Requirements

- `backend/Dockerfile`:
  - Base: `python:3.11-slim`
  - Install system deps needed for OpenSfM and Open3D (e.g. build tools, `libgl1`, etc.).
  - Install Python deps via `poetry` or `pip` using `pyproject.toml` or `requirements.txt`.
  - Expose FastAPI on port 8000.

- `web/Dockerfile`:
  - Base: `node:20-alpine`
  - Install dependencies and build static assets.
  - Serve via `npm run dev` (for dev) or `npm run preview` / simple Node server.

- `docker-compose.yml`:
  - Define `backend` and `web` services.
  - Map ports: backend 8000, web 5173 (or 3000).
  - Mount `data/` read-only into backend container.

## Data & Reconstruction

- Use example datasets from ODMdata as initial `images/`.
- Provide helper scripts to:
  - Link/copy a chosen dataset into `data/opensfm_project/images/`.
  - Run OpenSfM pipeline (via `opensfm_runner.py`) to produce `merged.ply`.
  - Run `volume_compute.py` to estimate stockpile volume from `merged.ply`.

## Web UI Behaviour

Minimum features:

- Dataset selector:
  - List available datasets under `data/odm/`.
  - Send selected dataset name to backend API to prepare OpenSfM project.

- Simulation panel:
  - Controls to "Run orbit simulation" (calls backend to start SITL + orbit script).
  - Display simple logs/state (flight progress, number of simulated camera triggers).

- Volume panel:
  - Button "Run reconstruction & volume" → calls backend to:
    - Run OpenSfM pipeline.
    - Run volume computation.
  - Show numeric volume result (m³) and links to download point cloud/mesh files (e.g. `merged.ply`).

## Tasks for Claude Code

When asked, you should:

1. Scaffold the repository structure and minimal files listed above.
2. Add `pyproject.toml` or `requirements.txt` with sensible dependencies.
3. Implement simulation stubs using MAVSDK-Python or DroneKit for SITL.
4. Implement OpenSfM / Open3D integration modules.
5. Implement FastAPI with endpoints covering simulation and volume computation.
6. Implement a simple React Web UI that talks to FastAPI.
7. Add Dockerfiles and docker-compose for local deployment.
8. Provide example commands in README to run everything end-to-end.

Do NOT assume real hardware; treat everything as simulation / offline processing using example datasets.