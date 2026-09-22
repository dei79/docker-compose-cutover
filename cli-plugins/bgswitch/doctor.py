"""`docker cutover doctor` - validate prerequisites for blue/green deployment."""

import re
import shutil
import subprocess

from .config import DEFAULTS, REQUIRED_ENV_KEYS, effective_config, parse_env_file


def check(label, ok, detail=""):
    icon = "OK  " if ok else "FAIL"
    print(f"[{icon}] {label}" + (f" - {detail}" if detail else ""))
    return ok


def find_compose_file(root):
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        if (root / name).exists():
            return name
    return None


def doctor(root):
    print(f"Checking blue/green deploy prerequisites in {root}\n")
    all_ok = True

    compose_file = find_compose_file(root)
    all_ok &= check(
        "docker-compose file present", compose_file is not None,
        compose_file or "no docker-compose.yml/compose.yaml found",
    )

    docker_present = shutil.which("docker") is not None
    all_ok &= check("docker CLI available", docker_present)

    daemon_ok = docker_present and subprocess.run(
        ["docker", "info"], cwd=root, capture_output=True,
    ).returncode == 0
    all_ok &= check("docker daemon reachable", daemon_ok)

    compose_valid = False
    if compose_file and docker_present:
        result = subprocess.run(
            ["docker", "compose", "config", "--quiet"], cwd=root, capture_output=True, text=True,
        )
        compose_valid = result.returncode == 0
        detail = "" if compose_valid else (result.stderr.strip().splitlines() or [""])[-1]
        all_ok &= check("docker-compose config is valid", compose_valid, detail)
    else:
        all_ok &= check("docker-compose config is valid", False, "skipped, see checks above")

    env_path = root / ".env"
    env_values = parse_env_file(env_path)
    all_ok &= check(".env file present", env_path.exists())

    for key in REQUIRED_ENV_KEYS:
        all_ok &= check(f".env defines {key}", bool(env_values.get(key)), env_values.get(key, ""))

    config = effective_config(env_values)
    for key in DEFAULTS:
        if key in env_values:
            check(f".env defines {key}", True, env_values[key])
        else:
            check(f".env defines {key}", True, f"not set, using default '{DEFAULTS[key]}'")

    upstream_conf = env_values.get("NGINX_UPSTREAM_CONF")
    upstream_path = root / upstream_conf if upstream_conf else None
    upstream_exists = bool(upstream_path and upstream_path.exists())
    all_ok &= check(
        "NGINX upstream config file exists", upstream_exists,
        str(upstream_path) if upstream_path else "NGINX_UPSTREAM_CONF not set",
    )

    if upstream_exists:
        text = upstream_path.read_text()
        matches = re.findall(
            rf"^\s*server app-(blue|green):{re.escape(config['APP_PORT'])}\s+resolve;",
            text, re.MULTILINE,
        )
        all_ok &= check(
            "upstream config points at exactly one active slot", len(matches) == 1,
            f"found: {matches or 'none'}",
        )

    if compose_valid:
        result = subprocess.run(
            ["docker", "compose", "config", "--services"], cwd=root, capture_output=True, text=True,
        )
        services = set(result.stdout.split())
        prefix = config["APP_SERVICE_PREFIX"]
        expected = {config["NGINX_SERVICE"], f"{prefix}-blue", f"{prefix}-green"}
        missing_services = expected - services
        all_ok &= check(
            "compose defines the nginx service and both app slots", not missing_services,
            "" if not missing_services else f"missing: {', '.join(sorted(missing_services))}",
        )

    lock_path = root / ".deploy.lock"
    all_ok &= check(
        "no stale .deploy.lock", not lock_path.exists(),
        "" if not lock_path.exists() else
        f"{lock_path} exists; if no 'docker cutover' is actually running (e.g. after a crash "
        "or power loss), remove it before deploying again",
    )

    print()
    print("All checks passed. Ready for 'docker cutover <image>:<tag>'." if all_ok
          else "Some checks failed; fix the items marked FAIL above.")
    return 0 if all_ok else 1
