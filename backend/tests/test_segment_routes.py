"""Dynamic-class behaviour of the segment/volume routes.

An ML run can produce any class set; the routes must whitelist against the
registry the run wrote (seg_classes.json), falling back to the static
heuristic classes for old outputs.
"""

import json
import math
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from api.main import app
from core.config import settings
from reconstruction.segmentation import write_class_registry

client = TestClient(app)


def _project_with_registry(project: Path, classes: list[str]) -> Path:
    (project / "reconstruction.ply").write_bytes(b"ply")  # find_point_cloud target
    write_class_registry(project, classes, {k: (0.5, 0.5, 0.5) for k in classes})
    return project


def test_segment_jobs_rejects_bad_mode() -> None:
    response = client.post("/segment/jobs", json={"mode": "bogus"})
    assert response.status_code == 422


def test_segment_jobs_404_without_reconstruction(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "opensfm_project_root", tmp_path)
    response = client.post("/segment/jobs", json={"mode": "ml"})
    assert response.status_code == 404


def test_ortho_whitelist_follows_registry(monkeypatch, tmp_path: Path) -> None:
    project = _project_with_registry(tmp_path, ["pond", "other"])
    monkeypatch.setattr(settings, "opensfm_project_root", project)

    # Registry class: allowed (404s only because no PNG was rendered yet).
    response = client.get("/segment/ortho/ortho_pond.png")
    assert response.status_code == 404
    assert "not rendered" in response.json()["detail"]

    # Not in this run's registry: rejected as unknown.
    response = client.get("/segment/ortho/ortho_pile.png")
    assert response.status_code == 404
    assert "unknown file" in response.json()["detail"]


def test_ortho_static_fallback_without_registry(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "reconstruction.ply").write_bytes(b"ply")
    monkeypatch.setattr(settings, "opensfm_project_root", tmp_path)

    response = client.get("/segment/ortho/ortho_pile.png")  # static heuristic class
    assert response.status_code == 404
    assert "not rendered" in response.json()["detail"]


def test_seg_cloud_download_follows_registry(monkeypatch, tmp_path: Path) -> None:
    project = _project_with_registry(tmp_path, ["pond", "other"])
    monkeypatch.setattr(settings, "opensfm_project_root", project)
    (project / "seg_pond.ply").write_bytes(b"plydata")

    assert client.get("/volume/files/seg_pond.ply").status_code == 200
    assert client.get("/volume/files/seg_bogus.ply").status_code == 404


def test_photo_overlay_unknown_class_rejected(monkeypatch, tmp_path: Path) -> None:
    project = _project_with_registry(tmp_path, ["pond", "other"])
    (project / "reconstruction.json").write_text(
        json.dumps(
            [
                {
                    "cameras": {
                        "cam": {
                            "projection_type": "perspective",
                            "focal": 1.0,
                            "width": 100,
                            "height": 100,
                        }
                    },
                    "shots": {
                        "img.jpg": {
                            "camera": "cam",
                            "rotation": [math.pi, 0.0, 0.0],
                            "translation": [0.0, 0.0, 8.0],
                        }
                    },
                }
            ]
        )
    )
    np.savez_compressed(
        project / "labels.npz",
        points=np.zeros((10, 3), dtype=np.float32),
        colors=np.zeros((10, 3), dtype=np.uint8),
        labels=np.zeros(10, dtype=np.uint8),
        plane=np.array([0.0, 0.0, 1.0, 0.0]),
        classes=np.array(["pond", "other"]),
    )
    monkeypatch.setattr(settings, "opensfm_project_root", project)

    # "car" is a valid static class but NOT in this ML run's registry.
    response = client.get("/segment/photo/img.jpg", params={"classes": "car"})
    assert response.status_code == 422
    assert "unknown classes" in response.json()["detail"]
