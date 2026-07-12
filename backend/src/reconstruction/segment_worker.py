"""Run scene segmentation in a child process (crash isolation, like volume).

    python -m reconstruction.segment_worker <ply_path> <output_dir|-> <result_json>
"""

import json
import sys
from pathlib import Path

from reconstruction.segmentation import segment_scene


def main() -> int:
    ply_path = Path(sys.argv[1])
    output_dir = None if sys.argv[2] == "-" else Path(sys.argv[2])
    result_json = Path(sys.argv[3])

    def progress(phase: str) -> None:
        print(f"PROGRESS:{phase}", flush=True)

    try:
        result = segment_scene(ply_path, output_dir=output_dir, on_progress=progress)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR:{exc}", flush=True)
        return 2

    result_json.write_text(
        json.dumps(
            {
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
                "cloud_path": str(result.cloud_path),
                "labels_path": str(result.labels_path),
                "class_clouds": {k: str(p) for k, p in result.class_cloud_paths.items()},
                "up_vector": list(result.up_vector),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
