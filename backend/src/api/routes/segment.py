from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.config import settings
from core.jobs import Job, job_manager
from core.logging import get_logger
from reconstruction.opensfm_runner import find_point_cloud
from reconstruction.overlay import (
    list_shot_images,
    render_ortho,
    render_photo_mosaic,
    render_photo_overlay_cached,
)
from reconstruction.pipeline import run_segmentation_isolated
from reconstruction.segmentation import CLASS_COLORS, CLASSES, OBJECT_CLASSES

logger = get_logger(__name__)

router = APIRouter(prefix="/segment", tags=["segmentation"])


def _hex(color: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{int(c * 255):02x}" for c in color)


class SegObjectModel(BaseModel):
    label: str
    volume_m3: float
    num_points: int
    north_m: float
    east_m: float


class SegClassModel(BaseModel):
    key: str
    color: str  # CSS hex, same colour in 3D / ortho / photo overlays
    point_count: int
    object_count: int | None  # None for surface classes (ground, road)
    total_volume_m3: float | None
    cloud_url: str | None  # per-class point cloud for the 3D layer toggle
    ortho_overlay_url: str | None


class SegResultModel(BaseModel):
    counts: dict[str, int]
    objects: list[SegObjectModel]
    classes: list[SegClassModel]
    cloud_url: str  # combined class-coloured cloud
    ortho_url: str | None  # top-down point render
    ortho_photo_url: str | None  # true photo mosaic (all photos merged into one)
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


def _output_dir() -> Path:
    """Where segmentation artefacts live: next to the reconstruction cloud."""
    return find_point_cloud(settings.opensfm_project_dir).parent


@router.post("/jobs", response_model=SegJobResponse, status_code=202)
def start_segmentation() -> SegJobResponse:
    """Segment the current reconstruction into classes (background job)."""
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

        job.progress = "rendering top-down overlays"
        labels_path = Path(data["labels_path"])
        ortho_files = render_ortho(labels_path, labels_path.parent, CLASS_COLORS)

        # Merge every photo into one seamless top-down image. Best-effort:
        # the mosaic needs photo files + poses, and its absence should not
        # fail the whole segmentation.
        job.progress = "merging photos into one mosaic"
        ortho_photo_url = None
        try:
            mosaic = render_photo_mosaic(
                labels_path,
                settings.opensfm_project_dir,
                labels_path.parent,
                on_progress=progress,
            )
            ortho_photo_url = f"/segment/ortho/{mosaic}"
        except Exception:
            logger.exception("photo mosaic failed; continuing without it")

        objects = data["objects"]
        point_counts: dict[str, int] = data.get("point_counts", {})
        classes = []
        for key in CLASSES:
            points = point_counts.get(key, 0)
            if points == 0:
                continue
            is_object = key in OBJECT_CLASSES
            classes.append(
                {
                    "key": key,
                    "color": _hex(CLASS_COLORS[key]),
                    "point_count": points,
                    "object_count": data["counts"].get(key) if is_object else None,
                    "total_volume_m3": (
                        sum(o["volume_m3"] for o in objects if o["label"] == key)
                        if is_object
                        else None
                    ),
                    "cloud_url": (
                        f"/volume/files/seg_{key}.ply" if key in data["class_clouds"] else None
                    ),
                    "ortho_overlay_url": (
                        f"/segment/ortho/{ortho_files[key]}" if key in ortho_files else None
                    ),
                }
            )
        return {
            "counts": data["counts"],
            "objects": objects,
            "classes": classes,
            "cloud_url": "/volume/files/segmented.ply",
            "ortho_url": f"/segment/ortho/{ortho_files['base']}",
            "ortho_photo_url": ortho_photo_url,
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


@router.get("/ortho/{filename}")
def download_ortho(filename: str) -> FileResponse:
    """Top-down render (base or one class overlay) written by the last job."""
    allowed = {"ortho_base.png", "ortho_photo.png"} | {f"ortho_{k}.png" for k in CLASSES}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail=f"unknown file: {filename}")
    path = _output_dir() / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not rendered yet — run segmentation first")
    return FileResponse(path, media_type="image/png")


@router.get("/photos")
def overlay_photos() -> dict[str, list[str]]:
    """Photos with a camera pose — each can show a segmentation overlay."""
    try:
        return {"images": list_shot_images(settings.opensfm_project_dir)}
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="no reconstruction yet — run a reconstruction first"
        ) from exc


@router.get("/photo/{image_name}")
def photo_overlay(
    image_name: str,
    classes: str = Query(default="", description="CSV of class keys to draw"),
    width: int = Query(default=1200, ge=200, le=2000),
) -> FileResponse:
    """One original photo with the selected classes projected onto it."""
    project = settings.opensfm_project_dir
    try:
        if image_name not in list_shot_images(project):
            raise HTTPException(status_code=404, detail=f"no pose for image: {image_name}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no reconstruction yet") from exc

    labels_path = _output_dir() / "labels.npz"
    if not labels_path.is_file():
        raise HTTPException(status_code=404, detail="run segmentation first")

    keys = [k for k in classes.split(",") if k]
    unknown = [k for k in keys if k not in CLASSES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown classes: {unknown}")
    class_ids = [CLASSES.index(k) for k in keys]
    colors_by_id = [CLASS_COLORS[k] for k in CLASSES]

    path = render_photo_overlay_cached(
        labels_path=labels_path,
        project_dir=project,
        cache_dir=labels_path.parent / "seg_photo_cache",
        image_name=image_name,
        class_ids=class_ids,
        class_colors_by_id=colors_by_id,
        width=width,
    )
    return FileResponse(path, media_type="image/jpeg")
