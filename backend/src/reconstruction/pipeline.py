"""High-level entry points: dataset id in, volume/segmentation out."""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.config import settings
from core.logging import get_logger
from reconstruction.dataset_utils import prepare_opensfm_project
from reconstruction.opensfm_runner import run_opensfm_pipeline
from reconstruction.volume_compute import VolumeResult

logger = get_logger(__name__)


def _run_isolated_worker(
    worker_module: str,
    point_cloud: Path,
    what: str,
    on_progress: Callable[[str], None] | None = None,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """Run an Open3D worker in a subprocess so a native crash can't kill the API.

    The worker prints "PROGRESS:<phase>" lines, an optional "ERROR:<msg>", and
    writes its result JSON. A non-zero/negative exit becomes a clean ValueError.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result_json = Path(tmp) / "result.json"
        cmd = [sys.executable, "-m", worker_module, str(point_cloud), "-", str(result_json)]
        cmd += extra_args or []
        # UTF-8 on both ends of the pipe: on Windows the default pipe encoding
        # is cp1252, which chokes on the UTF-8 progress bars ML libraries
        # print. errors="replace" keeps a truncated bar from killing the job.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
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
                logger.info("%s: %s", worker_module, line)
        code = proc.wait()

        # Read the result before the temp dir is cleaned up on block exit.
        if code == 0:
            return json.loads(result_json.read_text())
        if error_msg is not None:
            raise ValueError(error_msg)
        raise ValueError(
            f"{what} crashed (exit {code}) — the reconstruction may be unsuitable "
            "(no well-defined stockpile / objects above a floor plane)."
        )


def compute_volume_isolated(
    point_cloud: Path,
    on_progress: Callable[[str], None] | None = None,
) -> VolumeResult:
    """Compute the volume in a subprocess (Open3D can segfault on odd scenes)."""
    data = _run_isolated_worker(
        "reconstruction.volume_worker", point_cloud, "volume computation", on_progress
    )
    return VolumeResult(
        volume_m3=data["volume_m3"],
        num_points=data["num_points"],
        method=data["method"],
        point_cloud_path=Path(data["point_cloud_path"]),
        mesh_path=Path(data["mesh_path"]) if data["mesh_path"] else None,
        up_vector=tuple(data["up_vector"]) if data["up_vector"] else None,
    )


def run_segmentation_isolated(
    point_cloud: Path,
    on_progress: Callable[[str], None] | None = None,
    mode: str = "geometry",
    class_prompts: list[str] | None = None,
) -> dict[str, Any]:
    """Segment the scene in a subprocess; returns the raw dict.

    mode "geometry" is the heuristic colour+shape pass; "ml" runs the
    open-vocabulary model (class_prompts = text prompts, None = auto-detect).
    """
    extra = ["--mode", mode]
    if class_prompts:
        extra += ["--classes", json.dumps(class_prompts)]
    return _run_isolated_worker(
        "reconstruction.segment_worker", point_cloud, "segmentation", on_progress, extra
    )


def run_reconstruction_and_volume(
    dataset_id: str,
    use_symlink: bool = True,
    on_progress: Callable[[str], None] | None = None,
    use_exif_gps: bool = False,
) -> VolumeResult:
    """Prepare the OpenSfM project, run the full pipeline, compute the volume.

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
