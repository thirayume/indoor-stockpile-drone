"""Dataset image endpoints, against a temporary dataset with a real JPEG."""

import io

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.config import settings

client = TestClient(app)


@pytest.fixture()
def fake_dataset(monkeypatch, tmp_path):
    from PIL import Image

    images = tmp_path / "odm" / "demo" / "images"
    images.mkdir(parents=True)
    Image.new("RGB", (64, 48), color=(200, 60, 60)).save(images / "a.jpg", format="JPEG")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return "demo"


def test_list_images(fake_dataset) -> None:
    response = client.get(f"/datasets/{fake_dataset}/images")
    assert response.status_code == 200
    assert response.json() == {"dataset_id": "demo", "images": ["a.jpg"]}


def test_get_image_full_size(fake_dataset) -> None:
    response = client.get(f"/datasets/{fake_dataset}/images/a.jpg")
    assert response.status_code == 200
    assert response.content[:2] == b"\xff\xd8"  # JPEG magic


def test_get_image_thumbnail(fake_dataset) -> None:
    from PIL import Image

    response = client.get(f"/datasets/{fake_dataset}/images/a.jpg?width=32")
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as im:
        assert im.width == 32


def test_unknown_dataset_returns_404(fake_dataset) -> None:
    assert client.get("/datasets/nope/images").status_code == 404


def test_unknown_image_returns_404(fake_dataset) -> None:
    assert client.get(f"/datasets/{fake_dataset}/images/other.jpg").status_code == 404


def test_traversal_is_rejected(fake_dataset) -> None:
    # `..` can never appear in the directory-listing whitelist
    assert client.get(f"/datasets/{fake_dataset}/images/..").status_code == 404
