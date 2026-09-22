"""`docker cutover <image:tag>` - switch the active slot with zero downtime."""

from contextlib import contextmanager
import os
import shlex
import shutil
import signal
import sys

from .compose import compose, container_version, parse_image_reference, require_local_image, select_slots
from .health import test_new_container, verify_public, wait_healthy
from .nginx import atomic_write, ensure_no_draining_workers, nginx_workers, wait_for_old_workers, write_upstream


def deploy(root, config, image_reference, drain_timeout):
    image_name, version = parse_image_reference(image_reference)
    upstream = root / config["NGINX_UPSTREAM_CONF"]
    nginx_service = config["NGINX_SERVICE"]
    prefix = config["APP_SERVICE_PREFIX"]
    port = config["APP_PORT"]
    public_url = config["PUBLIC_URL"]
    reload_cmd = shlex.split(config["NGINX_RELOAD_CMD"])
    test_cmd = shlex.split(config["NGINX_TEST_CMD"])

    image = require_local_image(image_name, version)
    with deployment_lock(root):
        ensure_no_draining_workers(root, nginx_service)
        previous_config = upstream.read_text()
        active, target = select_slots(previous_config, port)
        old_version = container_version(root, prefix, active)
        verify_public(public_url, active, old_version)
        print(f"==> Deploying {image}")
        print(f"    active slot: {active} ({old_version})  ->  target slot: {target}")

        print(f"    starting {prefix}-{target} ...")
        start_new_version(root, prefix, target, image_name, version)
        wait_healthy(root, prefix, target)
        test_new_container(root, nginx_service, prefix, port, target, version)
        print(f"    {prefix}-{target} is healthy")

        reload_attempted = False
        try:
            write_upstream(upstream, prefix, target, port)
            compose(root, "exec", "-T", nginx_service, *test_cmd)
            old_workers = nginx_workers(root, nginx_service)
            reload_attempted = True
            compose(root, "exec", "-T", nginx_service, *reload_cmd)
            verify_public(public_url, target, version)
            print(f"==> Switched NGINX to {target}")
            drained = wait_for_old_workers(root, nginx_service, old_workers, drain_timeout)
            verify_public(public_url, target, version)
            if not drained:
                print(
                    f"Drain timeout after {drain_timeout:g}s: {target} ({version}) is serving new "
                    f"traffic, but {prefix}-{active} still has unfinished requests and was left "
                    "running. No container was stopped; retry once it has drained.",
                    file=sys.stderr,
                )
                return 2
        except (Exception, KeyboardInterrupt):
            rollback(root, nginx_service, test_cmd, reload_cmd, public_url,
                     previous_config, upstream, active, old_version, reload_attempted)
            raise

        # The switch is confirmed. A stop failure must not trigger rollback.
        compose(root, "stop", f"{prefix}-{active}")
        page_url = public_url[:-len("health")] if public_url.endswith("health") else public_url
        print("==> Deployment successful")
        print(f"    active : {target} ({image})")
        print(f"    stopped: {active}")
        print(f"    url    : {page_url}")
        return 0


def start_new_version(root, prefix, slot, image_name, version):
    # Persist the slot's image and version; Compose uses them to select the release image.
    env_file = root / ".env"
    image_key = f"{slot.upper()}_IMAGE"
    version_key = f"{slot.upper()}_VERSION"
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    lines = [line for line in lines if not line.startswith((image_key + "=", version_key + "="))]
    atomic_write(env_file, "\n".join(lines + [f"{image_key}={image_name}", f"{version_key}={version}"]) + "\n")
    env = dict(os.environ, **{image_key: image_name, version_key: version})
    compose(root, "up", "-d", "--no-deps", "--no-build", "--pull", "never",
            "--force-recreate", f"{prefix}-{slot}", env=env)


def rollback(root, nginx_service, test_cmd, reload_cmd, public_url,
             config_text, upstream, slot, version, reload_attempted):
    print("==> Deployment failed, rolling back NGINX; both apps stay up", file=sys.stderr)
    # Let rollback finish even if Ctrl-C is pressed again.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        atomic_write(upstream, config_text)
        if reload_attempted:
            compose(root, "exec", "-T", nginx_service, *test_cmd)
            compose(root, "exec", "-T", nginx_service, *reload_cmd)
            verify_public(public_url, slot, version)
        print(f"    rollback complete: {slot} ({version}) is active again", file=sys.stderr)
    except Exception as error:
        print(f"    ROLLBACK FAILED: {error}", file=sys.stderr)
        print("    neither app was stopped; inspect NGINX and both containers by hand", file=sys.stderr)
        raise


@contextmanager
def deployment_lock(root):
    lock = root / ".deploy.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise RuntimeError("Another deployment is running (.deploy.lock exists).") from None
    try:
        yield
    finally:
        shutil.rmtree(lock)
