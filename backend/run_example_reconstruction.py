#!/usr/bin/env python3
"""One-shot example: ODM dataset -> OpenSfM reconstruction -> stockpile volume.

Runs the same steps the API performs, as a plain CLI:

    python run_example_reconstruction.py                    # defaults to 'banana'
    python run_example_reconstruction.py --dataset banana
    python run_example_reconstruction.py --dataset copr --copy

Requires the `opensfm` CLI on PATH for the reconstruction step (see README,
"Note on OpenSfM"). Dataset listing and preparation work without it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Allow running as a plain script from backend/ without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from reconstruction.dataset_utils import list_odm_datasets, prepare_opensfm_project  # noqa: E402
from reconstruction.opensfm_runner import run_full_pipeline  # noqa: E402
from reconstruction.volume_compute import compute_volume  # noqa: E402

DEFAULT_DATASET = "banana"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"dataset under data/odm/ (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--copy", action="store_true", help="copy images instead of symlinking"
    )
    parser.add_argument(
        "--opensfm-bin", default="opensfm", help="OpenSfM CLI executable (default: opensfm)"
    )
    args = parser.parse_args()

    datasets = list_odm_datasets()
    print(
        "Available datasets:",
        ", ".join(datasets) if datasets else "(none — see README, section 'Datasets')",
    )

    print(f"\n[1/3] Preparing OpenSfM project for {args.dataset!r}")
    try:
        prepare_opensfm_project(args.dataset, use_symlink=not args.copy)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(
            f"error: cannot write to the OpenSfM project: {exc}\n"
            "hint: is the data mount read-only? Drop ':ro' from the volume in "
            "docker-compose.yml to run reconstructions in the container.",
            file=sys.stderr,
        )
        return 2

    print("\n[2/3] Running the OpenSfM pipeline (this can take a while)")
    try:
        point_cloud = run_full_pipeline(opensfm_bin=args.opensfm_bin)
    except RuntimeError as exc:  # opensfm binary not found
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except subprocess.CalledProcessError as exc:
        print(f"error: OpenSfM step failed: {exc}", file=sys.stderr)
        return 3
    except FileNotFoundError as exc:  # pipeline ran but produced no point cloud
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(f"Point cloud: {point_cloud}")

    print("\n[3/3] Computing stockpile volume with Open3D")
    try:
        result = compute_volume(point_cloud)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    print(
        f"\nEstimated volume: {result.volume_m3:.3f} m^3 "
        f"({result.method} method, {result.num_points} pile points)"
    )
    if result.mesh_path is not None:
        print(f"Stockpile mesh:   {result.mesh_path}")
    print(
        "Note: without GCPs the reconstruction scale is arbitrary — the volume\n"
        "is in model units^3, not true m^3 (see README, 'Scale caveat')."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
