from pathlib import Path

from reconstruction.dataset_utils import (
    list_odm_datasets,
    opensfm_config,
    prepare_opensfm_project,
)


def _make_dataset(odm_dir: Path, name: str) -> None:
    images = odm_dir / name / "images"
    images.mkdir(parents=True)
    (images / "a.jpg").write_bytes(b"not-a-real-jpg")


def test_list_only_returns_folders_with_images(tmp_path) -> None:
    _make_dataset(tmp_path, "demo")
    (tmp_path / "no-images-here").mkdir()
    assert list_odm_datasets(odm_dir=tmp_path) == ["demo"]


def test_prepare_copies_images(tmp_path) -> None:
    odm = tmp_path / "odm"
    project = tmp_path / "project"
    _make_dataset(odm, "demo")

    prepare_opensfm_project("demo", odm_dir=odm, project_dir=project, use_symlink=False)

    assert (project / "images" / "a.jpg").is_file()
    assert (project / "config.yaml").is_file()


def test_prepare_removes_empty_gcp_file(tmp_path) -> None:
    # An empty gcp_list.txt crashes OpenSfM's parser; prepare must drop it.
    odm = tmp_path / "odm"
    project = tmp_path / "project"
    _make_dataset(odm, "demo")
    project.mkdir()
    (project / "gcp_list.txt").write_text("")

    prepare_opensfm_project("demo", odm_dir=odm, project_dir=project, use_symlink=False)

    assert not (project / "gcp_list.txt").exists()


def test_prepare_keeps_populated_gcp_file(tmp_path) -> None:
    odm = tmp_path / "odm"
    project = tmp_path / "project"
    _make_dataset(odm, "demo")
    project.mkdir()
    (project / "gcp_list.txt").write_text("WGS84\n1 2 3 100 200 a.jpg\n")

    prepare_opensfm_project("demo", odm_dir=odm, project_dir=project, use_symlink=False)

    assert (project / "gcp_list.txt").is_file()


def test_config_gps_denied_by_default() -> None:
    cfg = opensfm_config(use_exif_gps=False)
    assert "bundle_use_gps: no" in cfg
    assert "align_method: naive" in cfg


def test_config_gps_enabled() -> None:
    cfg = opensfm_config(use_exif_gps=True)
    assert "bundle_use_gps: yes" in cfg
    assert "use_altitude_tag: yes" in cfg
    assert "bundle_use_gps: no" not in cfg


def test_prepare_writes_gps_config_when_requested(tmp_path) -> None:
    odm = tmp_path / "odm"
    project = tmp_path / "project"
    _make_dataset(odm, "demo")

    prepare_opensfm_project(
        "demo", odm_dir=odm, project_dir=project, use_symlink=False, use_exif_gps=True
    )

    assert "bundle_use_gps: yes" in (project / "config.yaml").read_text()
