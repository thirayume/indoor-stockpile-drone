"""Run scene segmentation in a child process (crash isolation, like volume).

    python -m reconstruction.segment_worker <ply_path> <output_dir|-> <result_json>
        [--mode geometry|ml] [--classes <JSON array of prompt strings>]

geometry: the heuristic colour+shape mode (segmentation.segment_scene).
ml:       open-vocabulary model mode (ml_segmentation.segment_scene_ml);
          --classes '["car","pile of sand"]' switches YOLOE to text prompts,
          omitted/empty -> the prompt-free auto-detect model.
"""

import argparse
import json
from pathlib import Path

from reconstruction.segmentation import (
    SegmentationResult,
    is_object_class,
    segment_scene,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ply_path", type=Path)
    parser.add_argument("output_dir", help='output directory, or "-" for the PLY\'s folder')
    parser.add_argument("result_json", type=Path)
    parser.add_argument("--mode", choices=("geometry", "ml"), default="geometry")
    parser.add_argument(
        "--classes",
        default="",
        help="JSON array of class prompts (ml mode); empty = auto-detect",
    )
    return parser.parse_args(argv)


def result_payload(result: SegmentationResult) -> dict:
    """JSON-safe result dict; `classes` carries the run's dynamic class set."""
    return {
        "counts": result.counts,
        "point_counts": result.point_counts,
        "objects": [
            {
                "label": o.label,
                "volume_m3": o.volume_m3,
                "num_points": o.num_points,
                "north_m": o.north_m,
                "east_m": o.east_m,
            }
            for o in result.objects
        ],
        "classes": [
            {
                "key": key,
                "color": list(result.colors[key]),
                "is_object": is_object_class(key),
                "point_count": result.point_counts.get(key, 0),
            }
            for key in result.classes
        ],
        "cloud_path": str(result.cloud_path),
        "labels_path": str(result.labels_path),
        "class_clouds": {k: str(p) for k, p in result.class_cloud_paths.items()},
        "up_vector": list(result.up_vector),
    }


def main(argv: list[str] | None = None) -> int:
    import sys

    args = parse_args(sys.argv[1:] if argv is None else argv)
    output_dir = None if args.output_dir == "-" else Path(args.output_dir)

    def progress(phase: str) -> None:
        print(f"PROGRESS:{phase}", flush=True)

    try:
        if args.mode == "ml":
            from reconstruction.ml_segmentation import segment_scene_ml

            prompts = [str(c) for c in json.loads(args.classes)] if args.classes else None
            result = segment_scene_ml(
                args.ply_path,
                output_dir=output_dir,
                class_prompts=prompts,
                on_progress=progress,
            )
        else:
            result = segment_scene(args.ply_path, output_dir=output_dir, on_progress=progress)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR:{exc}", flush=True)
        return 2

    args.result_json.write_text(json.dumps(result_payload(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
