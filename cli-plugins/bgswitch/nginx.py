"""NGINX upstream file rewriting and worker drain tracking."""

import re
import time

from .compose import compose


def atomic_write(path, content):
    # The mounted directory makes an atomic replacement visible inside NGINX.
    temporary = path.with_suffix(".next")
    temporary.write_text(content)
    temporary.replace(path)


def write_upstream(upstream, prefix, slot, port):
    atomic_write(upstream, f"""upstream backend {{
    zone backend 64k;
    server {prefix}-{slot}:{port} resolve;
}}
""")


def nginx_workers(root, nginx_service):
    # Include both current workers and workers finishing requests after a reload.
    output = compose(root, "exec", "-T", nginx_service, "ps", "-o", "pid,args", capture=True)
    workers = {}
    for line in output.splitlines():
        match = re.match(r"\s*(\d+)\s+nginx: worker process(.*)", line)
        if match:
            workers[int(match[1])] = "shutting down" in match[2]
    if not workers:
        raise RuntimeError("Cannot find NGINX workers; refusing to stop or replace any app.")
    return workers


def ensure_no_draining_workers(root, nginx_service):
    # A previous timeout or rollback may still have requests using either slot.
    if any(nginx_workers(root, nginx_service).values()):
        raise RuntimeError(
            "NGINX workers are still draining from a previous reload. "
            "Wait for them to exit before deploying again; neither app was changed."
        )


def wait_for_old_workers(root, nginx_service, old_workers, timeout):
    print(f"    waiting up to {timeout:g}s for the old NGINX worker(s) to drain ...")
    deadline = time.monotonic() + timeout
    while True:
        remaining = set(old_workers).intersection(nginx_workers(root, nginx_service))
        if not remaining:
            print("    old worker(s) drained")
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
