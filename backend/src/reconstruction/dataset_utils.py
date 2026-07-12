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

_CONFIG_COMMON = """\
camera_projection_type: BROWN
feature_type: HAHOG
matcher_type: FLANN
bundle_use_gcp: no
depthmap_resolution: 640
depthmap_min_consistent_views: 3
"""

# GPS-denied (the indoor default): never use GPS for pair selection or
# alignment. The reconstruction is up to scale (results in model units).
_CONFIG_NO_GPS = """\
matching_gps_distance: 0
matching_gps_neighbors: 0
align_method: naive
bundle_use_gps: no
"""

# GPS-enabled: use EXIF GPS to preselect image pairs and to align/scale the
# reconstruction, giving georeferenced, true-metre results. Only useful when
# the images actually carry GPS in EXIF (e.g. brighton_beach; not banana).
_CONFIG_GPS = """\
use_altitude_tag: yes
matching_gps_neighbors: 8
align_method: auto
bundle_use_gps: yes
"""


def opensfm_config(use_exif_gps: bool = False) -> str:
    """OpenSfM config.yaml text, GPS-denied by default (the indoor case)."""
    return _CONFIG_COMMON + (_CONFIG_GPS if use_exif_gps else _CONFIG_NO_GPS)


def find_images_dir(dataset_dir: Path) -> Path | None:
    """Return the folder holding a dataset's images, or None if it has none."""
    for candidate in (dataset_dir / "images", dataset_dir):
        if candidate.is_dir() and any(
            p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
            for p in candidate.iterdir()
        ):
            return candidate
    return None


def dataset_image_names(dataset_id: str, odm_dir: Path | None = None) -> list[str]:
    """Sorted image filenames for a dataset (empty if it has none)."""
    root = odm_dir or settings.odm_datasets_dir
    images_dir = find_images_dir(root / dataset_id)
    if images_dir is None:
        return []
    return sorted(
        p.name
        for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


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
    use_exif_gps: bool = False,
) -> None:
    """Stage a dataset into the OpenSfM project (config.yaml + images/).

    Validates the dataset exists under data/odm, writes the OpenSfM config
    for the chosen GPS mode, then links or copies the images. use_exif_gps
    only helps when the dataset's photos actually carry GPS in EXIF.
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

    # OpenSfM caches per-image outputs (features, matches, depthmaps) and
    # silently reuses them. After switching dataset or GPS mode those caches
    # are stale — e.g. depthmaps from a GPS-aligned run get merged into a
    # reconstruction computed in a completely different (GPS-denied) frame,
    # producing a merged.ply that no longer matches reconstruction.json.
    # Wipe every derived output whenever the config or the image set changes;
    # identical re-runs keep the cache and stay fast.
    config = project / "config.yaml"
    config_text = opensfm_config(use_exif_gps)
    old_config = config.read_text() if config.is_file() else None
    if old_config != config_text or _staged_image_names(project) != set(
        dataset_image_names(dataset_id, root)
    ):
        _clean_derived_outputs(project)

    config.write_text(config_text)
    logger.info("Wrote config.yaml (use_exif_gps=%s) to %s", use_exif_gps, config)

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


def _staged_image_names(project: Path) -> set[str]:
    """Names of the images currently staged at <project>/images/."""
    images = project / "images"
    if not images.is_dir():
        return set()
    return {
        p.name
        for p in images.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    }


# Everything OpenSfM (or our pipeline) derives from images/ + config.yaml.
_DERIVED_DIRS = ("exif", "features", "matches", "reports", "undistorted")
_DERIVED_FILES = (
    "camera_models.json",
    "profile.log",
    "reconstruction.json",
    "reconstruction.meshed.json",
    "reconstruction.ply",
    "reference_lla.json",
    "tracks.csv",
)


def _clean_derived_outputs(project: Path) -> None:
    """Remove cached OpenSfM outputs so the next run starts from the images."""
    removed = []
    for name in _DERIVED_DIRS:
        path = project / name
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(name)
    for name in _DERIVED_FILES:
        path = project / name
        if path.is_file():
            path.unlink()
            removed.append(name)
    if removed:
        logger.info("Config/dataset changed - cleared stale outputs: %s", ", ".join(removed))


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
