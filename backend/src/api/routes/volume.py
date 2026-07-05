import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.config import settings
from reconstruction.pipeline import run_reconstruction_and_volume
from reconstruction.volume_compute import VolumeResult

router = APIRouter(prefix="/volume", tags=["volume"])

DEFAULT_EXAMPLE_DATASET = "banana"


class VolumeRunRequest(BaseModel):
    dataset_id: str
    use_symlink: bool = Field(
        default=True,
        description="Symlink dataset images into the project (copy if false).",
    )


class VolumeRunResponse(BaseModel):
    volume_m3: float = Field(description="Model units³ unless the model is GCP-scaled.")
    num_points: int
    method: str = Field(description='"mesh" (watertight alpha shape) or "grid".')
    point_cloud_path: str
    point_cloud_url: str
    mesh_path: str | None
    mesh_url: str | None


class VolumeExampleRequest(BaseModel):
    dataset_id: str | None = None


class VolumeExampleResponse(BaseModel):
    status: str
    dataset_id: str
    volume_m3: float
    ply_path: str = Field(description="Point cloud path relative to the data directory.")
    ply_url: str = Field(description="Download URL served by GET /volume/files/...")


def _reconstruct(dataset_id: str, use_symlink: bool = True) -> VolumeResult:
    """Run the full pipeline, mapping domain errors to HTTP status codes.

    run_reconstruction_and_volume performs dataset preparation
    (prepare_opensfm_project) itself before invoking OpenSfM.
    """
    try:
        return run_reconstruction_and_volume(dataset_id, use_symlink=use_symlink)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/run", response_model=VolumeRunResponse)
def run_volume(request: VolumeRunRequest) -> VolumeRunResponse:
    """Prepare the dataset, run the OpenSfM pipeline, estimate pile volume."""
    result = _reconstruct(request.dataset_id, use_symlink=request.use_symlink)
    return VolumeRunResponse(
        volume_m3=result.volume_m3,
        num_points=result.num_points,
        method=result.method,
        point_cloud_path=str(result.point_cloud_path),
        point_cloud_url=f"/volume/files/{result.point_cloud_path.name}",
        mesh_path=str(result.mesh_path) if result.mesh_path else None,
        mesh_url=f"/volume/files/{result.mesh_path.name}" if result.mesh_path else None,
    )


@router.post("/example", response_model=VolumeExampleResponse)
def run_example(request: VolumeExampleRequest | None = None) -> VolumeExampleResponse:
    """One-click demo: reconstruct a known example dataset (default: banana)."""
    dataset_id = (request.dataset_id if request else None) or DEFAULT_EXAMPLE_DATASET
    result = _reconstruct(dataset_id)
    return VolumeExampleResponse(
        status="ok",
        dataset_id=dataset_id,
        volume_m3=result.volume_m3,
        ply_path=_data_relative(result.point_cloud_path),
        ply_url=f"/volume/files/{result.point_cloud_path.name}",
    )


def _data_relative(path: Path) -> str:
    """Path relative to the data dir, or absolute if outside it."""
    try:
        return path.relative_to(settings.data_dir).as_posix()
    except ValueError:
        return str(path)


def _downloadable_files() -> dict[str, list[Path]]:
    """Whitelist of downloadable artefacts and where the pipeline puts them."""
    project = settings.opensfm_project_dir
    depthmaps = project / "undistorted" / "depthmaps"
    return {
        "merged.ply": [depthmaps / "merged.ply"],
        "reconstruction.ply": [project / "reconstruction.ply"],
        "stockpile_mesh.ply": [depthmaps / "stockpile_mesh.ply", project / "stockpile_mesh.ply"],
    }


@router.get("/files/{filename}")
def download_file(filename: str) -> FileResponse:
    """Download a reconstruction artefact (whitelisted filenames only)."""
    candidates = _downloadable_files().get(filename)
    if candidates is None:
        raise HTTPException(status_code=404, detail=f"unknown file: {filename}")
    for path in candidates:
        if path.is_file():
            return FileResponse(path, filename=filename, media_type="application/octet-stream")
    raise HTTPException(
        status_code=404, detail=f"{filename} not generated yet — run POST /volume/run first"
    )
