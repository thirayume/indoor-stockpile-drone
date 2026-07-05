"""Manage ODM example datasets and stage them into the OpenSfM project.

The ODMdata submodule at data/odm/ is a catalog; actual images come from the
individual dataset repos it links to (e.g. dataset_banana), cloned into
data/odm/<name>/. A dataset is any folder there containing images, either in
an images/ subfolder or directly in the folder root.

CLI usage (from backend/, with the package installed or src/ on PYTHONPATH):
    python -m reconstruction.dataset_utils list
    python -m reconstruction.dataset_utils prepare banana [--copy]
"""

import os
import shutil
from pathlib import Path

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# Written to projects that have no config.yaml yet; mirrors the settings
# shipped in data/opensfm_project/config.yaml (GPS-denied indoor capture).
DEFAULT_CONFIG = """\
camera_projection_type: BROWN
feature_type: HAHOG
matcher_type: FLANN
matching_gps_distance: 0
matching_gps_neighbors: 0
align_method: naive
bundle_use_gps: no
bundle_use_gcp: no
depthmap_resolution: 640
depthmap_min_consistent_views: 3
"""


def find_images_dir(dataset_dir: Path) -> Path | None:
    """Return the folder holding a dataset's images, or None if it has none."""
    for candidate in (dataset_dir / "images", dataset_dir):
        if candidate.is_dir() and any(
            p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
            for p in candidate.iterdir()
        ):
            return candidate
    return None


def list_odm_datasets(odm_dir: Path | None = None) -> list[str]:
    """List dataset folders under data/odm/ that actually contain images."""
    root = odm_dir or settings.odm_datasets_dir
    if not root.is_dir():
        return []
    return sorted(
        d.name
        for d in root.iterdir()
        if d.is_dir() and not d.name.startswith(".") and find_images_dir(d) is not None
    )


def prepare_opensfm_project(
    dataset_id: str,
    odm_dir: Path | None = None,
    project_dir: Path | None = None,
    use_symlink: bool = True,
) -> None:
    """Stage a dataset into the OpenSfM project (config.yaml + images/).

    Validates the dataset exists under data/odm, ensures the project skeleton
    exists, then links or copies the images and logs the now-active dataset.
    """
    root = odm_dir or settings.odm_datasets_dir
    available = list_odm_datasets(root)
    if dataset_id not in available:
        raise FileNotFoundError(
            f"dataset {dataset_id!r} not found under {root} "
            f"(available: {', '.join(available) or 'none'})"
        )

    project = project_dir or settings.opensfm_project_dir
    project.mkdir(parents=True, exist_ok=True)
    config = project / "config.yaml"
    if not config.exists():
        config.write_text(DEFAULT_CONFIG)
        logger.info("Wrote default config.yaml to %s", config)

    # OpenSfM treats the mere existence of gcp_list.txt as "GCPs provided"
    # and crashes parsing an empty one (StopIteration on the projection
    # header) — drop empty leftovers.
    gcp = project / "gcp_list.txt"
    if gcp.is_file() and not gcp.read_text(encoding="utf-8").strip():
        gcp.unlink()
        logger.warning("Removed empty %s — OpenSfM cannot parse an empty GCP file", gcp)

    images = prepare_opensfm_images(
        dataset_id, odm_dir=root, project_dir=project, use_symlink=use_symlink
    )
    logger.info("Active dataset: %s (images at %s)", dataset_id, images)


def prepare_opensfm_images(
    dataset_id: str,
    odm_dir: Path | None = None,
    project_dir: Path | None = None,
    use_symlink: bool = True,
) -> Path:
    """Make a dataset's images available at <project>/images/ (symlink or copy).

    Symlinking is the default (no disk duplication); on Windows it requires
    Developer Mode or admin rights, so we fall back to copying if it fails.
    """
    root = odm_dir or settings.odm_datasets_dir
    project = project_dir or settings.opensfm_project_dir
    src = find_images_dir(root / dataset_id)
    if src is None:
        raise FileNotFoundError(
            f"dataset {dataset_id!r} not found or has no images under {root}"
        )

    dst = project / "images"
    _remove_existing(dst)

    if use_symlink:
        # Relative target so the link still resolves when data/ is bind-mounted
        # elsewhere (e.g. /data inside the backend container).
        target = Path(os.path.relpath(src, dst.parent))
        try:
            dst.symlink_to(target, target_is_directory=True)
            logger.info("Symlinked %s -> %s", dst, target)
            return dst
        except OSError as exc:
            logger.warning("Symlink failed (%s); copying instead", exc)

    dst.mkdir(parents=True)
    count = 0
    for image in sorted(src.iterdir()):
        if image.is_file() and image.suffix.lower() in IMAGE_EXTENSIONS:
            shutil.copy2(image, dst / image.name)
            count += 1
    logger.info("Copied %d images from %s to %s", count, src, dst)
    return dst


def _remove_existing(dst: Path) -> None:
    if dst.is_symlink():
        dst.unlink()
    elif dst.is_dir():
        shutil.rmtree(dst)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list available datasets")
    prep = sub.add_parser("prepare", help="stage a dataset into the OpenSfM project")
    prep.add_argument("dataset_id")
    prep.add_argument("--copy", action="store_true", help="copy files instead of symlinking")
    args = parser.parse_args()

    if args.command == "list":
        for name in list_odm_datasets():
            print(name)
    else:
        prepare_opensfm_project(args.dataset_id, use_symlink=not args.copy)
        print(f"prepared OpenSfM project for {args.dataset_id!r}")
