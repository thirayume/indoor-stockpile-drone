"""Run the Open3D volume computation in a child process.

Open3D's native code can segfault on degenerate/unsuitable point clouds
(e.g. a scene with no real stockpile). In-process that would crash the whole
API; run here as a subprocess so the parent can turn a crash into a clean
job error. Invoked as:

    python -m reconstruction.volume_worker <ply_path> <output_dir|-> <result_json>

Progress phases are printed to stdout as "PROGRESS:<phase>"; a handled error
as "ERROR:<message>" (exit 2). Success writes the result JSON and exits 0.
"""

import json
import sys
from pathlib import Path

from reconstruction.volume_compute import compute_volume


def main() -> int:
    ply_path = Path(sys.argv[1])
    output_dir = None if sys.argv[2] == "-" else Path(sys.argv[2])
    result_json = Path(sys.argv[3])

    def progress(phase: str) -> None:
        print(f"PROGRESS:{phase}", flush=True)

    try:
        result = compute_volume(ply_path, output_dir=output_dir, on_progress=progress)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR:{exc}", flush=True)
        return 2

    result_json.write_text(
        json.dumps(
            {
                "volume_m3": result.volume_m3,
                "num_points": result.num_points,
                "method": result.method,
                "point_cloud_path": str(result.point_cloud_path),
                "mesh_path": str(result.mesh_path) if result.mesh_path else None,
                "up_vector": list(result.up_vector) if result.up_vector else None,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
