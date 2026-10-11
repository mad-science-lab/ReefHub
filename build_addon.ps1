# Stage the ReefHub HA add-on into dist\reefhub\ - a folder ready to copy to
# the Home Assistant /addons share (\\<ha-ip>\addons).
# Local add-ons build from their own folder only, so the Python package is
# vendored in alongside the Dockerfile.
#
#   .\build_addon.ps1                       stage only
#   .\build_addon.ps1 -Deploy \\192.168.1.158\addons   stage and copy

param([string]$Deploy)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$dist = Join-Path $root "dist\reefhub"

if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
New-Item -ItemType Directory -Force $dist | Out-Null

foreach ($f in "config.yaml", "build.yaml", "CHANGELOG.md") {
    Copy-Item (Join-Path $root "addon\$f") $dist
}
Copy-Item (Join-Path $root "addon\translations") (Join-Path $dist "translations") -Recurse

# The repo Dockerfile installs from the GitHub tag; for a local build, swap in
# a version that installs the vendored copy instead.
$df = (Get-Content (Join-Path $root "addon\Dockerfile") -Raw) -replace "`r`n", "`n"
$df = [regex]::Replace($df, '(?s)# ReefHub package, installed.*?tar\.gz"\n',
    "COPY reefhub/ /opt/reefhub/reefhub/`nCOPY pyproject.toml README.md /opt/reefhub/`nRUN pip3 install --no-cache-dir --break-system-packages /opt/reefhub`n")
[System.IO.File]::WriteAllText((Join-Path $dist "Dockerfile"), $df,
    (New-Object System.Text.UTF8Encoding($false)))

# run.sh must be LF-only, no BOM, or the container won't start
$runsh = (Get-Content (Join-Path $root "addon\run.sh") -Raw) -replace "`r`n", "`n"
[System.IO.File]::WriteAllText((Join-Path $dist "run.sh"), $runsh,
    (New-Object System.Text.UTF8Encoding($false)))

# Vendor the Python package (skip caches)
Copy-Item (Join-Path $root "reefhub") (Join-Path $dist "reefhub") -Recurse
Get-ChildItem (Join-Path $dist "reefhub") -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force
Copy-Item (Join-Path $root "pyproject.toml") $dist
Copy-Item (Join-Path $root "README.md")      $dist

Write-Host "Staged add-on at: $dist"

if ($Deploy) {
    $target = Join-Path $Deploy "reefhub"
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
    Copy-Item $dist $target -Recurse
    Write-Host "Copied to: $target"
}
