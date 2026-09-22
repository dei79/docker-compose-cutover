#!/usr/bin/env bash
# Reset the blue/green demo to a clean starting state: blue running the
# given image (default bluegreen-demo:1.0.0), green stopped, nginx
# pointing at blue. Works both for the very first setup and for resetting
# later - there is nothing to do beforehand.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_ROOT/demo-deploy"

IMAGE_REF="${1:-bluegreen-demo:1.0.0}"
# Simple last-colon split; good enough for this demo's image references
# (does not handle a registry host with a port, unlike the docker-cutover plugin).
IMAGE_NAME="${IMAGE_REF%:*}"
VERSION="${IMAGE_REF##*:}"
if [ "$IMAGE_NAME" = "$IMAGE_REF" ]; then
    echo "Image reference must be NAME:TAG, e.g. bluegreen-demo:1.0.0" >&2
    exit 1
fi

cd "$DEPLOY_DIR"

echo "Stopping any running demo..."
docker compose down

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

echo "Building ${IMAGE_REF}..."
python3 "$REPO_ROOT/scripts/build.py" "$IMAGE_REF"

echo "Starting nginx + app-blue..."
docker compose up -d nginx app-blue

echo "Waiting for app-blue to become healthy..."
for _ in $(seq 1 30); do
    status=$(docker inspect --format '{{.State.Health.Status}}' bluegreen-demo-app-blue-1 2>/dev/null || echo "starting")
    [ "$status" = "healthy" ] && break
    sleep 1
done

echo "Waiting for NGINX to serve traffic..."
for _ in $(seq 1 10); do
    curl -sf http://localhost:8080/health >/dev/null 2>&1 && break
    sleep 1
done

echo
echo "Demo reset. Current state:"
python3 "$REPO_ROOT/scripts/status.py"
