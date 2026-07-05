"""Wrap the OpenSfM CLI to run SfM/MVS on a prepared dataset folder.

The project folder follows OpenSfM's dataset layout:
    project_dir/
    ├── config.yaml
    ├── images/
    └── (pipeline outputs: reconstruction.json, undistorted/, ...)

The `opensfm` binary is expected on PATH — it is not bundled in the backend
image (heavy C++ source build); see README for options.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

# Full OpenSfM pipeline, in order. `mesh` builds per-image meshes used by
# undistort; `compute_depthmaps` produces the dense cloud; `export_ply`
# exports the sparse reconstruction as a fallback point cloud.
PIPELINE_STEPS = [
    "extract_metadata",
    "detect_features",
    "match_features",
    "create_tracks",
    "reconstruct",
    "mesh",
    "undistort",
    "compute_depthmaps",
    "export_ply",
]

def run_step(step: str, project_dir: Path, opensfm_bin: str = "opensfm") -> None:
    """Run a single OpenSfM pipeline step on the given project directory."""
    cmd = [opensfm_bin, step, str(project_dir)]
    logger.info("Running: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"OpenSfM CLI not found ({opensfm_bin!r}) — is it installed and on PATH? "
            "See README, section 'Note on OpenSfM'."
        ) from exc


def run_opensfm_pipeline(
    project_dir: Path,
    opensfm_bin: str = "opensfm",
    steps: list[str] | None = None,
    on_step: Callable[[str, int, int], None] | None = None,
) -> Path:
    """Run the OpenSfM pipeline; return the path to the best point cloud.

    on_step(name, index, total) is called before each step — used by the
    job system to publish progress.
    """
    if not (project_dir / "images").is_dir():
        raise FileNotFoundError(f"no images/ folder in OpenSfM project: {project_dir}")

    pipeline = steps or PIPELINE_STEPS
    for i, step in enumerate(pipeline, start=1):
        if on_step is not None:
            on_step(step, i, len(pipeline))
        run_step(step, project_dir, opensfm_bin=opensfm_bin)

    return find_point_cloud(project_dir)


def run_full_pipeline(project_dir: Path | None = None, opensfm_bin: str = "opensfm") -> Path:
    """Run the whole pipeline on the configured project; return the point cloud.

    Convenience wrapper around run_opensfm_pipeline defaulting to
    settings.opensfm_project_dir (data/opensfm_project).
    """
    return run_opensfm_pipeline(
        project_dir or settings.opensfm_project_dir, opensfm_bin=opensfm_bin
    )


def find_point_cloud(project_dir: Path) -> Path:
    """Prefer the dense cloud; fall back to the sparse export_ply output."""
    dense = project_dir / "undistorted" / "depthmaps" / "merged.ply"
    if dense.exists():
        return dense
    sparse = project_dir / "reconstruction.ply"
    if sparse.exists():
        logger.warning("Dense cloud missing; falling back to sparse %s", sparse)
        return sparse
    raise FileNotFoundError(f"no point cloud found in {project_dir}")
