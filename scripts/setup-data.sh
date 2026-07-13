#!/usr/bin/env bash
# Fetch the source datasets so a fresh clone reconstructs identically.
#
#   bash scripts/setup-data.sh
#
# Idempotent: clones each dataset repo into data/odm/<name> and checks out the
# commit pinned in scripts/datasets.tsv, so every machine starts from the exact
# same images. Safe to re-run — it only fetches what is missing or out of date.
# This fetches INPUT images only; run a reconstruction in the app (or the CLI)
# to produce data/opensfm_project/ on the new machine.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname "$script_dir")"
odm_dir="$repo_root/data/odm"
manifest="$script_dir/datasets.tsv"

command -v git >/dev/null || { echo "ERROR: git is not on PATH." >&2; exit 1; }

echo "==> Initialising the ODMdata submodule"
git -C "$repo_root" submodule update --init data/odm
[ -d "$odm_dir" ] || { echo "ERROR: data/odm missing after submodule init." >&2; exit 1; }

while IFS=$'\t' read -r name url commit; do
    [ -z "$name" ] && continue
    case "$name" in \#*) continue;; esac
    dest="$odm_dir/$name"

    echo "==> $name"
    if [ ! -d "$dest/.git" ]; then
        rm -rf "$dest"
        git clone "$url" "$dest"
    fi
    git -C "$dest" fetch --depth 1 origin "$commit"
    git -C "$dest" checkout --quiet "$commit"

    count=$(find "$dest/images" -maxdepth 1 -type f \
        \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) 2>/dev/null | wc -l)
    [ "$count" -gt 0 ] || { echo "ERROR: $name has no images at $dest/images" >&2; exit 1; }
    echo "    $count images @ ${commit:0:8}"
done < "$manifest"

echo
echo "All datasets ready under data/odm/."
echo "Next: start the app (docker compose up -d) and run a reconstruction,"
echo "or from backend/: python -m reconstruction.dataset_utils list"
