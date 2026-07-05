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


def test_grid_survey_pattern() -> None:
    response = client.post(
        "/sim/orbit",
        json={"dataset_id": "demo", "pattern": "grid", "radius_m": 5.0, "spacing_m": 2.5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pattern"] == "grid"
    assert body["num_triggers"] == 25  # 5 rows x 5 columns over a 10 m square
    assert len({t["north_m"] for t in body["triggers"]}) == 5
    # serpentine: first row flies east, second row flies west
    assert body["triggers"][0]["yaw_deg"] == 90.0
    assert body["triggers"][5]["yaw_deg"] == 270.0


def test_orbit_sim() -> None:
    response = client.post("/sim/orbit", json={"dataset_id": "demo", "num_triggers": 8})
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "demo"
    assert body["num_triggers"] == 8
    assert body["mode"] in ("offline", "mavsdk")
    # at least one log line per camera trigger, plus start/end lines
    assert len(body["logs"]) >= 8
    assert any("Camera trigger" in line for line in body["logs"])
    assert len(body["triggers"]) == 8
    first = body["triggers"][0]
    assert {"index", "north_m", "east_m", "up_m", "yaw_deg"} <= set(first)
