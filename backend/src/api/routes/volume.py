import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.config import settings
from core.jobs import Job, job_manager
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
    method: str = Field(description='Volume method — "grid" (2.5D height integration).')
    point_cloud_path: str
    point_cloud_url: str
    mesh_path: str | None
    mesh_url: str | None
    up_vector: list[float] | None = Field(
        default=None, description="Oriented floor normal; the 3D viewer rotates it to +Y."
    )


class VolumeExampleRequest(BaseModel):
    dataset_id: str | None = None


class VolumeExampleResponse(BaseModel):
    status: str
    dataset_id: str
    volume_m3: float
    ply_path: str = Field(description="Point cloud path relative to the data directory.")
    ply_url: str = Field(description="Download URL served by GET /volume/files/...")


class JobRequest(BaseModel):
    dataset_id: str | None = Field(
        default=None, description=f"Defaults to {DEFAULT_EXAMPLE_DATASET!r}."
    )
    use_symlink: bool = True
    use_exif_gps: bool = Field(
        default=False,
        description="Use GPS from EXIF for georeferenced/true-scale results "
        "(only helps if the dataset's photos carry GPS).",
    )


class JobResponse(BaseModel):
    job_id: str
    kind: str
    dataset_id: str
    status: str
    progress: str | None
    error: str | None
    result: VolumeRunResponse | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def _result_payload(result: VolumeResult) -> dict[str, Any]:
    """Shape a VolumeResult the way VolumeRunResponse expects it."""
    return {
        "volume_m3": result.volume_m3,
        "num_points": result.num_points,
        "method": result.method,
        "point_cloud_path": str(result.point_cloud_path),
        "point_cloud_url": f"/volume/files/{result.point_cloud_path.name}",
        "mesh_path": str(result.mesh_path) if result.mesh_path else None,
        "mesh_url": f"/volume/files/{result.mesh_path.name}" if result.mesh_path else None,
        "up_vector": list(result.up_vector) if result.up_vector else None,
    }


def _job_response(job: Job) -> JobResponse:
    return JobResponse(
        job_id=job.id,
        kind=job.kind,
        dataset_id=job.params.get("dataset_id", ""),
        status=job.status.value,
        progress=job.progress,
        error=job.error,
        result=VolumeRunResponse(**job.result) if job.result else None,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


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


@router.post("/jobs", response_model=JobResponse, status_code=202)
def start_job(request: JobRequest | None = None) -> JobResponse:
    """Queue a reconstruction as a background job; poll GET /volume/jobs/{id}.

    Preferred over the blocking POST /volume/run for anything beyond tiny
    datasets — real reconstructions run for minutes to hours.
    """
    dataset_id = (request.dataset_id if request else None) or DEFAULT_EXAMPLE_DATASET
    use_symlink = request.use_symlink if request else True
    use_exif_gps = request.use_exif_gps if request else False

    def run(job: Job) -> dict[str, Any]:
        def progress(phase: str) -> None:
            job.progress = phase

        result = run_reconstruction_and_volume(
            dataset_id, use_symlink=use_symlink, on_progress=progress, use_exif_gps=use_exif_gps
        )
        return _result_payload(result)

    job = job_manager.submit(
        kind="reconstruction",
        params={
            "dataset_id": dataset_id,
            "use_symlink": use_symlink,
            "use_exif_gps": use_exif_gps,
        },
        fn=run,
    )
    return _job_response(job)


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs() -> list[JobResponse]:
    """All reconstruction jobs of this API process, newest first.

    Segmentation jobs live under /segment/jobs — their results do not fit
    VolumeRunResponse, so they must not be serialised here.
    """
    return [_job_response(job) for job in job_manager.list() if job.kind == "reconstruction"]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    """State of a single job (status, progress, result or error)."""
    job = job_manager.get(job_id)
    if job is None or job.kind != "reconstruction":
        raise HTTPException(status_code=404, detail=f"unknown reconstruction job: {job_id}")
    return _job_response(job)


@router.post("/run", response_model=VolumeRunResponse)
def run_volume(request: VolumeRunRequest) -> VolumeRunResponse:
    """Blocking variant of POST /volume/jobs — fine for scripts, not the UI."""
    result = _reconstruct(request.dataset_id, use_symlink=request.use_symlink)
    return VolumeRunResponse(**_result_payload(result))


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
    from reconstruction.segmentation import CLASSES, load_class_registry

    project = settings.opensfm_project_dir
    depthmaps = project / "undistorted" / "depthmaps"
    files = {
        "merged.ply": [depthmaps / "merged.ply"],
        "reconstruction.ply": [project / "reconstruction.ply"],
        "stockpile_mesh.ply": [depthmaps / "stockpile_mesh.ply", project / "stockpile_mesh.ply"],
        "segmented.ply": [depthmaps / "segmented.ply", project / "segmented.ply"],
    }
    # Per-class clouds for the 3D layer toggles. ML runs discover classes at
    # runtime, so extend the static set with both candidate dirs' registries.
    class_keys = set(CLASSES)
    for outputs in (depthmaps, project):
        class_keys.update(load_class_registry(outputs)[0])
    for klass in class_keys:
        name = f"seg_{klass}.ply"
        files[name] = [depthmaps / name, project / name]
    return files


@router.get("/files/preview.ply")
def download_preview() -> FileResponse:
    """Browser-sized point cloud: the dense cloud downsampled to ~150k points.

    Regenerated lazily whenever the source cloud is newer than the preview.
    """
    from reconstruction.volume_compute import write_preview_cloud

    project = settings.opensfm_project_dir
    src = project / "undistorted" / "depthmaps" / "merged.ply"
    if not src.is_file():
        src = project / "reconstruction.ply"
    if not src.is_file():
        raise HTTPException(
            status_code=404, detail="no point cloud yet — run a reconstruction first"
        )

    dst = src.parent / "preview.ply"
    try:
        if not dst.is_file() or dst.stat().st_mtime < src.stat().st_mtime:
            write_preview_cloud(src, dst)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"cannot write preview (read-only data mount?): {exc}",
        ) from exc
    return FileResponse(dst, filename="preview.ply", media_type="application/octet-stream")


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
        status_code=404, detail=f"{filename} not generated yet — run a reconstruction first"
    )
