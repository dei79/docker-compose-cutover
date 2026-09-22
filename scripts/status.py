#!/usr/bin/env python3
"""Show the configured slot, container states, versions and public response."""

import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent / "demo-deploy"


def read_containers():
    result = subprocess.run(
        ["docker", "compose", "ps", "-aq"], cwd=ROOT,
        text=True, check=True, capture_output=True,
    )
    container_ids = result.stdout.split()
    if not container_ids:
        return {}
    result = subprocess.run(
        ["docker", "inspect", *container_ids], text=True, check=True, capture_output=True,
    )
    return {
        container["Config"]["Labels"]["com.docker.compose.service"]: container
        for container in json.loads(result.stdout)
    }


def show_app(slot, container):
    if container is None:
        print(f"{slot}: not created; version: n/a")
        return
    state = container["State"]
    status = state["Status"]
    # Health is meaningful only while the container is running.
    if state["Running"]:
        status += f" (health: {state.get('Health', {}).get('Status', 'n/a')})"
    env = dict(item.split("=", 1) for item in container["Config"]["Env"])
    print(f"{slot}: {status}; version: {env.get('VERSION', 'n/a')}")
    print(f"  image: {container['Config']['Image']} ({container['Image'][:19]})")


def show_public_response():
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with client.open("http://localhost:8080/health", timeout=3) as response:
            print(f"Public response: {json.dumps(json.load(response))}")
    except (OSError, ValueError) as error:
        print(f"Public response: unavailable ({error})")


def main():
    try:
        config = (ROOT / "nginx/conf.d/upstream.conf").read_text()
        slots = re.findall(r"^\s*server app-(blue|green):8080\s+resolve;", config, re.MULTILINE)
        print(f"Configured active slot: {slots[0] if len(slots) == 1 else 'unknown'}")
        containers = read_containers()
        for slot in ("blue", "green"):
            show_app(slot, containers.get(f"app-{slot}"))
        nginx = containers.get("nginx")
        print(f"nginx: {nginx['State']['Status'] if nginx else 'not created'}")
        show_public_response()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Status check failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
