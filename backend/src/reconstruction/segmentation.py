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
GREEN_EXG = 0.02  # per-point ExG above this -> vegetation (tree)
FLAT_DOT = 0.80  # |normal · up| above this -> horizontal surface (roof-like)
MIN_CLUSTER_POINTS = 30


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


def segment_scene(
    ply_path: Path,
    output_dir: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> SegmentationResult:
    def report(phase: str) -> None:
        if on_progress is not None:
            on_progress(phase)

    report("segment 1/5: loading + cleaning point cloud")
    pcd = load_point_cloud(ply_path)
    if not pcd.has_colors():
        raise ValueError("point cloud has no colour — cannot separate trees from roofs")
    scale = _bbox_diagonal(pcd)

    report("segment 2/5: removing the ground plane")
    plane, above = segment_floor(pcd, distance_threshold=0.005 * scale)
    up = plane[:3]

    # Per-point classification (not per-cluster): on a large scene a single
    # cluster mixes trees and buildings, so classify every point first.
    report("segment 3/5: estimating surface orientation")
    above.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.02 * scale, max_nn=30)
    )
    cols = np.asarray(above.colors)
    norms = np.asarray(above.normals)
    exg = 2 * cols[:, 1] - cols[:, 0] - cols[:, 2]
    verticality = np.abs(norms @ up)  # ~1 = horizontal surface (roof-like), ~0 = chaotic (tree)
    # roof: not green AND a flat horizontal surface; everything else is tree.
    is_roof = (exg <= GREEN_EXG) & (verticality >= FLAT_DOT)
    point_label = np.where(is_roof, "roof", "tree")

    # Cluster within each class to count objects and measure per-object volume.
    report("segment 4/5: clustering objects")
    objects: list[SegObject] = []
    cell = 0.01 * scale
    for klass in ("tree", "roof"):
        mask = point_label == klass
        if mask.sum() < MIN_CLUSTER_POINTS:
            continue
        sub = above.select_by_index(np.where(mask)[0])
        sub_pts = np.asarray(sub.points)
        clusters = np.asarray(sub.cluster_dbscan(eps=0.015 * scale, min_points=8))
        for lab in range(clusters.max() + 1):
            idx = np.where(clusters == lab)[0]
            if len(idx) < MIN_CLUSTER_POINTS:
                continue
            cpts = sub_pts[idx]
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

    report("segment 5/5: writing coloured cloud")
    counts = {k: sum(o.label == k for o in objects) for k in ("tree", "roof")}
    cloud_path = _write_segmented_cloud(pcd, above, point_label, output_dir or ply_path.parent)
    logger.info("Segmented scene: %s from %d objects", counts, len(objects))
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
