"""ML scene segmentation: open-vocabulary 2D masks voted onto the 3D cloud.

Complements the heuristic mode in segmentation.py with a model that finds
arbitrary object classes in the photos themselves:

1. Load + clean the reconstruction cloud and RANSAC the floor plane (same
   helpers as the heuristic mode; the plane drives volumes + the upright
   3D view).
2. Run YOLOE instance segmentation over every photo that has a camera pose.
   An empty prompt list uses the prompt-free model with its built-in ~4.6k
   class vocabulary (auto-detect); a non-empty list uses text prompts
   (e.g. "pile of sand", "pond") for domain-specific classes.
3. Collapse each photo's detections into a class/confidence map, project
   every 3D point into the photo (OpenSfM pose, same projection as the
   photo overlays) and accumulate confidence-weighted votes per point.
4. A point's label is the class with the highest vote sum, if that sum is
   both large enough and a clear majority; everything else is "other".
   Voting across many photos filters out single-image false positives.
5. Instances come from 3D DBSCAN clustering per class — the same car seen
   in 30 photos is still ONE car — and volumes from the shared 2.5D grid.

Outputs (labels.npz, per-class clouds, seg_classes.json) are shaped exactly
like the heuristic mode's, so the 3D / ortho / photo views work unchanged.

ultralytics (torch) is imported lazily: the module loads fine without the
optional [ml] extra and only the actual ML run reports the install hint.
"""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import open3d as o3d

from core.config import settings
from core.logging import get_logger
from reconstruction.overlay import _ensure_same_frame, _load_reconstruction, _project
from reconstruction.segmentation import (
    MIN_CLUSTER_POINTS,
    SegmentationResult,
    SegObject,
    _cluster_volume,
    _params,
    _write_class_clouds,
    class_color,
    is_object_class,
    write_class_registry,
)
from reconstruction.volume_compute import (
    _bbox_diagonal,
    load_point_cloud,
    segment_floor,
)

logger = get_logger(__name__)

# A point is labelled when its best class collected at least this much
# summed confidence (~two sightings at the default 0.25 threshold)...
MIN_VOTE_SCORE = 0.5
# ...and that class won a clear majority of the point's total votes.
MIN_VOTE_SHARE = 0.5
# Keep the UI legend manageable: strongest classes by vote mass, rest -> other.
MAX_CLASSES = 29

# Resolution of the combined per-photo detection map (long side, pixels).
WORK_LONG_SIDE = 2048
# Fraction of a tile shared with its neighbour, so objects on tile borders
# are fully visible in at least one tile.
TILE_OVERLAP = 0.15

INSTALL_HINT = (
    "ML segmentation needs the optional ML dependencies (ultralytics/torch). "
    "Install with: pip install -e '.[ml]' in backend/, or rebuild the Docker "
    "image with INSTALL_ML=true."
)


@dataclass
class InferenceMaps:
    """One photo's detections, collapsed to dense maps in "map space"."""

    class_map: np.ndarray  # (mh, mw) int32, -1 = no detection
    conf_map: np.ndarray  # (mh, mw) float32
    id_to_name: dict[int, str]
    gain: float  # original pixel coords * gain + pad = map coords
    pad: tuple[float, float]  # (pad_x, pad_y)


# An inference callable: photo path -> InferenceMaps or None (no detections).
InferFn = Callable[[Path], InferenceMaps | None]


def _tile_boxes(w: int, h: int, tiles: int, overlap: float) -> list[tuple[int, int, int, int]]:
    """tiles x tiles crop boxes covering (w, h) with the given overlap."""
    n = max(1, tiles)
    if n == 1:
        return [(0, 0, w, h)]

    def edges(size: int) -> list[tuple[int, int]]:
        span = size / (1 + (n - 1) * (1 - overlap))  # tile side incl. overlap
        step = span * (1 - overlap)
        return [(round(i * step), min(size, round(i * step + span))) for i in range(n)]

    return [(x0, y0, x1, y1) for y0, y1 in edges(h) for x0, x1 in edges(w)]


def _slug(name: str) -> str:
    """Class name -> key safe for filenames, URLs and the CSV query param.

    "pile of sand" -> "pile_of_sand". Registry keys, seg_<key>.ply and
    ortho_<key>.png all use the slug; the UI prettifies it for display.
    """
    return re.sub(r"[^a-z0-9_-]+", "_", name.strip().lower()).strip("_") or "unknown"


class YoloeInference:
    """Wraps a YOLOE model as an InferFn. Weights download on first use."""

    def __init__(self, class_prompts: list[str] | None = None) -> None:
        try:
            import torch
            from ultralytics import YOLOE
        except ImportError as exc:
            raise ValueError(INSTALL_HINT) from exc

        models_dir = settings.ml_models_path
        try:
            models_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(
                f"cannot create the ML models dir {models_dir} (read-only data "
                f"mount? use the OpenSfM overlay compose file): {exc}"
            ) from exc
        # ultralytics side-downloads (the text encoder for prompts) land in
        # the CWD; we run in a worker subprocess, so chdir is safe here.
        os.chdir(models_dir)

        name = settings.ml_model
        if not class_prompts:
            # Prompt-free variant: built-in vocabulary, no text encoder.
            name = name.replace("-seg", "-seg-pf")
        logger.info("Loading YOLOE model %s (prompts=%s)", name, class_prompts or "auto")
        self.model = YOLOE(str(models_dir / name))
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if class_prompts:
            self.model.set_classes(class_prompts, self.model.get_text_pe(class_prompts))

    def __call__(self, image_path: Path) -> InferenceMaps | None:
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        w0, h0 = image.size
        # Working resolution of the combined detection map: high enough that
        # tile masks keep their shape, small enough to stay cheap.
        scale = min(1.0, WORK_LONG_SIDE / max(w0, h0))
        map_w, map_h = max(1, round(w0 * scale)), max(1, round(h0 * scale))
        class_map = np.full((map_h, map_w), -1, dtype=np.int32)
        conf_map = np.zeros((map_h, map_w), dtype=np.float32)
        id_to_name: dict[int, str] = {}

        # Nadir aerial objects are tiny at model resolution, so run the model
        # per overlapping tile (each tile gets the full inference size).
        for x0, y0, x1, y1 in _tile_boxes(w0, h0, settings.ml_tiles, TILE_OVERLAP):
            # Pre-resize the crop to the inference size ourselves: the model
            # sees the same pixels, and retina_masks then returns masks at
            # this small size (no letterbox maths, no huge full-res masks).
            crop_w, crop_h = x1 - x0, y1 - y0
            inf_scale = settings.ml_image_size / max(crop_w, crop_h)
            crop = image.crop((x0, y0, x1, y1)).resize(
                (max(1, round(crop_w * inf_scale)), max(1, round(crop_h * inf_scale))),
                Image.BILINEAR,
            )
            result = self.model.predict(
                np.asarray(crop)[:, :, ::-1],  # ultralytics ndarray input is BGR
                conf=settings.ml_confidence,
                imgsz=settings.ml_image_size,
                device=self.device,
                verbose=False,
                retina_masks=True,
                max_det=100,
            )[0]
            if result.masks is None or len(result.masks.data) == 0:
                continue
            id_to_name.update({int(k): str(v) for k, v in result.names.items()})

            masks = result.masks.data.cpu().numpy()  # (n, crop_h', crop_w')
            confs = result.boxes.conf.cpu().numpy()
            cls_ids = result.boxes.cls.cpu().numpy().astype(int)

            # Paint into the tile's region of the working map; the strongest
            # detection wins each pixel, also across overlapping tiles.
            rx0, ry0 = round(x0 * scale), round(y0 * scale)
            rx1, ry1 = min(map_w, round(x1 * scale)), min(map_h, round(y1 * scale))
            rw, rh = rx1 - rx0, ry1 - ry0
            if rw <= 0 or rh <= 0:
                continue
            region_cls = class_map[ry0:ry1, rx0:rx1]
            region_conf = conf_map[ry0:ry1, rx0:rx1]
            for i in np.argsort(confs):
                mask = np.asarray(
                    Image.fromarray((masks[i] > 0.5).astype(np.uint8) * 255).resize(
                        (rw, rh), Image.NEAREST
                    )
                ) > 0
                paint = mask & (confs[i] >= region_conf)
                region_cls[paint] = cls_ids[i]
                region_conf[paint] = confs[i]

        if not id_to_name or not (class_map >= 0).any():
            return None
        return InferenceMaps(class_map, conf_map, id_to_name, float(scale), (0.0, 0.0))


def _vote_labels(
    pts: np.ndarray,
    shots: dict,
    cameras: dict,
    images_dir: Path,
    infer: InferFn,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, np.ndarray]:
    """Per-class summed confidence votes for every point, across all photos."""
    votes: dict[str, np.ndarray] = {}
    names = sorted(shots)
    for i, name in enumerate(names, start=1):
        if on_progress is not None:
            on_progress(f"ML 3/6: detecting objects in photos ({i}/{len(names)})")
        photo = images_dir / name
        if not photo.is_file():
            logger.warning("Photo %s missing on disk; skipping", name)
            continue
        maps = infer(photo)
        if maps is None:
            continue

        shot = shots[name]
        camera = cameras[shot["camera"]]
        pix, in_front = _project(pts, shot, camera)
        with np.errstate(invalid="ignore"):
            pix = np.nan_to_num(pix, nan=-1e9, posinf=1e9, neginf=-1e9)
        mx = (pix[:, 0] * maps.gain + maps.pad[0]).astype(np.int32)
        my = (pix[:, 1] * maps.gain + maps.pad[1]).astype(np.int32)
        mh, mw = maps.class_map.shape
        ok = in_front & (mx >= 0) & (mx < mw) & (my >= 0) & (my < mh)
        if not ok.any():
            continue

        point_idx = np.where(ok)[0]
        cls = maps.class_map[my[ok], mx[ok]]
        conf = maps.conf_map[my[ok], mx[ok]]
        hit = cls >= 0
        for cid in np.unique(cls[hit]):
            key = _slug(maps.id_to_name.get(int(cid), f"class_{cid}"))
            arr = votes.get(key)
            if arr is None:
                arr = votes[key] = np.zeros(len(pts), dtype=np.float32)
            sel = hit & (cls == cid)
            arr[point_idx[sel]] += conf[sel]
    return votes


def _labels_from_votes(
    votes: dict[str, np.ndarray], num_points: int
) -> tuple[np.ndarray, list[str]]:
    """(per-point label ids, class list ending in "other") from the vote sums."""
    # Strongest classes by total vote mass; the rest fold into "other".
    ranked = sorted(votes, key=lambda k: -float(votes[k].sum()))
    kept = [k for k in ranked[:MAX_CLASSES] if k != "other"]
    classes = [*kept, "other"]
    other_id = len(classes) - 1

    labels = np.full(num_points, other_id, dtype=np.uint8)
    if kept:
        stack = np.stack([votes[k] for k in kept])  # (C, N)
        best = stack.argmax(axis=0)
        best_score = stack.max(axis=0)
        total = stack.sum(axis=0)
        confident = (best_score >= MIN_VOTE_SCORE) & (best_score >= MIN_VOTE_SHARE * total)
        labels[confident] = best[confident].astype(np.uint8)
    return _drop_sparse_classes(labels, classes, MIN_CLUSTER_POINTS)


def _drop_sparse_classes(
    labels: np.ndarray, classes: list[str], min_points: int
) -> tuple[np.ndarray, list[str]]:
    """Fold classes with fewer than min_points labelled points into "other".

    Stray single-mask detections otherwise clutter the legend with 5-point
    classes that are invisible in every view anyway.
    """
    counts = np.bincount(labels, minlength=len(classes))
    kept = [k for i, k in enumerate(classes) if k != "other" and counts[i] >= min_points]
    new_classes = [*kept, "other"]
    remap = np.full(len(classes), len(new_classes) - 1, dtype=np.uint8)
    for i, k in enumerate(classes):
        if k in kept:
            remap[i] = kept.index(k)
    return remap[labels], new_classes


def segment_scene_ml(
    ply_path: Path,
    project_dir: Path | None = None,
    output_dir: Path | None = None,
    class_prompts: list[str] | None = None,
    on_progress: Callable[[str], None] | None = None,
    infer: InferFn | None = None,
) -> SegmentationResult:
    """Full ML pipeline; `infer` is injectable for tests (defaults to YOLOE)."""

    def report(phase: str) -> None:
        if on_progress is not None:
            on_progress(phase)

    project = project_dir or settings.opensfm_project_dir
    out_dir = output_dir or ply_path.parent

    report("ML 1/6: loading + cleaning point cloud")
    pcd = load_point_cloud(ply_path)
    if not pcd.has_colors():
        raise ValueError("point cloud has no colour — cannot write view overlays")
    pts = np.asarray(pcd.points)
    cols = np.asarray(pcd.colors)
    scale = _bbox_diagonal(pcd)
    p = _params(scale)

    report("ML 2/6: finding the ground plane")
    plane, _ = segment_floor(pcd, distance_threshold=0.005 * scale)

    recon = _load_reconstruction(project)
    shots, cameras = recon["shots"], recon["cameras"]
    if not shots:
        raise ValueError("reconstruction has no posed photos")
    _ensure_same_frame(pts, shots)

    if infer is None:
        report("ML 3/6: loading the model (first run downloads weights)")
        infer = YoloeInference(class_prompts)
    votes = _vote_labels(pts, shots, cameras, project / "images", infer, on_progress)
    if not votes:
        raise ValueError(
            "the model detected nothing in any photo — try custom class prompts "
            "or the geometry mode"
        )

    report("ML 4/6: voting labels onto the 3D points")
    labels, classes = _labels_from_votes(votes, len(pts))
    colors = {k: class_color(k, i) for i, k in enumerate(classes)}

    report("ML 5/6: counting objects + measuring volumes")
    objects: list[SegObject] = []
    counts: dict[str, int] = {}
    cell = 0.01 * scale
    for cid, key in enumerate(classes):
        if key == "other" or not is_object_class(key):
            continue
        counts[key] = 0
        idx = np.where(labels == cid)[0]
        if len(idx) < MIN_CLUSTER_POINTS:
            continue
        sub = o3d.geometry.PointCloud()
        sub.points = o3d.utility.Vector3dVector(pts[idx])
        clusters = np.asarray(sub.cluster_dbscan(eps=p["cluster_eps"], min_points=8))
        for lab in range(clusters.max() + 1):
            members = idx[clusters == lab]
            if len(members) < MIN_CLUSTER_POINTS:
                continue
            cpts = pts[members]
            centroid = cpts.mean(axis=0)
            counts[key] += 1
            objects.append(
                SegObject(
                    label=key,
                    volume_m3=_cluster_volume(cpts, plane, cell),
                    num_points=len(members),
                    north_m=float(centroid[0]),
                    east_m=float(centroid[1]),
                )
            )

    report("ML 6/6: writing class clouds + labels")
    point_counts = {k: int((labels == i).sum()) for i, k in enumerate(classes)}
    cloud_path, class_paths = _write_class_clouds(pts, labels, out_dir, classes, colors)
    write_class_registry(out_dir, classes, colors)
    labels_path = out_dir / "labels.npz"
    np.savez_compressed(
        labels_path,
        points=pts.astype(np.float32),
        colors=(cols * 255).astype(np.uint8),
        labels=labels,
        plane=plane.astype(np.float64),
        classes=np.array(classes),
    )
    logger.info("ML segmentation: %s from %d objects", counts, len(objects))
    return SegmentationResult(
        counts=counts,
        objects=objects,
        point_counts=point_counts,
        cloud_path=cloud_path,
        labels_path=labels_path,
        class_cloud_paths=class_paths,
        up_vector=(float(plane[0]), float(plane[1]), float(plane[2])),
        classes=tuple(classes),
        colors=colors,
    )
