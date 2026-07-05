"""Volume estimation on a synthetic scene with known ground truth.

Scene: a dense floor at z=0 with a 2 x 2 x 1 box-shaped "stockpile" on it
(top face + side walls, as a surface scan would see it). True volume: 4.0.
"""

import numpy as np
import pytest

o3d = pytest.importorskip("open3d")

from reconstruction.volume_compute import compute_volume  # noqa: E402

TRUE_VOLUME = 4.0


def _synthetic_scene() -> np.ndarray:
    step = 0.02
    # Floor: [0,6] x [0,6] at z=0
    fx, fy = np.meshgrid(np.arange(0, 6, step), np.arange(0, 6, step))
    floor = np.stack([fx.ravel(), fy.ravel(), np.zeros(fx.size)], axis=1)
    # Pile top face: [2,4] x [2,4] at z=1
    tx, ty = np.meshgrid(np.arange(2, 4, step), np.arange(2, 4, step))
    top = np.stack([tx.ravel(), ty.ravel(), np.ones(tx.size)], axis=1)
    # Pile side walls
    s, z = np.meshgrid(np.arange(2, 4, step), np.arange(0, 1, step))
    walls = np.concatenate([
        np.stack([s.ravel(), np.full(s.size, 2.0), z.ravel()], axis=1),
        np.stack([s.ravel(), np.full(s.size, 4.0), z.ravel()], axis=1),
        np.stack([np.full(s.size, 2.0), s.ravel(), z.ravel()], axis=1),
        np.stack([np.full(s.size, 4.0), s.ravel(), z.ravel()], axis=1),
    ])
    return np.concatenate([floor, top, walls])


def test_compute_volume_box_pile(tmp_path) -> None:
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(_synthetic_scene())
    ply_path = tmp_path / "merged.ply"
    o3d.io.write_point_cloud(str(ply_path), pcd)

    result = compute_volume(ply_path)

    assert result.method in ("mesh", "grid")
    assert result.num_points > 100
    # 20% tolerance: downsampling, wall-cell averaging and meshing all blur edges.
    assert result.volume_m3 == pytest.approx(TRUE_VOLUME, rel=0.2)
    if result.mesh_path is not None:
        assert result.mesh_path.exists()
