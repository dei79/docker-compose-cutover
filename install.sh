#!/usr/bin/env bash
# Install the docker-cutover CLI plugin without cloning the repo.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/dei79/docker-compose-cutover/main/install.sh | bash
#
# Downloads the latest tagged release (falls back to the main branch if none
# exists yet) into a versioned directory under $CUTOVER_HOME, then points
# ~/.docker/cli-plugins/docker-cutover at it with `ln -sf`. Re-running this
# - even over a symlink left by a previous run, or by a local dev checkout's
# scripts/install-plugin.sh - always replaces that link outright: `cp` onto
# an existing symlink follows it and silently overwrites whatever it points
# at instead of replacing the link itself, which is what bit us before.
set -euo pipefail

REPO="dei79/docker-compose-cutover"
PLUGIN_DIR="${DOCKER_CLI_PLUGIN_DIR:-$HOME/.docker/cli-plugins}"
CUTOVER_HOME="${CUTOVER_HOME:-$HOME/.docker/cutover}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 is required but was not found on PATH." >&2
    exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "warning: docker was not found on PATH; install/start Docker Desktop first." >&2
fi

# Prefer the latest tagged release; an empty result (no releases yet, or the
# API call failed) falls back to the main branch.
ref="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
    | python3 -c 'import json, sys
try:
    print(json.load(sys.stdin).get("tag_name", ""))
except ValueError:
    pass' 2>/dev/null || true)"
ref="${ref:-main}"

echo "Installing docker-cutover from $REPO@$ref ..."

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

curl -fsSL "https://github.com/$REPO/archive/refs/tags/$ref.tar.gz" -o "$workdir/src.tar.gz" 2>/dev/null \
    || curl -fsSL "https://github.com/$REPO/archive/refs/heads/$ref.tar.gz" -o "$workdir/src.tar.gz"

tar -xzf "$workdir/src.tar.gz" -C "$workdir"
srcdir="$(find "$workdir" -mindepth 1 -maxdepth 1 -type d)"

# The checked-in source always says "0.0.0-dev" (see cli-plugins/bgswitch/cli.py);
# release.yml stamps the real version into the .deb it builds, but this script
# installs straight from the source tarball, so do the same stamp here. A
# plain branch install (no tag) has no meaningful version number, so it just
# gets a timestamp - good enough to tell two such installs apart.
case "$ref" in
    v[0-9]*)
        version="${ref#v}"
        sed -i.bak "s/\"Version\": \"[^\"]*\"/\"Version\": \"${version}\"/" \
            "$srcdir/cli-plugins/bgswitch/cli.py"
        rm -f "$srcdir/cli-plugins/bgswitch/cli.py.bak"
        ;;
    *)
        version="${ref}-$(date +%Y%m%d%H%M%S)"
        ;;
esac

# Install into a versioned directory first; multiple versions can coexist
# under $CUTOVER_HOME/versions/ (handy to roll back: just re-point the
# symlink below at an older one), and the plugin dir only ever holds a
# symlink to whichever one is currently active.
version_dir="$CUTOVER_HOME/versions/$version"
rm -rf "$version_dir"
mkdir -p "$version_dir"
cp "$srcdir/cli-plugins/docker-cutover" "$version_dir/docker-cutover"
cp -r "$srcdir/cli-plugins/bgswitch" "$version_dir/bgswitch"
find "$version_dir/bgswitch" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
chmod 755 "$version_dir/docker-cutover"

mkdir -p "$PLUGIN_DIR"
rm -f "$PLUGIN_DIR/docker-cutover"
ln -s "$version_dir/docker-cutover" "$PLUGIN_DIR/docker-cutover"

echo "Installed docker-cutover $version"
echo "  $version_dir  (versioned copy)"
echo "  $PLUGIN_DIR/docker-cutover -> $version_dir/docker-cutover"
echo "Try it: docker cutover doctor"
