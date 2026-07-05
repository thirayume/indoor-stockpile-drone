#!/usr/bin/env python3
"""Fetch OpenSfM reference material into docs/opensfm/.

Downloads (standard library only, no third-party dependencies):
  - opensfm-docs.pdf     official documentation PDF (Read the Docs build;
                         opensfm.org itself publishes no PDF)
  - default_config.py    opensfm/config.py from GitHub: the OpenSfMConfig
                         dataclass holding every option, its default and a
                         doc comment — the config reference page is gone
                         from opensfm.org, so the source is authoritative
  - dataset.html         the dataset-structure docs page from opensfm.org

Existing files are kept unless --force is given.

Usage:
    python tools/download_refs.py [--dest DIR] [--force]
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = REPO_ROOT / "docs" / "opensfm"

DOCS_PDF_URL = "https://opensfm.readthedocs.io/_/downloads/en/latest/pdf/"
DATASET_DOCS_URL = "https://opensfm.org/docs/dataset.html"
# opensfm/config.py embeds the full default config.yaml; try the repo's
# default branch first, then the legacy branch name.
CONFIG_PY_URLS = [
    "https://raw.githubusercontent.com/mapillary/OpenSfM/main/opensfm/config.py",
    "https://raw.githubusercontent.com/mapillary/OpenSfM/master/opensfm/config.py",
]

USER_AGENT = "indoor-stockpile-drone/0.1 (OpenSfM reference fetcher)"
TIMEOUT_S = 60


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return response.read()


def save(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_bytes(data)
    part.replace(dest)  # no truncated file left behind on interrupt
    print(f"  wrote {dest.relative_to(REPO_ROOT)} ({len(data):,} bytes)")


def _skip_existing(dest: Path, force: bool) -> bool:
    if dest.exists() and not force:
        print(f"  {dest.relative_to(REPO_ROOT)} exists, skipping (--force to refresh)")
        return True
    return False


def download_docs_pdf(dest_dir: Path, force: bool) -> bool:
    dest = dest_dir / "opensfm-docs.pdf"
    if _skip_existing(dest, force):
        return True
    try:
        data = fetch(DOCS_PDF_URL)
    except OSError as exc:
        print(f"  FAILED to download docs PDF: {exc}", file=sys.stderr)
        return False
    if not data.startswith(b"%PDF"):
        print(f"  FAILED: {DOCS_PDF_URL} did not return a PDF", file=sys.stderr)
        return False
    save(dest, data)
    return True


def download_default_config(dest_dir: Path, force: bool) -> bool:
    dest = dest_dir / "default_config.py"
    if _skip_existing(dest, force):
        return True
    for url in CONFIG_PY_URLS:
        try:
            source = fetch(url).decode("utf-8")
        except OSError as exc:
            print(f"  {url} failed: {exc}", file=sys.stderr)
            continue
        if "OpenSfMConfig" not in source and "default_config" not in source:
            print(f"  {url} does not look like OpenSfM's config module", file=sys.stderr)
            continue
        header = (
            f"# OpenSfM configuration reference, fetched from\n"
            f"# {url}\n"
            f"# by tools/download_refs.py — every config.yaml option, its default\n"
            f"# value and a doc comment. Regenerate rather than edit.\n\n"
        )
        save(dest, (header + source).encode("utf-8"))
        return True
    return False


def download_dataset_docs(dest_dir: Path, force: bool) -> bool:
    dest = dest_dir / "dataset.html"
    if _skip_existing(dest, force):
        return True
    try:
        data = fetch(DATASET_DOCS_URL)
    except OSError as exc:
        print(f"  FAILED to download dataset docs: {exc}", file=sys.stderr)
        return False
    save(dest, data)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                        help=f"output directory (default: {DEFAULT_DEST})")
    parser.add_argument("--force", action="store_true",
                        help="re-download artifacts that already exist")
    args = parser.parse_args()

    print(f"Fetching OpenSfM reference material into {args.dest}")
    results = {
        "documentation PDF": download_docs_pdf(args.dest, args.force),
        "default config.yaml": download_default_config(args.dest, args.force),
        "dataset docs page": download_dataset_docs(args.dest, args.force),
    }

    failed = [name for name, ok in results.items() if not ok]
    if failed:
        print(f"\nDone with errors — failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
