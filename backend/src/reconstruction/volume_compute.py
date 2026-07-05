"""Estimate stockpile volume from a reconstructed point cloud using Open3D.

Steps (per Skill.md, skill:reconstruction):
1. Load the point cloud (OpenSfM's merged.ply), downsample and drop outliers.
2. RANSAC-segment the dominant plane — assumed to be the floor.
3. Keep points above the floor; the largest DBSCAN cluster is the stockpile.
4. Build an alpha-shape surface mesh, closed at the bottom with the pile's
   footprint projected onto the floor. If the mesh is watertight its exact
   volume is used ("mesh" method); otherwise the volume is the integral of
   mean point height above the floor over a 2D grid ("grid" method).

All geometric parameters (voxel size, RANSAC threshold, cluster eps, alpha,
grid cell) are derived from the cloud's bounding-box diagonal, because a
GPS-denied reconstruction without GCPs has arbitrary scale: results are in
"model units cubed" and only become true m³ once the reconstruction is scaled
(GCPs or a known distance).
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import open3d as o3d

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VolumeResult:
    volume_m3: float
    num_points: int
    method: str  # "mesh" (watertight alpha shape) or "grid" (height integration)
    point_cloud_path: Path
    mesh_path: Path | None = None


def compute_volume(ply_path: Path, output_dir: Path | None = None) -> VolumeResult:
    """Full pipeline: load, segment floor, isolate pile, mesh, measure volume."""
    pcd = load_point_cloud(ply_path)
    scale = _bbox_diagonal(pcd)

    plane, above = segment_floor(pcd, distance_threshold=0.005 * scale)
    pile = isolate_stockpile(above, eps=0.02 * scale)

    mesh = build_stockpile_mesh(pile, plane, alpha=0.05 * scale)
    mesh_path: Path | None = None
    if mesh is not None:
        mesh_path = (output_dir or ply_path.parent) / "stockpile_mesh.ply"
        o3d.io.write_triangle_mesh(str(mesh_path), mesh)

    volume, method = _mesh_volume(mesh) if mesh is not None else (None, None)
    if volume is None:
        volume = grid_volume(pile, plane, cell_size=0.01 * scale)
        method = "grid"

    logger.info(
        "Estimated volume %.4f (method=%s) from %d pile points",
        volume, method, len(pile.points),
    )
    return VolumeResult(
        volume_m3=volume,
        num_points=len(pile.points),
        method=method,
        point_cloud_path=ply_path,
        mesh_path=mesh_path,
    )


def load_point_cloud(ply_path: Path) -> o3d.geometry.PointCloud:
    """Load, voxel-downsample and statistically de-noise a point cloud."""
    pcd = o3d.io.read_point_cloud(str(ply_path))
    if not pcd.has_points():
        raise ValueError(f"no points in point cloud: {ply_path}")
    pcd = pcd.voxel_down_sample(_bbox_diagonal(pcd) / 400.0)
    pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
    if len(pcd.points) < 100:
        raise ValueError(f"too few points after cleaning: {len(pcd.points)}")
    return pcd


def _bbox_diagonal(pcd: o3d.geometry.PointCloud) -> float:
    """Bounding-box diagonal length — the scale reference for all parameters."""
    return float(np.linalg.norm(pcd.get_axis_aligned_bounding_box().get_extent()))


def segment_floor(
    pcd: o3d.geometry.PointCloud,
    distance_threshold: float,
) -> tuple[np.ndarray, o3d.geometry.PointCloud]:
    """RANSAC the dominant plane; return (plane [a,b,c,d], points above it)."""
    plane, inliers = pcd.segment_plane(
        distance_threshold=distance_threshold, ransac_n=3, num_iterations=1000
    )
    plane = np.asarray(plane, dtype=float)
    plane /= np.linalg.norm(plane[:3])

    rest = pcd.select_by_index(inliers, invert=True)
    pts = np.asarray(rest.points)
    heights = pts @ plane[:3] + plane[3]
    if np.median(heights) < 0:  # orient the normal toward the pile side
        plane, heights = -plane, -heights

    above = rest.select_by_index(np.where(heights > distance_threshold)[0])
    if len(above.points) < 50:
        raise ValueError("no significant structure found above the floor plane")
    return plane, above


def isolate_stockpile(
    pcd: o3d.geometry.PointCloud,
    eps: float,
    min_points: int = 10,
) -> o3d.geometry.PointCloud:
    """Return the largest DBSCAN cluster — assumed to be the stockpile."""
    labels = np.asarray(pcd.cluster_dbscan(eps=eps, min_points=min_points))
    if labels.max() < 0:
        raise ValueError("could not cluster any stockpile points")
    largest = int(np.bincount(labels[labels >= 0]).argmax())
    return pcd.select_by_index(np.where(labels == largest)[0])


def build_stockpile_mesh(
    pile: o3d.geometry.PointCloud,
    plane: np.ndarray,
    alpha: float,
) -> o3d.geometry.TriangleMesh | None:
    """Alpha-shape the pile, closed at the bottom with its floor footprint.

    Projecting every pile point onto the floor plane and meshing the combined
    set gives the alpha shape a base, so it has a chance of being watertight.
    """
    pts = np.asarray(pile.points)
    normal = plane[:3]
    heights = pts @ normal + plane[3]
    base = pts - np.outer(heights, normal)

    closed = o3d.geometry.PointCloud()
    closed.points = o3d.utility.Vector3dVector(np.vstack([pts, base]))
    try:
        # Errors only: alpha shapes on scan data emit an "invalid tetra"
        # warning per degenerate cell, easily flooding megabytes of output.
        with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Error):
            mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_alpha_shape(closed, alpha)
    except RuntimeError as exc:
        logger.warning("Alpha-shape meshing failed: %s", exc)
        return None
    mesh.compute_vertex_normals()
    return mesh


def _mesh_volume(mesh: o3d.geometry.TriangleMesh) -> tuple[float | None, str | None]:
    if not mesh.is_watertight():
        logger.info("Alpha-shape mesh not watertight; using grid integration")
        return None, None
    try:
        return float(mesh.get_volume()), "mesh"
    except RuntimeError as exc:
        logger.warning("Mesh volume failed (%s); using grid integration", exc)
        return None, None


def grid_volume(
    pile: o3d.geometry.PointCloud,
    plane: np.ndarray,
    cell_size: float,
) -> float:
    """Integrate mean point height above the floor over a 2D grid.

    Standard 2.5D stockpile volumetrics: rasterise the pile footprint in
    floor-plane coordinates and sum cell_area x mean height per cell.
    """
    pts = np.asarray(pile.points)
    normal = plane[:3]
    heights = pts @ normal + plane[3]

    u, v = _plane_basis(normal)
    uv = np.stack([pts @ u, pts @ v], axis=1)
    cells = np.floor((uv - uv.min(axis=0)) / cell_size).astype(np.int64)
    cell_ids = cells[:, 0] * (cells[:, 1].max() + 1) + cells[:, 1]

    _, inverse = np.unique(cell_ids, return_inverse=True)
    sums = np.bincount(inverse, weights=heights)
    counts = np.bincount(inverse)
    return float(cell_size**2 * np.sum(sums / counts))


def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two orthonormal vectors spanning the plane with the given normal."""
    ref = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(normal, ref)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    return u, v
