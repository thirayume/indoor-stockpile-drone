"""High-level entry point: dataset id in, stockpile volume out."""

from core.config import settings
from reconstruction.dataset_utils import prepare_opensfm_project
from reconstruction.opensfm_runner import run_opensfm_pipeline
from reconstruction.volume_compute import VolumeResult, compute_volume


def run_reconstruction_and_volume(dataset_id: str, use_symlink: bool = True) -> VolumeResult:
    """Prepare the OpenSfM project, run the full pipeline, compute the volume.

    Raises FileNotFoundError (dataset/outputs missing), RuntimeError (OpenSfM
    CLI missing), subprocess.CalledProcessError (a pipeline step failed) or
    ValueError (degenerate point cloud).
    """
    prepare_opensfm_project(dataset_id, use_symlink=use_symlink)
    point_cloud = run_opensfm_pipeline(settings.opensfm_project_dir)
    return compute_volume(point_cloud)
