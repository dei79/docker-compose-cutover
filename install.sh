#!/usr/bin/env bash
# Install the docker-cutover CLI plugin without cloning the repo.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/dei79/docker-compose-cutover/main/install.sh | bash
#
# Downloads the latest tagged release (falls back to the main branch if none
# exists yet) and installs it into ~/.docker/cli-plugins/, the same place
# `scripts/install-plugin.sh` symlinks to from a local checkout. Set
# DOCKER_CLI_PLUGIN_DIR to install somewhere else (e.g. a system-wide dir).
set -euo pipefail

REPO="dei79/docker-compose-cutover"
PLUGIN_DIR="${DOCKER_CLI_PLUGIN_DIR:-$HOME/.docker/cli-plugins}"

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
# installs straight from the source tarball, so do the same stamp here.
case "$ref" in
    v[0-9]*)
        sed -i.bak "s/\"Version\": \"[^\"]*\"/\"Version\": \"${ref#v}\"/" \
            "$srcdir/cli-plugins/bgswitch/cli.py"
        rm -f "$srcdir/cli-plugins/bgswitch/cli.py.bak"
        ;;
esac

mkdir -p "$PLUGIN_DIR"
rm -rf "$PLUGIN_DIR/bgswitch"
cp "$srcdir/cli-plugins/docker-cutover" "$PLUGIN_DIR/docker-cutover"
cp -r "$srcdir/cli-plugins/bgswitch" "$PLUGIN_DIR/bgswitch"
find "$PLUGIN_DIR/bgswitch" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
chmod 755 "$PLUGIN_DIR/docker-cutover"

echo "Installed: $PLUGIN_DIR/docker-cutover"
echo "Try it: docker cutover doctor"
