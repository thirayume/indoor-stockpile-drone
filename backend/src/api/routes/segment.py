from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import settings
from core.jobs import Job, job_manager
from reconstruction.opensfm_runner import find_point_cloud
from reconstruction.pipeline import run_segmentation_isolated

router = APIRouter(prefix="/segment", tags=["segmentation"])


class SegObjectModel(BaseModel):
    label: str
    volume_m3: float
    num_points: int
    north_m: float
    east_m: float


class SegResultModel(BaseModel):
    counts: dict[str, int]
    objects: list[SegObjectModel]
    cloud_url: str  # class-coloured cloud for the 3D viewer
    up_vector: list[float] | None


class SegJobResponse(BaseModel):
    job_id: str
    status: str
    progress: str | None
    error: str | None
    result: SegResultModel | None


def _job_response(job: Job) -> SegJobResponse:
    return SegJobResponse(
        job_id=job.id,
        status=job.status.value,
        progress=job.progress,
        error=job.error,
        result=SegResultModel(**job.result) if job.result else None,
    )


@router.post("/jobs", response_model=SegJobResponse, status_code=202)
def start_segmentation() -> SegJobResponse:
    """Segment the current reconstruction into trees/roofs (background job)."""
    try:
        cloud = find_point_cloud(settings.opensfm_project_dir)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="no reconstruction yet — run a reconstruction first"
        ) from exc

    def run(job: Job) -> dict[str, Any]:
        def progress(phase: str) -> None:
            job.progress = phase

        data = run_segmentation_isolated(cloud, on_progress=progress)
        return {
            "counts": data["counts"],
            "objects": data["objects"],
            "cloud_url": "/volume/files/segmented.ply",
            "up_vector": data["up_vector"],
        }

    job = job_manager.submit(kind="segmentation", params={}, fn=run)
    return _job_response(job)


@router.get("/jobs/{job_id}", response_model=SegJobResponse)
def get_segmentation_job(job_id: str) -> SegJobResponse:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job: {job_id}")
    return _job_response(job)
