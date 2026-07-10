"""Segment a reconstructed scene into trees / roofs by geometry + colour.

Self-contained (NumPy + Open3D, no ML models):
1. Segment the ground plane (RANSAC) and keep points above it.
2. Cluster the above-ground points (DBSCAN) into candidate objects.
3. Classify each cluster from two cheap cues:
   - greenness  ExG = 2G - R - B  (vegetation is green)   -> "tree"
   - planarity  (PCA surface variation; roofs are flat)   -> "roof"
4. Count each class and compute per-object volume (2.5D grid, model units³).
5. Recolour the cloud by class and write it for the 3D viewer.

Thresholds are heuristics (tunable) — good enough to demonstrate
segment + count + volume, not a trained semantic model.
"""

from collections.abc import Callable
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

# Class colours for the recoloured cloud (RGB 0..1).
_COLORS = {
    "ground": (0.60, 0.60, 0.60),
    "tree": (0.20, 0.72, 0.25),
    "roof": (0.95, 0.50, 0.15),
    "other": (0.40, 0.50, 0.90),
}
GREEN_EXG = 0.03  # mean ExG above this -> vegetation (tree)
ROUGH_SV = 0.010  # PCA surface variation above this -> volumetric/rough (tree)
MIN_CLUSTER_POINTS = 40


@dataclass
class SegObject:
    label: str  # "tree" | "roof" | "other"
    volume_m3: float
    num_points: int
    north_m: float
    east_m: float


@dataclass
class SegmentationResult:
    counts: dict[str, int]
    objects: list[SegObject]
    cloud_path: Path
    up_vector: tuple[float, float, float]
    objects_total: int = field(init=False)

    def __post_init__(self) -> None:
        self.objects_total = len(self.objects)


def _surface_variation(points: np.ndarray) -> float:
    """PCA smallest-eigenvalue ratio: ~0 for a flat surface, larger for volumetric."""
    if len(points) < 3:
        return 1.0
    cov = np.cov((points - points.mean(axis=0)).T)
    eig = np.clip(np.linalg.eigvalsh(cov), 0, None)
    total = eig.sum()
    return float(eig[0] / total) if total > 0 else 1.0


def _cluster_volume(points: np.ndarray, plane: np.ndarray, cell_size: float) -> float:
    """2.5D grid volume of a point set above the floor plane."""
    normal = plane[:3]
    heights = points @ normal + plane[3]
    u, v = _plane_basis(normal)
    uv = np.stack([points @ u, points @ v], axis=1)
    cells = np.floor((uv - uv.min(axis=0)) / cell_size).astype(np.int64)
    cell_ids = cells[:, 0] * (cells[:, 1].max() + 1) + cells[:, 1]
    _, inverse = np.unique(cell_ids, return_inverse=True)
    sums = np.bincount(inverse, weights=heights)
    counts = np.bincount(inverse)
    return float(cell_size**2 * np.sum(sums / counts))


def _classify(mean_exg: float, surface_variation: float) -> str:
    """Trees are green or geometrically rough; flat non-green blobs are roofs.

    Aerial reconstructions are thin (2.5D), so surface variation is only a
    weak secondary cue — greenness is the primary tree signal.
    """
    if mean_exg > GREEN_EXG or surface_variation > ROUGH_SV:
        return "tree"
    return "roof"


def segment_scene(
    ply_path: Path,
    output_dir: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> SegmentationResult:
    def report(phase: str) -> None:
        if on_progress is not None:
            on_progress(phase)

    report("segment 1/4: loading + cleaning point cloud")
    pcd = load_point_cloud(ply_path)
    if not pcd.has_colors():
        raise ValueError("point cloud has no colour — cannot separate trees from roofs")
    scale = _bbox_diagonal(pcd)

    report("segment 2/4: removing the ground plane")
    plane, above = segment_floor(pcd, distance_threshold=0.005 * scale)

    report("segment 3/4: clustering objects")
    labels = np.asarray(above.cluster_dbscan(eps=0.02 * scale, min_points=10))
    pts = np.asarray(above.points)
    cols = np.asarray(above.colors)

    objects: list[SegObject] = []
    point_label = np.full(len(pts), "other", dtype=object)
    cell = 0.01 * scale
    report("segment 4/4: classifying + measuring")
    for lab in range(labels.max() + 1):
        idx = np.where(labels == lab)[0]
        if len(idx) < MIN_CLUSTER_POINTS:
            continue
        cpts, ccols = pts[idx], cols[idx]
        mean_exg = float(np.mean(2 * ccols[:, 1] - ccols[:, 0] - ccols[:, 2]))
        klass = _classify(mean_exg, _surface_variation(cpts))
        point_label[idx] = klass
        centroid = cpts.mean(axis=0)
        objects.append(
            SegObject(
                label=klass,
                volume_m3=_cluster_volume(cpts, plane, cell),
                num_points=len(idx),
                north_m=float(centroid[0]),
                east_m=float(centroid[1]),
            )
        )

    counts = {k: sum(o.label == k for o in objects) for k in ("tree", "roof")}
    cloud_path = _write_segmented_cloud(pcd, above, point_label, output_dir or ply_path.parent)
    logger.info("Segmented scene: %s from %d clusters", counts, len(objects))
    return SegmentationResult(
        counts=counts,
        objects=objects,
        cloud_path=cloud_path,
        up_vector=(float(plane[0]), float(plane[1]), float(plane[2])),
    )


def _write_segmented_cloud(
    full: o3d.geometry.PointCloud,
    above: o3d.geometry.PointCloud,
    point_label: np.ndarray,
    output_dir: Path,
) -> Path:
    """Ground grey + above-ground points coloured by class, written as PLY."""
    ground_pts = np.asarray(full.points)
    ground_cols = np.tile(_COLORS["ground"], (len(ground_pts), 1))
    above_pts = np.asarray(above.points)
    above_cols = np.array([_COLORS[str(lbl)] for lbl in point_label])

    out = o3d.geometry.PointCloud()
    out.points = o3d.utility.Vector3dVector(np.vstack([ground_pts, above_pts]))
    out.colors = o3d.utility.Vector3dVector(np.vstack([ground_cols, above_cols]))
    dst = output_dir / "segmented.ply"
    o3d.io.write_point_cloud(str(dst), out)
    return dst
