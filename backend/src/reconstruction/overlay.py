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
from collections.abc import Callable
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


def _ortho_bounds(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    """Padded percentile bounds of the scene in ground-plane coordinates.

    Shared by the point render and the photo mosaic so their pixels align
    (the UI stacks the class overlays over either base image).
    """
    x0, x1 = np.percentile(x, [1, 99])
    y0, y1 = np.percentile(y, [1, 99])
    pad_x, pad_y = 0.02 * (x1 - x0), 0.02 * (y1 - y0)
    return float(x0 - pad_x), float(x1 + pad_x), float(y0 - pad_y), float(y1 + pad_y)


def _ortho_size(width: int, x0: float, x1: float, y0: float, y1: float) -> int:
    """Image height for a given width preserving the ground aspect ratio."""
    return int(np.clip(round(width * (y1 - y0) / max(x1 - x0, 1e-9)), 64, 3000))


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

    x0, x1, y0, y1 = _ortho_bounds(x, y)
    width = ORTHO_WIDTH
    height = _ortho_size(width, x0, x1, y0, y1)
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
# True photo mosaic: every ground pixel sampled from the best photo
# ---------------------------------------------------------------------------

MOSAIC_WIDTH = 1600
_MOSAIC_PHOTO_WIDTH = 2200  # decode photos at roughly this width (JPEG draft)


def _fill_holes(grid: np.ndarray, passes: int = 16) -> np.ndarray:
    """Fill NaN cells with the mean of their valid 3x3 neighbours, repeatedly."""
    for _ in range(passes):
        nan = np.isnan(grid)
        if not nan.any():
            break
        padded = np.pad(grid, 1, constant_values=np.nan)
        shifts = [
            padded[1 + dy : padded.shape[0] - 1 + dy, 1 + dx : padded.shape[1] - 1 + dx]
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if (dy, dx) != (0, 0)
        ]
        stack = np.stack(shifts)
        valid = ~np.isnan(stack)
        counts = valid.sum(axis=0)
        sums = np.where(valid, stack, 0.0).sum(axis=0)
        mean = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
        grid = np.where(nan, mean, grid)
    return np.nan_to_num(grid, nan=0.0)


def _ensure_same_frame(pts: np.ndarray, shots: dict) -> np.ndarray:
    """Camera centres for all shots, after checking they share the cloud's frame.

    Two observed failure modes when stale artefacts from different OpenSfM
    runs mix: the cloud sits millions of units from the cameras (different
    origins), or the cameras bunch into a few units while the cloud spans
    hundreds (different scales). Either way projecting is meaningless.
    """
    centers = np.array(
        [
            -_rotation_matrix(np.asarray(s["rotation"], dtype=float)).T
            @ np.asarray(s["translation"], dtype=float)
            for s in shots.values()
        ]
    )
    cloud_center = np.median(pts, axis=0)
    cloud_extent = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
    cam_center = np.median(centers, axis=0)
    cam_extent = float(np.linalg.norm(centers.max(axis=0) - centers.min(axis=0)))
    offset = float(np.linalg.norm(cloud_center - cam_center))
    if offset > 20 * max(cloud_extent, 1e-6) or (
        len(shots) > 3 and cam_extent < cloud_extent / 50
    ):
        raise ValueError(
            "point cloud and camera poses are in different coordinate frames — "
            "stale outputs from a previous run; re-run the reconstruction"
        )
    return centers


def render_photo_mosaic(
    labels_path: Path,
    project_dir: Path,
    out_dir: Path,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Write ortho_photo.png — the photos merged into one seamless top-down
    image — and return its filename.

    A simplified orthomosaic: build a height map of the scene from the point
    cloud, then colour every ground pixel by projecting its 3D position into
    the photo whose camera stood closest above it (nearest-nadir sampling; no
    seam blending). Bounds match render_ortho, so the class overlays stack on
    this image unchanged.
    """
    data = _load_labels(labels_path)
    pts = data["points"].astype(np.float64)
    plane = data["plane"]
    u_ax, v_ax, n_ax = _plane_frame(plane)
    d = float(plane[3])

    x = pts @ u_ax
    y = pts @ v_ax
    h = pts @ n_ax + d
    x0, x1, y0, y1 = _ortho_bounds(x, y)
    width = MOSAIC_WIDTH
    height = _ortho_size(width, x0, x1, y0, y1)

    # Height map (DSM): topmost point height per pixel, splatted 2x2, then
    # hole-filled — needed so roofs/piles sample from the right photo pixel.
    px = ((x - x0) / (x1 - x0) * (width - 2)).astype(np.int32)
    py = ((y - y0) / (y1 - y0) * (height - 2)).astype(np.int32)
    keep = (px >= 0) & (px < width - 1) & (py >= 0) & (py < height - 1)
    order = np.argsort(h[keep])
    px_o, py_o, h_o = px[keep][order], py[keep][order], h[keep][order]
    dsm = np.full((height, width), np.nan)
    for dy in (0, 1):
        for dx in (0, 1):
            dsm[py_o + dy, px_o + dx] = h_o
    dsm = _fill_holes(dsm)

    # World position of every output pixel (pixel centre -> plane frame).
    gx = x0 + (np.arange(width) + 0.5) / (width - 2) * (x1 - x0)
    gy = y0 + (np.arange(height) + 0.5) / (height - 2) * (y1 - y0)
    grid_x, grid_y = np.meshgrid(gx, gy)
    world = (
        grid_x[..., None] * u_ax
        + grid_y[..., None] * v_ax
        + (dsm - d)[..., None] * n_ax
    ).reshape(-1, 3)

    recon = _load_reconstruction(project_dir)
    shots, cameras = recon["shots"], recon["cameras"]
    names = sorted(shots)
    centers = _ensure_same_frame(pts, {s: shots[s] for s in names})
    cam_xy = np.stack([centers @ u_ax, centers @ v_ax], axis=1)

    # Nearest camera (in ground XY) per pixel, chunked to bound memory.
    pix_xy = np.stack([grid_x.reshape(-1), grid_y.reshape(-1)], axis=1)
    assign = np.empty(len(pix_xy), dtype=np.int32)
    chunk = 200_000
    for start in range(0, len(pix_xy), chunk):
        block = pix_xy[start : start + chunk]
        d2 = ((block[:, None, :] - cam_xy[None, :, :]) ** 2).sum(axis=2)
        assign[start : start + chunk] = np.argmin(d2, axis=1)

    # Start from the point render so pixels no photo covers are not black.
    base_png = out_dir / "ortho_base.png"
    if base_png.is_file():
        out = np.asarray(
            Image.open(base_png).convert("RGB").resize((width, height), Image.NEAREST)
        ).copy()
    else:
        out = np.zeros((height, width, 3), dtype=np.uint8)
    out = out.reshape(-1, 3)
    filled = np.zeros(len(out), dtype=bool)

    def sample(shot_name: str, targets: np.ndarray) -> None:
        """Sample colours for these pixel indices from one photo."""
        shot = shots[shot_name]
        camera = cameras[shot["camera"]]
        pix, in_front = _project(world[targets], shot, camera)
        with np.errstate(invalid="ignore"):
            pix = np.nan_to_num(pix, nan=-1e9, posinf=1e9, neginf=-1e9)
        w_full, h_full = camera["width"], camera["height"]
        ok = (
            in_front
            & (pix[:, 0] >= 0)
            & (pix[:, 0] < w_full - 1)
            & (pix[:, 1] >= 0)
            & (pix[:, 1] < h_full - 1)
        )
        if not ok.any():
            return
        photo_path = project_dir / "images" / shot_name
        photo = Image.open(photo_path)
        # JPEG draft mode decodes at reduced resolution — much faster.
        photo.draft("RGB", (_MOSAIC_PHOTO_WIDTH, _MOSAIC_PHOTO_WIDTH))
        arr = np.asarray(photo.convert("RGB"))
        scale_x = arr.shape[1] / w_full
        scale_y = arr.shape[0] / h_full
        ui = np.clip((pix[ok, 0] * scale_x).astype(np.int32), 0, arr.shape[1] - 1)
        vi = np.clip((pix[ok, 1] * scale_y).astype(np.int32), 0, arr.shape[0] - 1)
        hit = targets[ok]
        out[hit] = arr[vi, ui]
        filled[hit] = True

    for i, name in enumerate(names):
        targets = np.where((assign == i) & ~filled)[0]
        if len(targets) == 0:
            continue
        sample(name, targets)
        if on_progress is not None and (i + 1) % 10 == 0:
            on_progress(f"photo mosaic: {i + 1}/{len(names)} photos")

    # Pixels whose nearest photo did not cover them: sweep the photos again.
    for name in names:
        remaining = np.where(~filled)[0]
        if len(remaining) == 0:
            break
        sample(name, remaining)

    result = out.reshape(height, width, 3)
    filename = "ortho_photo.png"
    Image.fromarray(result).save(out_dir / filename)
    return filename


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
    _ensure_same_frame(pts, recon["shots"])

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
