\# Skills for Indoor Stockpile Drone Project



\## skill:sim-flight



Purpose:

\- Work with PX4/ArduPilot SITL and Python (MAVSDK or DroneKit).

\- Implement orbit flight patterns and camera trigger logic for simulation.



Capabilities:

\- Write Python code using MAVSDK-Python or DroneKit-SITL to:

&#x20; - Connect to SITL instance (`udp://:14540` etc.).

&#x20; - Arm, takeoff, land.

&#x20; - Execute a circular/orbit trajectory around a virtual point.

&#x20; - Log simulated "camera triggers" at given intervals.



Constraints:

\- No real hardware: always assume SITL or mocked connections.

\- Keep module APIs simple, e.g. `run\_orbit\_sim(dataset\_id: str) -> SimResult`.



\## skill:reconstruction



Purpose:

\- Use OpenSfM and OpenDroneMap-style datasets to build 3D models.

\- Use Open3D to compute volumes from point clouds/meshes.



Capabilities:

\- Prepare OpenSfM-compatible dataset folders (`config.yaml`, `images/` etc.).

\- Call OpenSfM CLI commands (e.g. `opensfm reconstruct`, `export\_ply`) via Python wrappers.

\- Load `.ply` files into Open3D.

\- Segment ground plane and isolate stockpile points.

\- Build a surface mesh (alpha shape or Poisson) and compute volume (m³).



Constraints:

\- Assume datasets come from `data/odm/` (ODMdata) as examples.\[1]

\- Do not hard-code absolute paths; use configuration and `Path` objects.



\## skill:backend-api



Purpose:

\- Provide FastAPI endpoints for the Web UI and CLI usage.



Capabilities:

\- Implement FastAPI app in `backend/src/api/main.py`.

\- Provide endpoints:

&#x20; - `GET /datasets` → list available example datasets.

&#x20; - `POST /sim/orbit` → kick off orbit simulation (non-blocking or blocking).

&#x20; - `POST /volume/run` → run reconstruction pipeline and return volume + file paths.

\- Integrate `sim-flight` and `reconstruction` modules cleanly.



Constraints:

\- Use Pydantic models for request/response.

\- Ensure endpoints are simple and well-documented.



\## skill:web-ui



Purpose:

\- Build a simple React-based UI to interact with the FastAPI backend.



Capabilities:

\- Scaffold a Vite + React + TypeScript project under `web/`.

\- Implement components:

&#x20; - `DatasetSelector` → select dataset / call `/datasets`.

&#x20; - `SimulationPanel` → trigger orbit sim / show status.

&#x20; - `VolumePanel` → run reconstruction / show numeric volume and links.

\- Handle basic error states and loading indicators.



Constraints:

\- No need for 3D viewer at first; links to download PLY/mesh are enough.

\- Keep styling minimal (Tailwind or simple CSS modules).



\## skill:devops-docker



Purpose:

\- Containerise backend and web UI; orchestrate with docker-compose.



Capabilities:

\- Write `backend/Dockerfile` for Python app, including OpenSfM/Open3D deps.

\- Write `web/Dockerfile` for React app.

\- Write `docker-compose.yml` to:

&#x20; - Build and run backend and web.

&#x20; - Expose ports (8000 for backend, 5173 for web).

&#x20; - Mount `data/` read-only into backend.



Constraints:

\- Provide commands and notes in `README.md` to:

&#x20; - `docker-compose up --build`

&#x20; - Access web UI and test end-to-end workflow.

