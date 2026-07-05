from pathlib import Path

from reconstruction.dataset_utils import list_odm_datasets, prepare_opensfm_project


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
