#!/usr/bin/env bash
# Build a .deb package for the docker-cutover CLI plugin, installable with
# `sudo apt-get install ./dist/docker-compose-cutover_<version>_all.deb`
# (or `sudo dpkg -i ...` + `sudo apt-get install -f` to pull in python3).
# No PPA or APT repo needed - the .deb is fully self-contained.
#
# Usage: packaging/deb/build.sh [version]
# The release workflow always passes the version derived from the git tag.
# Without an argument (manual/local builds), it falls back to `git describe`
# so there is no separate VERSION file to keep in sync by hand.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ -n "${1:-}" ]; then
    VERSION="$1"
elif DESCRIBE="$(git -C "$ROOT" describe --tags --dirty 2>/dev/null)"; then
    # A real vX.Y.Z tag is reachable: use it (dpkg accepts the extra
    # "-<n>-g<sha>" git-describe suffix as its debian_revision part).
    VERSION="${DESCRIBE#v}"
else
    # No tag at all yet - Debian versions must start with a digit, so this
    # can't just be the raw commit hash.
    SHA="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    DIRTY=""
    git -C "$ROOT" diff --quiet 2>/dev/null || DIRTY=".dirty"
    VERSION="0.0.0+${SHA}${DIRTY}"
fi
PKG_NAME="docker-compose-cutover"
ARCH="all"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

PLUGIN_DIR="$STAGE/usr/lib/docker/cli-plugins"
DOC_DIR="$STAGE/usr/share/doc/$PKG_NAME"
mkdir -p "$PLUGIN_DIR" "$DOC_DIR" "$STAGE/DEBIAN"

# The installed binary is still named docker-cutover: that filename is what
# Docker's CLI plugin protocol uses to expose it as `docker cutover ...`.
# The .deb package name is independent of that, same as e.g. Debian's
# docker-compose-plugin package installing a binary named docker-compose.
cp "$ROOT/cli-plugins/docker-cutover" "$PLUGIN_DIR/docker-cutover"
cp -r "$ROOT/cli-plugins/bgswitch" "$PLUGIN_DIR/bgswitch"
find "$PLUGIN_DIR/bgswitch" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
chmod 755 "$PLUGIN_DIR/docker-cutover"
find "$PLUGIN_DIR/bgswitch" -type f -exec chmod 644 {} \;

cp "$ROOT/README.md" "$ROOT/LICENSE" "$DOC_DIR/"

SIZE_KB=$(du -sk "$STAGE/usr" | cut -f1)

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $VERSION
Section: admin
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.9)
Recommends: docker.io | docker-ce-cli
Installed-Size: $SIZE_KB
Maintainer: cutover contributors <noreply@example.com>
Homepage: https://github.com/
Description: Zero-downtime blue/green deploys for docker compose (docker cutover)
 Installs the "docker cutover" Docker CLI plugin: docker cutover doctor
 validates a compose project's blue/green setup, and
 docker cutover <image>:<tag> switches the project's compose service
 between a blue and a green slot behind NGINX with zero dropped
 requests - health-checking the new slot, draining the old slot's
 in-flight requests, and rolling back automatically on failure.
EOF

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/${PKG_NAME}_${VERSION}_${ARCH}.deb"
rm -f "$OUT"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT" >/dev/null
echo "Built: $OUT"
