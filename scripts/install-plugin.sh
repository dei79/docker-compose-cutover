#!/usr/bin/env bash
# Install the docker-cutover CLI plugin for the current user.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="${DOCKER_CLI_PLUGIN_DIR:-$HOME/.docker/cli-plugins}"

mkdir -p "$PLUGIN_DIR"
ln -sf "$ROOT/cli-plugins/docker-cutover" "$PLUGIN_DIR/docker-cutover"
chmod +x "$ROOT/cli-plugins/docker-cutover"

echo "Installed: $PLUGIN_DIR/docker-cutover -> $ROOT/cli-plugins/docker-cutover"
echo "Try it: docker cutover doctor"
