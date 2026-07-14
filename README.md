# Indoor Stockpile Drone (No GPS)

Prototype / reference repo for estimating stockpile volumes in GPS-denied
indoor environments:

- **Simulation** — orbit and grid/lawnmower flight patterns, one shot per
  dataset image, designed for PX4/ArduPilot SITL via MAVSDK (mocked so it
  runs anywhere). The pattern is chosen per dataset (aerial → grid, object
  scan → orbit).
- **Reconstruction** — OpenSfM pipeline over example image datasets
  (ODMdata) producing a dense point cloud (`merged.ply`), optionally
  GPS-georeferenced.
- **Volume** — Open3D floor-plane removal + 2.5D grid integration.
- **Segmentation** — geometry + colour classification of the reconstruction
  into trees and roofs, with counts and per-object volume (no ML models).
- **API + UI** — FastAPI backend and a Vite + React + TypeScript web UI.

No real drone hardware is involved; everything is simulation / offline
processing on example datasets.

### Example datasets

Clone any into `data/odm/<name>/` (each is a separate repo the ODMdata
catalog links to). The three used in development:

| Dataset | Kind | Flight | Shows |
|---------|------|--------|-------|
| `banana` | close-up object scan (no GPS) | orbit | volume + 3D view |
| `brighton_beach` | aerial, GPS | grid | trees (coastal, no buildings) |
| `toledo` | aerial suburban, GPS | grid | trees **and roofs** |

## Repository layout

```text
backend/          FastAPI app, simulation and reconstruction modules (Python 3.11)
web/              Vite + React + TypeScript UI
data/odm/         Example datasets (ODMdata — submodule or manual copy)
data/opensfm_project/   OpenSfM dataset skeleton (config.yaml, images/)
docker-compose.yml
```

## Cloning

The ODMdata catalog is a git submodule at `data/odm/`, so clone with
submodules:

```bash
git clone --recurse-submodules https://github.com/thirayume/indoor-stockpile-drone.git
# or, in an existing checkout:
git submodule update --init --recursive
```

## Set up on a new machine (fetch the datasets)

The source images (~1 GB across banana / brighton_beach / toledo) are **not**
in this repo — they live in their own upstream repos. One script fetches all
of them, pinned to exact commits so every machine reconstructs from
byte-identical inputs:

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts\setup-data.ps1
```
```bash
# macOS / Linux / Git Bash
bash scripts/setup-data.sh
```

It is idempotent — safe to re-run to repair or update `data/odm/`. After it
finishes, start the app and run a reconstruction (below); reconstruction
outputs (`data/opensfm_project/`, ~230 MB, regenerated per run) are derived
data and are intentionally not shipped. Same images + same code = same
results, so a fresh machine matches this one after one reconstruction.

To carry a **prebuilt** reconstruction to another PC (skip the ~30 min run and
segment immediately), copy the whole `data/opensfm_project/` folder across by
any means (USB, cloud) — it is self-contained.

## Quick start (Docker)

First copy the environment template — it wires the two things this project
needs from compose (host ports + the OpenSfM overlay), and matches the
reference machine exactly:

```bash
cp .env.example .env        # Windows cmd: copy .env.example .env
```

Then bring it up (the `.env` is read automatically):

```bash
docker compose up -d --build     # or: docker-compose up -d --build
```

- Web UI: http://localhost:5273  *(the port set in `.env.example`; edit
  `WEB_PORT` there if you prefer 5173 or another free port)*
- API: http://localhost:8000 — interactive docs at http://localhost:8000/docs

The `COMPOSE_FILE` line in `.env` layers `docker-compose.opensfm.yml` on top
automatically, so `docker compose` commands need no `-f` flags — the backend
comes up **with the OpenSfM CLI and a writable data mount**, ready to run real
reconstructions. (The first build compiles OpenSfM from source and takes a
while; it is cached afterwards.)

Then test the workflow end-to-end in the UI: **1.** pick a dataset (fetched by
`setup-data`, above) → **2.** *Run flight simulation* → **3.** *Run
reconstruction & volume* (GPS is off by default — tick the box only for
GPS-carrying datasets) → **4.** *Segment objects* (trees / roofs / roads /
vehicles / piles, with toggleable overlays on the 3D view, the merged
top-down photo, and the original photos).

Build notes:

- The web image serves a production build via `vite preview`; switch the
  compose `target` to `dev` for the hot-reload dev server.
- To run the **lightweight backend without OpenSfM** (Open3D volume and
  segmentation on a prebuilt point cloud, no reconstruction), delete the
  `COMPOSE_PATH_SEPARATOR`/`COMPOSE_FILE` lines from `.env`.

## Local development (fast — don't rebuild Docker to code)

Docker is for **deploy / final integration**. For day-to-day coding use
hot reload so you see changes and errors instantly. On Windows, three
helper scripts wrap the commands below:

| Script | What it does |
|--------|--------------|
| `.\scripts\dev-web.ps1` | Vite dev server with **hot reload** (browser refreshes on save). Edit `web/src/**` and watch it update. React errors show in the browser console (F12). |
| `.\scripts\dev-backend.ps1` | uvicorn with `--reload`. Edit `backend/src/**` and it restarts; **Python tracebacks print in the terminal**. |
| `.\scripts\check.ps1` | Pre-deploy gate: ruff + pytest + web type-check/build. Run this to catch code problems **before** a Docker rebuild. |

### Recommended: hot-reload UI against the Dockerized backend

Best for frontend work — instant UI feedback *and* a fully working backend
(including OpenSfM reconstruction, which needs the Docker image):

```powershell
# 1. backend in Docker (published on host :8000, has OpenSfM)
docker compose -f docker-compose.yml -f docker-compose.opensfm.yml up -d backend
# 2. frontend hot-reloading locally -> http://localhost:5174
.\scripts\dev-web.ps1
```

The dev server proxies `/api/*` to `http://localhost:8000` (override with
`VITE_API_URL`) and runs on port 5174 (override with `DEV_PORT`) to avoid
the Docker web port (5273).

### Backend logic work

```powershell
docker compose stop backend        # free port 8000
.\scripts\dev-backend.ps1          # http://localhost:8000, docs at /docs
```

Every endpoint works except a real reconstruction (`POST /volume/jobs`),
which needs the OpenSfM CLI that only the Docker image has — locally it
returns a clean "OpenSfM CLI not found" error. Use the Docker backend for
actual reconstructions.

### Manual commands (any OS)

```bash
cd backend && python -m venv .venv && pip install -e ".[dev]"
uvicorn api.main:app --reload --app-dir src   # backend
pytest && ruff check src tests                 # test + lint
cd web && npm install && npm run dev           # frontend
```

## Datasets

`data/odm/` is the [ODMdata](https://github.com/OpenDroneMap/ODMdata)
submodule — a **catalog** (README of links), not the images themselves. Fetch
an actual dataset by cloning one of the `odm_data_*` repos it links to into
`data/odm/<name>`:

```bash
git clone https://github.com/OpenDroneMap/odm_data_aukerman.git data/odm/aukerman
# other small ones: odm_data_toledo, odm_data_seneca, ...
```

(These clones stay untracked inside the submodule; the parent repo is
configured to ignore them.)

### Selecting a dataset

Use the helper in `backend/src/reconstruction/dataset_utils.py` to list
datasets and link/copy one into the OpenSfM project:

```bash
cd backend
python -m reconstruction.dataset_utils list
python -m reconstruction.dataset_utils prepare aukerman          # symlink (default)
python -m reconstruction.dataset_utils prepare aukerman --copy   # copy files instead
```

This populates `data/opensfm_project/images/`. Symlinking avoids duplicating
image data but on Windows needs Developer Mode (or admin); the tool falls
back to copying automatically. The same listing backs the API's
`GET /datasets`, so prepared datasets also show up in the web UI selector.

## Reference documentation (`docs/opensfm/`)

`docs/opensfm/` holds downloaded OpenSfM reference material (gitignored —
each clone fetches its own copy):

- `opensfm-docs.pdf` — the official documentation PDF (Read the Docs build).
- `default_config.py` — OpenSfM's `config.py` with the `OpenSfMConfig`
  dataclass: every `config.yaml` option, its default value and a doc
  comment. The config reference page no longer exists on opensfm.org, so
  this is the authoritative option list.
- `dataset.html` — the dataset-structure docs page.

Fetch or refresh them with (standard library only, no extra deps):

```bash
python tools/download_refs.py            # skips files that already exist
python tools/download_refs.py --force    # re-download everything
```

## Running the pipeline

1. Open the web UI, pick a dataset, and use **Run orbit simulation**. If a
   PX4 SITL instance is reachable on `udp://:14540` the orbit is actually
   flown via MAVSDK (arm → takeoff → offboard orbit with camera-trigger log
   events → land); otherwise it falls back to an offline simulation that
   computes the same camera poses, so the demo works anywhere. Easiest way
   to run SITL:

   ```bash
   docker run --rm -p 14540:14540/udp jonasvautherin/px4-gazebo-headless:1.14
   ```

   (or from a PX4 source build: `make px4_sitl jmavsim`). The command used
   by `sim.sitl_runner.start_sitl` is configurable via
   `STOCKPILE_SITL_COMMAND`.
2. **Run reconstruction & volume** calls the backend, which prepares
   `data/opensfm_project/` for the selected dataset, runs the OpenSfM
   pipeline (`extract_metadata` → … → `compute_depthmaps` → `export_ply`)
   and estimates the volume from `undistorted/depthmaps/merged.ply`
   (falling back to the sparse `reconstruction.ply` if dense
   reconstruction produced nothing). The floor plane is RANSAC-segmented,
   the largest cluster above it is taken as the stockpile, and the volume
   comes from a watertight alpha-shape mesh (written to
   `stockpile_mesh.ply`) or, failing that, 2.5D grid integration of
   heights above the floor.

> **Scale caveat:** without GPS or ground control points, an OpenSfM
> reconstruction has arbitrary scale — the reported number is in *model
> units³*, not true m³. To get real volumes, provide GCPs
> (`gcp_list.txt` + `bundle_use_gcp: yes` in `config.yaml`) or scale the
> model by a known distance.

### Note on OpenSfM

The default backend image does **not** build OpenSfM (heavy C++ build, no
wheels). To run real reconstructions — this path is verified end-to-end —
use the overlay, which bakes in OpenSfM *and* makes the data mount
writable. Works the same in bash, PowerShell and cmd:

```bash
docker compose -f docker-compose.yml -f docker-compose.opensfm.yml up --build
```

(The equivalent by hand: build with the `INSTALL_OPENSFM=true` build arg —
`set INSTALL_OPENSFM=true` in cmd / `$env:INSTALL_OPENSFM="true"` in
PowerShell before `docker compose build backend` — and drop `:ro` from the
`./data` mount. The `VAR=value command` one-liner is bash-only.)

The build stage mirrors upstream's `Dockerfile.ubuntu24` (scikit-build-core
+ OpenCV/Ceres/Eigen) and adds an `/usr/local/bin/opensfm` wrapper, since
upstream installs no console entry point. Verified result: the full
pipeline over the 16-image `banana` dataset runs in ~6 minutes on CPU and
produces a ~37 MB dense `merged.ply`.

### Running the example reconstruction in the container

The backend image ships `run_example_reconstruction.py`; the host `./data`
(ODMdata submodule included) is mounted at `/app/data`:

```bash
# with the read-only compose default (lists datasets, then explains the ro mount):
docker compose run --rm backend python run_example_reconstruction.py

# with a writable data mount (requires the opensfm CLI in the image, see above):
docker run --rm -v "$PWD/data:/app/data" \
  -e STOCKPILE_DATA_DIR=/app/data \
  -e OPEN_SFM_DATA_ROOT=/app/data/opensfm_project \
  indoor-stockpile-drone-backend \
  python run_example_reconstruction.py --dataset banana
```

Note: inside the container the image symlink cannot be created on the
Windows bind mount, so `dataset_utils` automatically falls back to copying
the images — no action needed.

## API overview

| Method | Path                      | Purpose                                            |
|--------|---------------------------|----------------------------------------------------|
| GET    | `/health`                 | Liveness check                                     |
| GET    | `/datasets`               | List dataset folders under `data/odm/`             |
| POST   | `/sim/orbit`              | Run orbit flight (MAVSDK or offline), return logs  |
| POST   | `/volume/jobs`            | Queue a reconstruction job (what the UI uses)      |
| GET    | `/volume/jobs/{id}`       | Poll job status / progress / result                |
| GET    | `/volume/jobs`            | List jobs, newest first                            |
| POST   | `/volume/run`             | Blocking reconstruction (scripts only)             |
| POST   | `/volume/example`         | Blocking demo run, defaults to `banana`            |
| GET    | `/volume/files/{filename}`| Download `merged.ply` / `stockpile_mesh.ply` etc.  |

Interactive documentation for all endpoints: http://localhost:8000/docs

Reconstructions run for minutes to hours, so the UI submits a **background
job** and polls it; progress reports the current OpenSfM step. Job state is
in-process: run the API as a single process (uvicorn's default, as in the
Docker image) — swap `core/jobs.py` for a persistent queue if the API ever
needs replicas.
