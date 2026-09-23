#!/usr/bin/env bash
# Reset the blue/green demo to a clean starting state: blue running the
# given image (default the published ghcr.io demo image, tag 1.0.0), green
# stopped, nginx pointing at blue. Works both for the very first setup and
# for resetting later - there is nothing to do beforehand. Requires the
# docker-cutover plugin to be installed (scripts/install-plugin.sh).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/demo-deploy"

IMAGE_REF="${1:-ghcr.io/dei79/docker-compose-cutover-demo:1.0.0}"
# Simple last-colon split; good enough for this demo's image references
# (does not handle a registry host with a port, unlike the docker-cutover plugin).
IMAGE_NAME="${IMAGE_REF%:*}"
VERSION="${IMAGE_REF##*:}"
if [ "$IMAGE_NAME" = "$IMAGE_REF" ]; then
    echo "Image reference must be NAME:TAG, e.g. ghcr.io/dei79/docker-compose-cutover-demo:1.0.0" >&2
    exit 1
fi

cd "$DEPLOY_DIR"

echo "Stopping any running demo..."
docker cutover down --force

echo "Resetting .env..."
cat > .env <<EOF
BLUE_IMAGE=${IMAGE_NAME}
BLUE_VERSION=${VERSION}
GREEN_IMAGE=${IMAGE_NAME}
GREEN_VERSION=${VERSION}

# Required by 'docker cutover doctor' / 'docker cutover <image:tag>'.
NGINX_UPSTREAM_CONF=nginx/conf.d/upstream.conf
NGINX_RELOAD_CMD=nginx -s reload
EOF

echo "Resetting NGINX upstream to blue..."
printf 'upstream backend {\n    zone backend 64k;\n    server app-blue:8080 resolve;\n}\n' \
    > nginx/conf.d/upstream.conf

docker compose config --quiet

# A locally built tag (e.g. from scripts/build.py) is used as-is; anything
# not already present locally is assumed to be a registry reference and
# pulled - the published demo image by default.
if docker image inspect "$IMAGE_REF" >/dev/null 2>&1; then
    echo "${IMAGE_REF} is already available locally."
else
    echo "Pulling ${IMAGE_REF}..."
    docker pull "$IMAGE_REF"
fi

echo "Starting nginx + app-blue..."
docker cutover up

echo "Waiting for NGINX to serve traffic..."
for _ in $(seq 1 10); do
    curl -sf http://localhost:8080/health >/dev/null 2>&1 && break
    sleep 1
done

echo
echo "Demo reset. Current state:"
python3 "$REPO_ROOT/scripts/status.py"
