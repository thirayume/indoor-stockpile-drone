"""Background-job API flow, with the pipeline monkeypatched for speed."""

import time

from fastapi.testclient import TestClient

from api.main import app
from api.routes import volume as volume_route
from core.config import settings
from reconstruction.volume_compute import VolumeResult

client = TestClient(app)


def _wait_for_terminal(job_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/volume/jobs/{job_id}").json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout_s}s")


def test_job_success_flow(monkeypatch) -> None:
    fake_ply = settings.data_dir / "opensfm_project" / "undistorted" / "depthmaps" / "merged.ply"

    def fake_run(dataset_id, use_symlink=True, on_progress=None):
        if on_progress is not None:
            on_progress("opensfm reconstruct (5/9)")
        return VolumeResult(
            volume_m3=4.2, num_points=123, method="grid", point_cloud_path=fake_ply
        )

    monkeypatch.setattr(volume_route, "run_reconstruction_and_volume", fake_run)

    response = client.post("/volume/jobs", json={"dataset_id": "banana"})
    assert response.status_code == 202
    body = response.json()
    # The response is a snapshot: a fast job may already be done.
    assert body["status"] in ("queued", "running", "succeeded")

    final = _wait_for_terminal(body["job_id"])
    assert final["status"] == "succeeded"
    assert final["dataset_id"] == "banana"
    assert final["progress"] == "opensfm reconstruct (5/9)"
    assert final["result"]["volume_m3"] == 4.2
    assert final["result"]["point_cloud_url"] == "/volume/files/merged.ply"

    listing = client.get("/volume/jobs").json()
    assert any(j["job_id"] == body["job_id"] for j in listing)


def test_job_failure_flow(monkeypatch) -> None:
    def fake_run(dataset_id, use_symlink=True, on_progress=None):
        raise RuntimeError("OpenSfM CLI not found")

    monkeypatch.setattr(volume_route, "run_reconstruction_and_volume", fake_run)

    body = client.post("/volume/jobs", json={}).json()
    assert body["dataset_id"] == "banana"  # backend default applied

    final = _wait_for_terminal(body["job_id"])
    assert final["status"] == "failed"
    assert "OpenSfM" in final["error"]
    assert final["result"] is None


def test_get_unknown_job_returns_404() -> None:
    assert client.get("/volume/jobs/doesnotexist").status_code == 404
