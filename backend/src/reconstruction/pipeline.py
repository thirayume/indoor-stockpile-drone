"""High-level entry point: dataset id in, stockpile volume out."""

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from core.config import settings
from core.logging import get_logger
from reconstruction.dataset_utils import prepare_opensfm_project
from reconstruction.opensfm_runner import run_opensfm_pipeline
from reconstruction.volume_compute import VolumeResult

logger = get_logger(__name__)


def compute_volume_isolated(
    point_cloud: Path,
    on_progress: Callable[[str], None] | None = None,
) -> VolumeResult:
    """Compute the volume in a subprocess so a native crash can't kill the API.

    Open3D may segfault on scenes that aren't real stockpiles; here that
    surfaces as a clean ValueError instead of taking the whole process down.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result_json = Path(tmp) / "result.json"
        proc = subprocess.Popen(
            [sys.executable, "-m", "reconstruction.volume_worker",
             str(point_cloud), "-", str(result_json)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        error_msg: str | None = None
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("PROGRESS:"):
                if on_progress is not None:
                    on_progress(line[len("PROGRESS:"):])
            elif line.startswith("ERROR:"):
                error_msg = line[len("ERROR:"):]
            elif line:
                logger.info("volume worker: %s", line)
        code = proc.wait()

        if code == 0:
            data = json.loads(result_json.read_text())
            return VolumeResult(
                volume_m3=data["volume_m3"],
                num_points=data["num_points"],
                method=data["method"],
                point_cloud_path=Path(data["point_cloud_path"]),
                mesh_path=Path(data["mesh_path"]) if data["mesh_path"] else None,
                up_vector=tuple(data["up_vector"]) if data["up_vector"] else None,
            )
        if error_msg is not None:
            raise ValueError(error_msg)
        # Negative code = killed by a signal (e.g. -11 SIGSEGV).
        raise ValueError(
            f"volume computation crashed (exit {code}) — the reconstruction "
            "may not contain a well-defined stockpile above a floor plane."
        )


def run_reconstruction_and_volume(
    dataset_id: str,
    use_symlink: bool = True,
    on_progress: Callable[[str], None] | None = None,
    use_exif_gps: bool = False,
) -> VolumeResult:
    """Prepare the OpenSfM project, run the full pipeline, compute the volume.

    on_progress receives human-readable phase descriptions ("opensfm
    reconstruct (5/9)") — used by the job system. use_exif_gps enables
    GPS-based alignment/scale when the dataset's EXIF carries coordinates.

    Raises FileNotFoundError (dataset/outputs missing), RuntimeError (OpenSfM
    CLI missing), subprocess.CalledProcessError (a pipeline step failed) or
    ValueError (degenerate point cloud / volume step failed or crashed).
    """

    def report(phase: str) -> None:
        if on_progress is not None:
            on_progress(phase)

    report("preparing dataset")
    prepare_opensfm_project(dataset_id, use_symlink=use_symlink, use_exif_gps=use_exif_gps)

    point_cloud = run_opensfm_pipeline(
        settings.opensfm_project_dir,
        on_step=lambda step, i, n: report(f"opensfm {step} ({i}/{n})"),
    )

    return compute_volume_isolated(point_cloud, on_progress=report)
