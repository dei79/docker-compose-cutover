"""`docker cutover up` - start NGINX and whichever slot is currently active."""

from .compose import compose, select_slots
from .health import wait_healthy


def up(root, config):
    upstream = root / config["NGINX_UPSTREAM_CONF"]
    if not upstream.exists():
        raise RuntimeError(
            f"{config['NGINX_UPSTREAM_CONF']} does not exist; run 'docker cutover init' first."
        )
    nginx_service = config["NGINX_SERVICE"]
    prefix = config["APP_SERVICE_PREFIX"]
    port = config["APP_PORT"]

    active, _ = select_slots(upstream.read_text(), port)
    print(f"==> Starting {nginx_service} + {prefix}-{active} "
          f"(the slot {config['NGINX_UPSTREAM_CONF']} points at; {prefix}-{'green' if active == 'blue' else 'blue'} stays down)")
    compose(root, "up", "-d", nginx_service, f"{prefix}-{active}")
    wait_healthy(root, prefix, active)
    print(f"    {prefix}-{active} is healthy")
    return 0
