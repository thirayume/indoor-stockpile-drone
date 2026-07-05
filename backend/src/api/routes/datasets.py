import io

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.config import settings
from reconstruction.dataset_utils import IMAGE_EXTENSIONS, find_images_dir

router = APIRouter(prefix="/datasets", tags=["datasets"])

THUMBNAIL_MAX_WIDTH = 1024


class DatasetImagesResponse(BaseModel):
    dataset_id: str
    images: list[str]


def _image_files(dataset_id: str) -> dict[str, object]:
    """Name -> Path for a dataset's images; the whitelist for serving files."""
    images_dir = find_images_dir(settings.odm_datasets_dir / dataset_id)
    if images_dir is None:
        raise HTTPException(status_code=404, detail=f"unknown dataset: {dataset_id}")
    return {
        p.name: p
        for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    }


@router.get("/{dataset_id}/images", response_model=DatasetImagesResponse)
def list_images(dataset_id: str) -> DatasetImagesResponse:
    """Image filenames of a dataset, sorted."""
    return DatasetImagesResponse(dataset_id=dataset_id, images=sorted(_image_files(dataset_id)))


@router.get("/{dataset_id}/images/{name}")
def get_image(dataset_id: str, name: str, width: int | None = None) -> Response:
    """Serve one dataset image, optionally downscaled to `width` pixels.

    `name` is matched against the directory listing (a whitelist), so path
    traversal is impossible by construction.
    """
    src = _image_files(dataset_id).get(name)
    if src is None:
        raise HTTPException(status_code=404, detail=f"unknown image: {name}")

    if width is None:
        return FileResponse(src)

    from PIL import Image

    width = max(32, min(width, THUMBNAIL_MAX_WIDTH))
    with Image.open(src) as im:  # type: ignore[arg-type]
        im = im.convert("RGB")
        if width < im.width:
            im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
    return Response(content=buf.getvalue(), media_type="image/jpeg")
