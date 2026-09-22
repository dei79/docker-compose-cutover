"""Health, readiness and smoke-test checks against the app slots."""

import json
import time
import urllib.request

from .compose import compose, inspect_container

HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def wait_healthy(root, prefix, slot):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = inspect_container(root, prefix, slot)["State"]
        health = state.get("Health", {}).get("Status", "missing")
        if state["Running"] and health == "healthy":
            return
        if not state["Running"] or health in ("unhealthy", "missing"):
            raise RuntimeError(f"{prefix}-{slot} is not ready: {state['Status']}, health={health}.")
        time.sleep(1)
    raise RuntimeError(f"{prefix}-{slot} did not become healthy within 60 seconds.")


def matches_release(body, slot, version):
    return (
        isinstance(body, dict)
        and body.get("slot") == slot
        and body.get("version") == version
        and bool(body.get("hostname"))
    )


def test_new_container(root, nginx_service, prefix, port, slot, version):
    # Probe from NGINX through Docker DNS; app ports are never published.
    # '/' is the human-facing web page, not JSON, so only '/health' is checked here.
    body = compose(root, "exec", "-T", nginx_service, "wget", "-q", "-T", "3", "-O", "-",
                   f"http://{prefix}-{slot}:{port}/health", capture=True)
    if not matches_release(json.loads(body), slot, version):
        raise RuntimeError(f"Direct probe failed for {prefix}-{slot}/health.")


def verify_public(public_url, slot, version):
    # Reload is asynchronous: allow old responses briefly, but reject HTTP errors.
    for attempt in range(20):
        with HTTP.open(public_url, timeout=3) as response:
            if response.status != 200:
                raise RuntimeError(f"Public smoke test ({public_url}) returned HTTP {response.status}.")
            body = json.load(response)
        if matches_release(body, slot, version):
            return
        time.sleep(0.5)
    raise RuntimeError(
        f"Public traffic ({public_url}) did not switch to {slot} / {version} in time; "
        f"last response: {json.dumps(body)}"
    )
