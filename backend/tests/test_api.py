from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_datasets_returns_list() -> None:
    response = client.get("/datasets")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["datasets"], list)


def test_download_unknown_file_returns_404() -> None:
    response = client.get("/volume/files/secrets.txt")
    assert response.status_code == 404
    assert "unknown file" in response.json()["detail"]


def test_download_not_generated_returns_404(monkeypatch, tmp_path) -> None:
    # Point the project at an empty directory: the developer machine may have
    # real reconstruction outputs lying around.
    from core.config import settings

    monkeypatch.setattr(settings, "opensfm_project_root", tmp_path)
    response = client.get("/volume/files/merged.ply")
    assert response.status_code == 404
    assert "not generated" in response.json()["detail"]


def test_volume_run_unknown_dataset_returns_404() -> None:
    response = client.post("/volume/run", json={"dataset_id": "no-such-dataset"})
    assert response.status_code == 404


def test_volume_example_unknown_dataset_returns_404() -> None:
    response = client.post("/volume/example", json={"dataset_id": "no-such-dataset"})
    assert response.status_code == 404


def test_volume_example_accepts_empty_body() -> None:
    # Body is optional (defaults to the example dataset); the request must
    # never be rejected as a validation error. The outcome depends on the
    # environment: 404 without the banana dataset cloned, 500 without the
    # OpenSfM CLI, 200 with both present.
    response = client.post("/volume/example", json={})
    assert response.status_code != 422


def test_volume_example_success_response_shape(monkeypatch) -> None:
    from api.routes import volume as volume_route
    from core.config import settings
    from reconstruction.volume_compute import VolumeResult

    fake_ply = settings.data_dir / "opensfm_project" / "undistorted" / "depthmaps" / "merged.ply"
    monkeypatch.setattr(
        volume_route,
        "run_reconstruction_and_volume",
        lambda dataset_id, use_symlink=True: VolumeResult(
            volume_m3=4.2, num_points=123, method="grid", point_cloud_path=fake_ply
        ),
    )

    response = client.post("/volume/example", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dataset_id"] == "banana"  # backend default
    assert body["volume_m3"] == 4.2
    assert body["ply_path"] == "opensfm_project/undistorted/depthmaps/merged.ply"
    assert body["ply_url"] == "/volume/files/merged.ply"


def _fake_images(n: int) -> list[str]:
    return [f"IMG_{i:03d}.JPG" for i in range(n)]


def test_grid_survey_matches_dataset_images(monkeypatch) -> None:
    from sim import orbit_capture

    monkeypatch.setattr(orbit_capture, "dataset_image_names", lambda _id: _fake_images(9))
    response = client.post("/sim/orbit", json={"dataset_id": "demo", "pattern": "grid"})
    assert response.status_code == 200
    body = response.json()
    assert body["pattern"] == "grid"
    assert body["num_triggers"] == 9  # one shot per dataset image
    assert [t["image"] for t in body["triggers"]] == _fake_images(9)
    # serpentine: first row flies east, second row flies west (3x3 grid)
    assert body["triggers"][0]["yaw_deg"] == 90.0
    assert body["triggers"][3]["yaw_deg"] == 270.0


def test_orbit_sim_matches_dataset_images(monkeypatch) -> None:
    from sim import orbit_capture

    monkeypatch.setattr(orbit_capture, "dataset_image_names", lambda _id: _fake_images(8))
    response = client.post("/sim/orbit", json={"dataset_id": "demo"})
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "demo"
    assert body["num_triggers"] == 8  # one shot per dataset image
    assert body["mode"] in ("offline", "mavsdk")
    assert any("Shutter" in line for line in body["logs"])
    assert [t["image"] for t in body["triggers"]] == _fake_images(8)
    assert {"index", "north_m", "east_m", "up_m", "yaw_deg", "image"} <= set(body["triggers"][0])


def test_orbit_sim_no_images_returns_422(monkeypatch) -> None:
    from sim import orbit_capture

    monkeypatch.setattr(orbit_capture, "dataset_image_names", lambda _id: [])
    response = client.post("/sim/orbit", json={"dataset_id": "empty"})
    assert response.status_code == 422
