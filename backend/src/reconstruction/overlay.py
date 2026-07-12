"""2D verification overlays for a segmented scene (NumPy + Pillow only).

Two views of the same labels.npz that segmentation.py writes:

- Orthophoto: the point cloud rendered straight down onto the ground plane.
  Because the 3D reconstruction already aligned every photo, this IS the
  "all photos merged into one image" view — no 2D stitching needed. A base
  image plus one RGBA overlay per class lets the UI toggle classes client-side.

- Photo overlay: class points projected back into an original photo through
  its OpenSfM camera pose (reconstruction.json), so the segmentation can be
  verified against the real pixels. No occlusion test — fine for nadir/oblique
  aerial shots where little geometry hides other geometry.

Kept free of Open3D on purpose: these run in the API process (no crash risk).
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

from core.logging import get_logger

logger = get_logger(__name__)

ORTHO_WIDTH = 900
OVERLAY_ALPHA = 190


def _load_labels(labels_path: Path) -> dict[str, np.ndarray]:
    data = np.load(labels_path, allow_pickle=False)
    return {k: data[k] for k in ("points", "colors", "labels", "plane", "classes")}


def _plane_frame(plane: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Orthonormal (u, v, n) with n = the floor normal."""
    n = plane[:3] / np.linalg.norm(plane[:3])
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, helper)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v, n


def render_ortho(labels_path: Path, out_dir: Path, class_colors: dict) -> dict[str, str]:
    """Write ortho_base.png + ortho_<class>.png; return {name: filename}.

    Top-down z-buffer render: points sorted by height, higher points win the
    pixel, each point splatted 2x2 so the image is dense.
    """
    data = _load_labels(labels_path)
    pts, cols, labels = data["points"], data["colors"], data["labels"]
    classes = [str(c) for c in data["classes"]]
    plane = data["plane"]
    u_ax, v_ax, n_ax = _plane_frame(plane)

    x = pts @ u_ax
    y = pts @ v_ax
    h = pts @ n_ax + plane[3]

    # Percentile bounds keep stray far-away points from blowing up the frame.
    x0, x1 = np.percentile(x, [1, 99])
    y0, y1 = np.percentile(y, [1, 99])
    pad_x, pad_y = 0.02 * (x1 - x0), 0.02 * (y1 - y0)
    x0, x1, y0, y1 = x0 - pad_x, x1 + pad_x, y0 - pad_y, y1 + pad_y

    width = ORTHO_WIDTH
    height = int(np.clip(round(width * (y1 - y0) / max(x1 - x0, 1e-9)), 64, 2400))
    px = ((x - x0) / (x1 - x0) * (width - 2)).astype(np.int32)
    py = ((y - y0) / (y1 - y0) * (height - 2)).astype(np.int32)
    keep = (px >= 0) & (px < width - 1) & (py >= 0) & (py < height - 1)

    order = np.argsort(h[keep])  # ascending: highest points assigned last, win
    px_o, py_o = px[keep][order], py[keep][order]
    idx_o = np.where(keep)[0][order]

    top = np.full((height, width), -1, dtype=np.int64)  # topmost point per pixel
    for dy in (0, 1):
        for dx in (0, 1):
            top[py_o + dy, px_o + dx] = idx_o

    filled = top >= 0
    base = np.zeros((height, width, 3), dtype=np.uint8)
    base[..., :] = (27, 30, 38)  # match the 3D viewer background
    base[filled] = cols[top[filled]]
    files = {"base": "ortho_base.png"}
    Image.fromarray(base).save(out_dir / files["base"])

    top_label = np.where(filled, labels[np.maximum(top, 0)], 255)
    for i, klass in enumerate(classes):
        mask = top_label == i
        if not mask.any():
            continue
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[mask, :3] = [int(c * 255) for c in class_colors[klass]]
        rgba[mask, 3] = OVERLAY_ALPHA
        name = f"ortho_{klass}.png"
        Image.fromarray(rgba).save(out_dir / name)
        files[klass] = name
    return files


# ---------------------------------------------------------------------------
# Photo overlays via OpenSfM camera poses
# ---------------------------------------------------------------------------

_recon_cache: dict[str, tuple[float, dict]] = {}


def _load_reconstruction(project_dir: Path) -> dict:
    """cameras + shots of the first reconstruction, cached by file mtime."""
    path = project_dir / "reconstruction.json"
    mtime = path.stat().st_mtime
    cached = _recon_cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    recon = json.loads(path.read_text())[0]
    slim = {"cameras": recon["cameras"], "shots": recon["shots"]}
    _recon_cache[str(path)] = (mtime, slim)
    return slim


def list_shot_images(project_dir: Path) -> list[str]:
    """Names of photos that have a camera pose (i.e. can show an overlay)."""
    return sorted(_load_reconstruction(project_dir)["shots"].keys())


def _rotation_matrix(rvec: np.ndarray) -> np.ndarray:
    """Rodrigues: axis-angle vector -> 3x3 rotation matrix."""
    theta = float(np.linalg.norm(rvec))
    if theta < 1e-12:
        return np.eye(3)
    k = rvec / theta
    kx, ky, kz = k
    cross = np.array([[0, -kz, ky], [kz, 0, -kx], [-ky, kx, 0]])
    return np.eye(3) + np.sin(theta) * cross + (1 - np.cos(theta)) * (cross @ cross)


def _project(points: np.ndarray, shot: dict, camera: dict) -> tuple[np.ndarray, np.ndarray]:
    """World points -> pixel coords (N,2) + in-front mask, OpenSfM conventions."""
    rot = _rotation_matrix(np.asarray(shot["rotation"], dtype=float))
    t = np.asarray(shot["translation"], dtype=float)
    cam_pts = points @ rot.T + t
    in_front = cam_pts[:, 2] > 1e-6
    z = np.where(in_front, cam_pts[:, 2], 1.0)
    xn = cam_pts[:, 0] / z
    yn = cam_pts[:, 1] / z
    r2 = xn**2 + yn**2

    ptype = camera.get("projection_type", "perspective")
    if ptype in ("perspective", "simple_radial"):
        k1 = camera.get("k1", 0.0)
        k2 = camera.get("k2", 0.0)
        distort = 1 + k1 * r2 + k2 * r2**2
        f = camera["focal"]
        xd = f * distort * xn
        yd = f * distort * yn
    elif ptype == "brown":
        k1, k2, k3 = camera.get("k1", 0.0), camera.get("k2", 0.0), camera.get("k3", 0.0)
        p1, p2 = camera.get("p1", 0.0), camera.get("p2", 0.0)
        radial = 1 + k1 * r2 + k2 * r2**2 + k3 * r2**3
        x_t = 2 * p1 * xn * yn + p2 * (r2 + 2 * xn**2)
        y_t = p1 * (r2 + 2 * yn**2) + 2 * p2 * xn * yn
        fx = camera.get("focal_x", camera.get("focal", 1.0))
        fy = camera.get("focal_y", fx)
        xd = fx * (radial * xn + x_t) + camera.get("c_x", 0.0)
        yd = fy * (radial * yn + y_t) + camera.get("c_y", 0.0)
    else:
        raise ValueError(f"unsupported projection type: {ptype}")

    w, hgt = camera["width"], camera["height"]
    size = max(w, hgt)
    pix = np.stack([xd * size + (w - 1) / 2, yd * size + (hgt - 1) / 2], axis=1)
    return pix, in_front


def render_photo_overlay(
    labels_path: Path,
    project_dir: Path,
    image_name: str,
    class_ids: list[int],
    class_colors_by_id: list[tuple[float, float, float]],
    width: int = 1200,
) -> Image.Image:
    """The original photo with the selected classes' points splatted on top."""
    recon = _load_reconstruction(project_dir)
    shot = recon["shots"].get(image_name)
    if shot is None:
        raise FileNotFoundError(f"no camera pose for image: {image_name}")
    camera = recon["cameras"][shot["camera"]]

    photo_path = project_dir / "images" / image_name
    photo = Image.open(photo_path).convert("RGB")
    scale = width / photo.width
    height = max(1, round(photo.height * scale))
    photo = photo.resize((width, height), Image.BILINEAR)

    data = _load_labels(labels_path)
    pts, labels = data["points"].astype(np.float64), data["labels"]

    # Guard against mixed-frame artefacts (e.g. a merged.ply cached from a
    # GPS-aligned run next to a GPS-denied reconstruction.json): if the cloud
    # sits nowhere near this camera, projecting it is meaningless.
    rot = _rotation_matrix(np.asarray(shot["rotation"], dtype=float))
    cam_center = -rot.T @ np.asarray(shot["translation"], dtype=float)
    cloud_center = np.median(pts, axis=0)
    cloud_extent = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
    if np.linalg.norm(cloud_center - cam_center) > 50 * max(cloud_extent, 1e-6):
        raise ValueError(
            "point cloud and camera poses are in different coordinate frames — "
            "stale outputs from a previous run; re-run the reconstruction"
        )

    pix, in_front = _project(pts, shot, camera)
    with np.errstate(invalid="ignore"):
        pix = np.nan_to_num(pix, nan=-1e9, posinf=1e9, neginf=-1e9)
    px = np.clip(pix[:, 0] * scale, -1, width).astype(np.int32)
    py = np.clip(pix[:, 1] * scale, -1, height).astype(np.int32)
    in_view = in_front & (px >= 0) & (px < width - 1) & (py >= 0) & (py < height - 1)

    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    for cid in class_ids:
        mask = in_view & (labels == cid)
        if not mask.any():
            continue
        color = [int(c * 255) for c in class_colors_by_id[cid]]
        xs, ys = px[mask], py[mask]
        for dy in (0, 1):
            for dx in (0, 1):
                overlay[ys + dy, xs + dx, :3] = color
                overlay[ys + dy, xs + dx, 3] = OVERLAY_ALPHA

    out = photo.convert("RGBA")
    out.alpha_composite(Image.fromarray(overlay))
    return out.convert("RGB")


def photo_overlay_cache_path(
    cache_dir: Path, image_name: str, class_ids: list[int], width: int
) -> Path:
    key = "-".join(str(c) for c in sorted(class_ids)) or "none"
    return cache_dir / f"{Path(image_name).stem}_w{width}_c{key}.jpg"


def render_photo_overlay_cached(
    labels_path: Path,
    project_dir: Path,
    cache_dir: Path,
    image_name: str,
    class_ids: list[int],
    class_colors_by_id: list[tuple[float, float, float]],
    width: int = 1200,
) -> Path:
    """Disk-cached render_photo_overlay; invalidated when labels.npz changes."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dst = photo_overlay_cache_path(cache_dir, image_name, class_ids, width)
    if dst.is_file() and dst.stat().st_mtime >= labels_path.stat().st_mtime:
        return dst
    image = render_photo_overlay(
        labels_path, project_dir, image_name, class_ids, class_colors_by_id, width
    )
    image.save(dst, quality=85)
    return dst
