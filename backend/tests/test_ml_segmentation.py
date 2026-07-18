"""ML segmentation: registry, slug/vote maths, worker args, full synthetic run.

The full-pipeline test injects a fake inference function, so none of these
tests need ultralytics/torch installed.
"""

import json
import math
from pathlib import Path

import numpy as np
import open3d as o3d
import pytest

from reconstruction.ml_segmentation import (
    InferenceMaps,
    _labels_from_votes,
    _slug,
    segment_scene_ml,
)
from reconstruction.segment_worker import parse_args
from reconstruction.segmentation import (
    CLASS_COLORS,
    CLASSES,
    OBJECT_CLASSES,
    is_object_class,
    load_class_registry,
    write_class_registry,
)

# ---------------------------------------------------------------------------
# Class registry
# ---------------------------------------------------------------------------


def test_registry_round_trip(tmp_path: Path) -> None:
    classes = ["car", "pile_of_sand", "road", "other"]
    colors = {k: (0.1 * i, 0.2, 0.3) for i, k in enumerate(classes)}
    write_class_registry(tmp_path, classes, colors)

    got_classes, got_colors, got_objects = load_class_registry(tmp_path)
    assert got_classes == classes
    assert got_colors["pile_of_sand"] == pytest.approx((0.1, 0.2, 0.3))
    assert got_objects == {"car", "pile_of_sand"}


def test_registry_fallback_is_static_classes(tmp_path: Path) -> None:
    classes, colors, objects = load_class_registry(tmp_path)
    assert classes == list(CLASSES)
    assert colors == CLASS_COLORS
    assert objects == set(OBJECT_CLASSES)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("car", True),
        ("pile_of_sand", True),  # a pile OF a surface material is an object
        ("heap_of_gravel", True),
        ("road", False),
        ("water", False),
        ("pond", False),
        ("other", False),
        ("umbrella", True),  # unknown words default to object
    ],
)
def test_is_object_class(key: str, expected: bool) -> None:
    assert is_object_class(key) is expected


def test_slug_makes_safe_keys() -> None:
    assert _slug("Pile of Sand") == "pile_of_sand"
    assert _slug("  car ") == "car"
    assert _slug("///") == "unknown"


# ---------------------------------------------------------------------------
# Vote -> label maths
# ---------------------------------------------------------------------------


def test_vote_majority_and_threshold() -> None:
    # 40 points clearly car, 40 points tree-vs-car majority, 10 points with
    # votes too weak to label (sparse-class folding needs >=30 pts per class).
    car = np.concatenate([np.full(40, 0.9), np.full(40, 0.4), np.full(10, 0.3)])
    tree = np.concatenate([np.zeros(40), np.full(40, 0.6), np.full(10, 0.2)])
    votes = {"car": car.astype(np.float32), "tree": tree.astype(np.float32)}
    labels, classes = _labels_from_votes(votes, 90)

    # Ranked by total vote mass (car > tree), "other" always last.
    assert classes == ["car", "tree", "other"]
    assert (labels[:40] == classes.index("car")).all()  # strong, unanimous
    assert (labels[40:80] == classes.index("tree")).all()  # 0.6 beats 0.4
    assert (labels[80:] == classes.index("other")).all()  # 0.3 < MIN_VOTE_SCORE


def test_no_kept_classes_all_other() -> None:
    labels, classes = _labels_from_votes({"other": np.ones(4, dtype=np.float32)}, 4)
    assert classes == ["other"]
    assert (labels == 0).all()


def test_sparse_classes_fold_into_other() -> None:
    # "boat" wins only 2 points — below MIN_CLUSTER_POINTS — so it must not
    # survive as a class; "tree" wins 40 points and stays.
    votes = {
        "tree": np.concatenate([np.full(40, 0.9), np.zeros(2)]).astype(np.float32),
        "boat": np.concatenate([np.zeros(40), np.full(2, 0.9)]).astype(np.float32),
    }
    labels, classes = _labels_from_votes(votes, 42)
    assert classes == ["tree", "other"]
    assert (labels[:40] == 0).all()
    assert (labels[40:] == 1).all()  # folded into other


# ---------------------------------------------------------------------------
# Worker CLI arguments
# ---------------------------------------------------------------------------


def test_worker_args_default_geometry() -> None:
    args = parse_args(["cloud.ply", "-", "result.json"])
    assert args.mode == "geometry"
    assert args.classes == ""


def test_worker_args_ml_with_classes() -> None:
    args = parse_args(
        ["cloud.ply", "out", "r.json", "--mode", "ml", "--classes", '["car", "pile of sand"]']
    )
    assert args.mode == "ml"
    assert json.loads(args.classes) == ["car", "pile of sand"]


# ---------------------------------------------------------------------------
# Full pipeline on a synthetic scene with a fake model
# ---------------------------------------------------------------------------

_IMG = 1000  # synthetic camera/mask resolution


def _make_scene(tmp: Path) -> tuple[Path, Path]:
    """Flat floor + a dense box (the "car"), plus a two-shot OpenSfM project.

    Both cameras hang nadir ~8 units above the origin (rotation = 180 deg
    about x maps world +z up to camera -z, OpenSfM convention).
    """
    step = 0.02
    xs = np.arange(-2.0, 2.0, step)
    floor = np.stack(np.meshgrid(xs, xs, indexing="ij"), axis=-1).reshape(-1, 2)
    floor = np.column_stack([floor, np.zeros(len(floor))])

    b = np.arange(-0.3, 0.3, step)
    top = np.stack(np.meshgrid(b, b, indexing="ij"), axis=-1).reshape(-1, 2)
    top = np.column_stack([top, np.full(len(top), 0.5)])
    zs = np.arange(step, 0.5, step)
    side_strips = []
    for edge in (-0.3, 0.3):
        for z in zs:
            side_strips.append(np.column_stack([b, np.full(len(b), edge), np.full(len(b), z)]))
            side_strips.append(np.column_stack([np.full(len(b), edge), b, np.full(len(b), z)]))
    pts = np.vstack([floor, top, *side_strips])

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    pcd.colors = o3d.utility.Vector3dVector(np.full_like(pts, 0.5))
    ply = tmp / "merged.ply"
    o3d.io.write_point_cloud(str(ply), pcd)

    project = tmp / "project"
    (project / "images").mkdir(parents=True)
    shots = {}
    for i, tx in enumerate((0.0, 0.1)):
        name = f"img{i}.jpg"
        (project / "images" / name).write_bytes(b"fake")
        shots[name] = {"camera": "cam", "rotation": [math.pi, 0.0, 0.0],
                       "translation": [tx, 0.0, 8.0]}
    (project / "reconstruction.json").write_text(
        json.dumps(
            [
                {
                    "cameras": {
                        "cam": {
                            "projection_type": "perspective",
                            "focal": 1.0,
                            "k1": 0.0,
                            "k2": 0.0,
                            "width": _IMG,
                            "height": _IMG,
                        }
                    },
                    "shots": shots,
                }
            ]
        )
    )
    return ply, project


def _fake_infer(_photo: Path) -> InferenceMaps:
    """Every photo "detects" a Car in a disc around the image centre."""
    yy, xx = np.ogrid[:_IMG, :_IMG]
    disc = (xx - (_IMG - 1) / 2) ** 2 + (yy - (_IMG - 1) / 2) ** 2 < 60**2
    class_map = np.where(disc, 0, -1).astype(np.int32)
    conf_map = np.where(disc, 0.9, 0.0).astype(np.float32)
    return InferenceMaps(class_map, conf_map, {0: "Car"}, gain=1.0, pad=(0.0, 0.0))


def test_segment_scene_ml_synthetic_end_to_end(tmp_path: Path) -> None:
    ply, project = _make_scene(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    phases: list[str] = []

    result = segment_scene_ml(
        ply,
        project_dir=project,
        output_dir=out,
        on_progress=phases.append,
        infer=_fake_infer,
    )

    assert result.classes[-1] == "other"
    assert "car" in result.classes  # slugged + lowercased from "Car"
    assert result.counts["car"] == 1  # one box, one cluster — seen in 2 photos
    [car] = [o for o in result.objects if o.label == "car"]
    assert 0.03 < car.volume_m3 < 0.5  # true box volume is 0.6*0.6*0.5 = 0.18
    assert result.point_counts["other"] > result.point_counts["car"]

    # Artefacts every view consumes: registry, per-class cloud, labels archive.
    assert (out / "seg_classes.json").is_file()
    assert (out / "seg_car.ply").is_file()
    npz = np.load(out / "labels.npz")
    assert [str(c) for c in npz["classes"]] == list(result.classes)
    assert any("detecting objects" in p for p in phases)


def test_segment_scene_ml_no_detections_raises(tmp_path: Path) -> None:
    ply, project = _make_scene(tmp_path)
    with pytest.raises(ValueError, match="detected nothing"):
        segment_scene_ml(ply, project_dir=project, output_dir=tmp_path, infer=lambda _p: None)
