"""Segment a reconstructed scene into semantic classes by geometry + colour.

Self-contained (NumPy + Open3D, no ML models). Classes:

- ground  vegetated / bare ground in the floor plane
- road    paved surface in the floor plane (grey: low colour saturation)
- tree    green (ExG) points above the ground
- roof    non-green cluster floating above the ground (walls are barely
          captured in nadir aerial shots, so buildings start well above 0)
- car     small, low, compact non-green cluster
- pile    non-green mound rising continuously from the ground — stockpiles
          of soil / sand / fertiliser / sacks all share this shape
- other   anything that fits none of the rules

Pipeline:
1. RANSAC the floor plane; per-point height above it.
2. Per-point cues: greenness ExG = 2G-R-B, colour saturation, normal
   verticality |n·up|.
3. Floor-band points -> ground / road by saturation; green points -> tree.
4. Remaining above-ground points are DBSCAN-clustered and each cluster is
   classified from its shape (height profile + footprint): car / roof / pile.
5. Count objects, per-object 2.5D grid volume, recolour the cloud by class,
   and save per-class clouds + a labels archive for the 2D/ortho overlays.

Thresholds are heuristics (tunable) — good enough to demonstrate
segment + count + measure, not a trained semantic model.
"""

import colorsys
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import open3d as o3d

from core.logging import get_logger
from reconstruction.volume_compute import (
    _bbox_diagonal,
    _plane_basis,
    load_point_cloud,
    segment_floor,
)

logger = get_logger(__name__)

# Class order is the label id used in labels.npz (index = id).
CLASSES = ("ground", "road", "tree", "roof", "car", "pile", "other")

# Class colours for the recoloured clouds and 2D overlays (RGB 0..1).
CLASS_COLORS: dict[str, tuple[float, float, float]] = {
    "ground": (0.60, 0.60, 0.60),
    "road": (0.15, 0.65, 0.90),
    "tree": (0.20, 0.72, 0.25),
    "roof": (0.95, 0.50, 0.15),
    "car": (0.90, 0.20, 0.75),
    "pile": (0.95, 0.85, 0.15),
    "other": (0.55, 0.45, 0.70),
}
# Object classes get counted + measured; surface classes are overlay-only.
OBJECT_CLASSES = ("tree", "roof", "car", "pile")


# ---------------------------------------------------------------------------
# Class registry: which classes the CURRENT segmentation output contains.
# The heuristic mode always uses the static CLASSES above; the ML mode
# (ml_segmentation.py) discovers its classes at runtime. Both write
# seg_classes.json next to labels.npz so the API serves whatever the latest
# run produced — same label-id order as the "classes" array in labels.npz.
# ---------------------------------------------------------------------------

REGISTRY_FILENAME = "seg_classes.json"

# Words that mark a class as a surface (overlay-only: no counting/volumes)...
_SURFACE_WORDS = {
    "ground", "road", "street", "path", "pavement", "sidewalk", "floor",
    "grass", "lawn", "field", "water", "pond", "lake", "river", "sea",
    "beach", "sand", "soil", "earth", "gravel", "sky", "wall", "fence",
    "other",
}
# ...but a pile/heap of a surface material ("pile of sand") is an object,
# and so are containers of one ("water tank").
_OBJECT_WORDS = {
    "pile", "heap", "mound", "stack", "stockpile", "bag", "sack",
    "tank", "container", "silo", "truck",
}


def is_object_class(key: str) -> bool:
    """Should this class be instance-counted and measured (vs overlay-only)?"""
    words = set(key.lower().replace("-", " ").replace("_", " ").split())
    if words & _OBJECT_WORDS:
        return True
    return not (words & _SURFACE_WORDS)


def class_color(key: str, index: int) -> tuple[float, float, float]:
    """Stable colour: the fixed palette for known keys, golden-angle otherwise.

    Keeping known keys (car, tree, road, ...) on the heuristic palette makes
    the two modes look consistent; unknown ML classes get well-separated hues
    deterministic in their registry position.
    """
    if key in CLASS_COLORS:
        return CLASS_COLORS[key]
    hue = (index * 0.61803398875) % 1.0
    return colorsys.hsv_to_rgb(hue, 0.75, 0.95)


def write_class_registry(
    output_dir: Path,
    classes: Sequence[str],
    colors: dict[str, tuple[float, float, float]],
) -> Path:
    """Persist the class list (in label-id order) with colours + object flags."""
    payload = {
        "classes": [
            {"key": k, "color": list(colors[k]), "is_object": is_object_class(k)}
            for k in classes
        ]
    }
    path = output_dir / REGISTRY_FILENAME
    path.write_text(json.dumps(payload, indent=1))
    return path


def load_class_registry(
    output_dir: Path,
) -> tuple[list[str], dict[str, tuple[float, float, float]], set[str]]:
    """(ordered class keys, colours, object-class keys) of the latest run.

    Falls back to the static heuristic classes when no registry exists
    (outputs from before the registry, or no segmentation yet).
    """
    path = output_dir / REGISTRY_FILENAME
    if not path.is_file():
        return list(CLASSES), dict(CLASS_COLORS), set(OBJECT_CLASSES)
    entries = json.loads(path.read_text())["classes"]
    classes = [str(e["key"]) for e in entries]
    colors = {str(e["key"]): tuple(float(c) for c in e["color"]) for e in entries}
    objects = {str(e["key"]) for e in entries if e["is_object"]}
    return classes, colors, objects

GREEN_EXG = 0.02  # per-point ExG above this -> vegetation
ROAD_SAT = 0.10  # saturation below this (and not green, not dark) -> paved
ROAD_MIN_VALUE = 0.25  # darker than this is shadow, not pavement
MIN_CLUSTER_POINTS = 30
ROOF_TOP_HEAVY = 0.50  # median/p98 height above this -> elevated slab (roof)
ROUGH_DOT = 0.55  # |normal · up| below this counts as a "rough" point
TREE_ROUGH_FRACTION = 0.45  # cluster rougher than this -> canopy (autumn trees)

# Geometric thresholds scale with the scene's bbox diagonal, but on large
# GPS-scaled scenes (hundreds of metres) pure relative values explode — a 7 m
# cluster eps merges whole street blocks and a 2 m ground band swallows every
# car. The clamps are sane absolute metres; small GPS-denied scenes (arbitrary
# model units, tiny diagonals) never reach them, so they keep pure relative
# behaviour.
def _params(scale: float) -> dict[str, float]:
    return {
        "ground_band": min(0.005 * scale, 0.6),  # within this of the floor -> ground/road
        "cluster_eps": min(0.015 * scale, 2.0),
        "tree_min_h": min(0.008 * scale, 1.0),  # green below this -> ground, not tree
        "car_max_h": min(0.012 * scale, 2.3),
        "car_max_fp": min(0.04 * scale, 8.0),  # footprint diagonal
        "low_max_h": min(0.02 * scale, 2.6),  # low + sprawling (fences, walls) -> other
    }


@dataclass
class SegObject:
    label: str  # one of OBJECT_CLASSES
    volume_m3: float
    num_points: int
    north_m: float
    east_m: float


@dataclass
class SegmentationResult:
    counts: dict[str, int]
    objects: list[SegObject]
    point_counts: dict[str, int]  # per-class point totals (incl. surface classes)
    cloud_path: Path
    labels_path: Path
    class_cloud_paths: dict[str, Path]
    up_vector: tuple[float, float, float]
    # Label-id order + colours of THIS run (ML runs discover them at runtime).
    classes: tuple[str, ...] = CLASSES
    colors: dict[str, tuple[float, float, float]] = field(
        default_factory=lambda: dict(CLASS_COLORS)
    )
    objects_total: int = field(init=False)

    def __post_init__(self) -> None:
        self.objects_total = len(self.objects)


def _cluster_volume(points: np.ndarray, plane: np.ndarray, cell_size: float) -> float:
    """2.5D grid volume of a point set above the floor plane.

    Cell means are clamped at zero: an ML-labelled cluster can sit below the
    RANSAC floor (e.g. water below a beach plane), and integrating negative
    heights would report a negative volume.
    """
    normal = plane[:3]
    heights = points @ normal + plane[3]
    u, v = _plane_basis(normal)
    uv = np.stack([points @ u, points @ v], axis=1)
    cells = np.floor((uv - uv.min(axis=0)) / cell_size).astype(np.int64)
    cell_ids = cells[:, 0] * (cells[:, 1].max() + 1) + cells[:, 1]
    _, inverse = np.unique(cell_ids, return_inverse=True)
    sums = np.bincount(inverse, weights=heights)
    counts = np.bincount(inverse)
    return float(cell_size**2 * np.sum(np.maximum(sums / counts, 0.0)))


def _classify_cluster(
    heights: np.ndarray, rough_frac: float, footprint_diag: float, p: dict[str, float]
) -> str:
    """Shape-based class of one non-green above-ground cluster.

    Cars are low and compact. A very rough surface (chaotic normals) is tree
    canopy that failed the greenness cue — autumn foliage. Low but sprawling
    clusters (fences, garden walls, terrain bumps) are "other". A building is
    top-heavy: nadir shots capture the roof slab densely and the walls barely,
    so most points sit near the cluster's top. A pile is a mound: surface area
    (and therefore points) concentrates near the bottom, rising gradually to
    a peak — and its surface is smooth, unlike canopy.
    """
    h_top = float(np.percentile(heights, 98))  # robust to stray high points
    if h_top < p["car_max_h"] and footprint_diag < p["car_max_fp"]:
        return "car"
    if rough_frac > TREE_ROUGH_FRACTION:
        return "tree"
    if h_top < p["low_max_h"]:
        return "other"
    if float(np.median(heights)) > ROOF_TOP_HEAVY * h_top:
        return "roof"
    return "pile"


def segment_scene(
    ply_path: Path,
    output_dir: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> SegmentationResult:
    def report(phase: str) -> None:
        if on_progress is not None:
            on_progress(phase)

    report("segment 1/6: loading + cleaning point cloud")
    pcd = load_point_cloud(ply_path)
    if not pcd.has_colors():
        raise ValueError("point cloud has no colour — colour cues are required")
    scale = _bbox_diagonal(pcd)
    out_dir = output_dir or ply_path.parent

    p = _params(scale)

    report("segment 2/6: finding the ground plane")
    # RANSAC fitting distance stays relative (robust plane on any scale);
    # the classification band is the clamped one.
    plane, _ = segment_floor(pcd, distance_threshold=0.005 * scale)
    up = plane[:3]

    report("segment 3/6: per-point colour cues")
    pts = np.asarray(pcd.points)
    cols = np.asarray(pcd.colors)
    heights = pts @ up + plane[3]
    exg = 2 * cols[:, 1] - cols[:, 0] - cols[:, 2]
    c_max = cols.max(axis=1)
    saturation = (c_max - cols.min(axis=1)) / np.maximum(c_max, 1e-6)

    labels = np.full(len(pts), CLASSES.index("other"), dtype=np.uint8)
    in_floor = heights <= p["ground_band"]
    is_green = exg > GREEN_EXG
    labels[in_floor] = CLASSES.index("ground")
    labels[in_floor & ~is_green & (saturation < ROAD_SAT) & (c_max > ROAD_MIN_VALUE)] = (
        CLASSES.index("road")
    )
    labels[~in_floor & is_green] = CLASSES.index("tree")
    # Low vegetation (lawns, shrubs below tree height) is ground, not trees.
    labels[~in_floor & is_green & (heights < p["tree_min_h"])] = CLASSES.index("ground")

    # Non-green points above the floor: cluster, then classify each cluster
    # by shape. (Per-cluster is safe here because trees — the class that
    # merges into everything — were already removed by the colour cue.)
    report("segment 4/6: clustering candidate objects")
    objects: list[SegObject] = []
    cell = 0.01 * scale
    candidate_idx = np.where(~in_floor & ~is_green)[0]
    if len(candidate_idx) >= MIN_CLUSTER_POINTS:
        sub = pcd.select_by_index(candidate_idx)
        # Surface roughness (per-point normal verticality) separates canopy
        # from smooth built/piled surfaces; only needed for the candidates.
        sub.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(
                radius=2.5 * p["cluster_eps"], max_nn=30
            )
        )
        rough = np.abs(np.asarray(sub.normals) @ up) < ROUGH_DOT
        clusters = np.asarray(sub.cluster_dbscan(eps=p["cluster_eps"], min_points=8))
        u_ax, v_ax = _plane_basis(up)
        for lab in range(clusters.max() + 1):
            in_cluster = clusters == lab
            members = candidate_idx[in_cluster]
            if len(members) < MIN_CLUSTER_POINTS:
                continue
            cpts = pts[members]
            uv = np.stack([cpts @ u_ax, cpts @ v_ax], axis=1)
            footprint_diag = float(np.linalg.norm(uv.max(axis=0) - uv.min(axis=0)))
            klass = _classify_cluster(
                heights[members], float(rough[in_cluster].mean()), footprint_diag, p
            )
            labels[members] = CLASSES.index(klass)
            # Trees rescued here are counted in the tree pass below; "other"
            # is never an object.
            if klass not in OBJECT_CLASSES or klass == "tree":
                continue
            centroid = cpts.mean(axis=0)
            objects.append(
                SegObject(
                    label=klass,
                    volume_m3=_cluster_volume(cpts, plane, cell),
                    num_points=len(members),
                    north_m=float(centroid[0]),
                    east_m=float(centroid[1]),
                )
            )

    # Count green clusters as individual trees too.
    report("segment 5/6: counting trees")
    tree_idx = np.where(labels == CLASSES.index("tree"))[0]
    if len(tree_idx) >= MIN_CLUSTER_POINTS:
        sub = pcd.select_by_index(tree_idx)
        clusters = np.asarray(sub.cluster_dbscan(eps=p["cluster_eps"], min_points=8))
        for lab in range(clusters.max() + 1):
            members = tree_idx[clusters == lab]
            if len(members) < MIN_CLUSTER_POINTS:
                continue
            cpts = pts[members]
            centroid = cpts.mean(axis=0)
            objects.append(
                SegObject(
                    label="tree",
                    volume_m3=_cluster_volume(cpts, plane, cell),
                    num_points=len(members),
                    north_m=float(centroid[0]),
                    east_m=float(centroid[1]),
                )
            )

    report("segment 6/6: writing class clouds + labels")
    counts = {k: sum(o.label == k for o in objects) for k in OBJECT_CLASSES}
    point_counts = {k: int((labels == i).sum()) for i, k in enumerate(CLASSES)}
    cloud_path, class_paths = _write_class_clouds(pts, labels, out_dir)
    write_class_registry(out_dir, CLASSES, CLASS_COLORS)
    labels_path = out_dir / "labels.npz"
    np.savez_compressed(
        labels_path,
        points=pts.astype(np.float32),
        colors=(cols * 255).astype(np.uint8),
        labels=labels,
        plane=plane.astype(np.float64),
        classes=np.array(CLASSES),
    )
    logger.info("Segmented scene: %s from %d objects", counts, len(objects))
    return SegmentationResult(
        counts=counts,
        objects=objects,
        point_counts=point_counts,
        cloud_path=cloud_path,
        labels_path=labels_path,
        class_cloud_paths=class_paths,
        up_vector=(float(plane[0]), float(plane[1]), float(plane[2])),
    )


def _write_class_clouds(
    pts: np.ndarray,
    labels: np.ndarray,
    output_dir: Path,
    classes: Sequence[str] = CLASSES,
    class_colors: dict[str, tuple[float, float, float]] | None = None,
) -> tuple[Path, dict[str, Path]]:
    """segmented.ply (all classes, class-coloured) + one PLY per class.

    Per-class files let the 3D viewer toggle classes on/off independently.
    Stale seg_*.ply from an earlier run (possibly a different class set) are
    removed first so only the current classes remain on disk.
    """
    for old in output_dir.glob("seg_*.ply"):
        old.unlink()
    palette = class_colors or CLASS_COLORS
    colors = np.array([palette[k] for k in classes])[labels]
    out = o3d.geometry.PointCloud()
    out.points = o3d.utility.Vector3dVector(pts)
    out.colors = o3d.utility.Vector3dVector(colors)
    combined = output_dir / "segmented.ply"
    o3d.io.write_point_cloud(str(combined), out)

    class_paths: dict[str, Path] = {}
    for i, klass in enumerate(classes):
        idx = np.where(labels == i)[0]
        if len(idx) == 0:
            continue
        sub = out.select_by_index(idx)
        dst = output_dir / f"seg_{klass}.ply"
        o3d.io.write_point_cloud(str(dst), sub)
        class_paths[klass] = dst
    return combined, class_paths
