"""High-level entry point: dataset id in, stockpile volume out."""

from collections.abc import Callable

from core.config import settings
from reconstruction.dataset_utils import prepare_opensfm_project
from reconstruction.opensfm_runner import run_opensfm_pipeline
from reconstruction.volume_compute import VolumeResult, compute_volume


def run_reconstruction_and_volume(
    dataset_id: str,
    use_symlink: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> VolumeResult:
    """Prepare the OpenSfM project, run the full pipeline, compute the volume.

    on_progress receives human-readable phase descriptions ("opensfm
    reconstruct (5/9)") — used by the job system.

    Raises FileNotFoundError (dataset/outputs missing), RuntimeError (OpenSfM
    CLI missing), subprocess.CalledProcessError (a pipeline step failed) or
    ValueError (degenerate point cloud).
    """

    def report(phase: str) -> None:
        if on_progress is not None:
            on_progress(phase)

    report("preparing dataset")
    prepare_opensfm_project(dataset_id, use_symlink=use_symlink)

    point_cloud = run_opensfm_pipeline(
        settings.opensfm_project_dir,
        on_step=lambda step, i, n: report(f"opensfm {step} ({i}/{n})"),
    )

    report("computing volume")
    return compute_volume(point_cloud)
