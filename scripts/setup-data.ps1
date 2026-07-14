# Fetch the source datasets so a fresh clone reconstructs identically.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup-data.ps1
#
# Idempotent: clones each dataset repo into data/odm/<name> and checks out the
# commit pinned in scripts/datasets.tsv, so every machine starts from the exact
# same images. Safe to re-run — it only fetches what is missing or out of date.
# This fetches INPUT images only; run a reconstruction in the app (or the CLI)
# to produce data/opensfm_project/ on the new machine.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$odmDir = Join-Path $repoRoot "data\odm"
$manifest = Join-Path $PSScriptRoot "datasets.tsv"

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "git is not on PATH." }

# The ODMdata catalog is a submodule; make sure it is present first.
Write-Host "==> Initialising the ODMdata submodule" -ForegroundColor Cyan
git -C $repoRoot submodule update --init data/odm
if (-not (Test-Path $odmDir)) { Fail "data/odm missing after submodule init." }

foreach ($line in Get-Content $manifest) {
    $t = $line.Trim()
    if ($t -eq "" -or $t.StartsWith("#")) { continue }
    $name, $url, $commit = $t -split "`t"
    $dest = Join-Path $odmDir $name

    Write-Host "==> $name" -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $dest ".git"))) {
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
        git clone $url $dest
    }
    git -C $dest fetch --depth 1 origin $commit
    git -C $dest checkout --quiet $commit

    # Count image files. Note: Get-ChildItem -Include matches nothing unless the
    # path ends in a wildcard or -Recurse is used, so filter by extension here.
    $imagesDir = Join-Path $dest "images"
    $imageExts = @(".jpg", ".jpeg", ".png", ".tif", ".tiff")
    $count = (Get-ChildItem $imagesDir -File -ErrorAction SilentlyContinue |
        Where-Object { $imageExts -contains $_.Extension.ToLower() } | Measure-Object).Count
    if ($count -eq 0) { Fail "$name has no images at $imagesDir" }
    Write-Host "    $count images @ $($commit.Substring(0,8))" -ForegroundColor Green
}

Write-Host "`nAll datasets ready under data/odm/." -ForegroundColor Green
Write-Host "Next: start the app (docker compose up -d) and run a reconstruction," -ForegroundColor Green
Write-Host "or from backend/: python -m reconstruction.dataset_utils list" -ForegroundColor Green
