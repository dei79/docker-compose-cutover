"""Thin wrappers around `docker compose` / `docker inspect` subprocess calls."""

import json
import re
import subprocess

TAG_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")


def compose(root, *args, capture=False, env=None):
    # Always capture: `docker compose`'s own progress noise (container
    # creating/starting, nginx's stdout, ...) would otherwise print directly
    # and bury our own status lines. On failure it's included in the error
    # instead, so nothing is lost - just kept out of the happy path.
    result = subprocess.run(
        ["docker", "compose", *args], cwd=root, env=env,
        text=True, capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"'docker compose {' '.join(args)}' failed: {detail}")
    return result.stdout.strip() if capture else None


def inspect_container(root, prefix, slot):
    container_id = compose(root, "ps", "-aq", f"{prefix}-{slot}", capture=True)
    if not container_id:
        raise RuntimeError(f"{prefix}-{slot} does not exist. Start the initial environment first.")
    result = subprocess.run(
        ["docker", "inspect", container_id], text=True, capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"'docker inspect {prefix}-{slot}' failed: {result.stderr.strip()}")
    return json.loads(result.stdout)[0]


def container_version(root, prefix, slot):
    for item in inspect_container(root, prefix, slot)["Config"]["Env"]:
        if item.startswith("VERSION="):
            return item.split("=", 1)[1]
    raise RuntimeError(f"{prefix}-{slot} has no VERSION environment variable.")


def parse_image_reference(reference):
    """Split a docker image reference into (name, tag), the way `docker` itself does:
    the tag is separated by the last ':' found after the last '/', so a registry
    port (host:5000/repo) is never mistaken for a tag.
    """
    slash_index = reference.rfind("/")
    tail = reference[slash_index + 1:]
    if ":" not in tail:
        raise ValueError(
            f"Image reference '{reference}' has no tag; expected e.g. "
            f"'{reference}:1.0.0' or 'namespace/{reference}:1.0.0'."
        )
    colon_index = reference.rindex(":", slash_index + 1)
    name, tag = reference[:colon_index], reference[colon_index + 1:]
    if not name or not tag:
        raise ValueError(f"Image reference '{reference}' must be NAME:TAG.")
    if not TAG_RE.fullmatch(tag):
        raise ValueError(
            f"Tag '{tag}' must be a Docker tag: 1-128 characters, starting with a letter or digit; "
            "letters, digits, dots, underscores and hyphens only."
        )
    return name, tag


def require_local_image(name, tag):
    # Inspect only: deployment never builds or pulls an image.
    image = f"{name}:{tag}"
    result = subprocess.run(
        ["docker", "image", "inspect", image], text=True, capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Local image {image} is unavailable. Build it first, e.g. "
            f"'docker build --tag {image} --build-arg VERSION={tag} ./demo-app'. "
            f"Docker: {result.stderr.strip()}"
        )
    return image


def select_slots(config_text, port):
    matches = re.findall(rf"^\s*server app-(blue|green):{re.escape(port)}\s+resolve;", config_text, re.MULTILINE)
    if len(matches) != 1:
        raise RuntimeError("Cannot determine the active slot from the NGINX upstream config.")
    active = matches[0]
    return active, "green" if active == "blue" else "blue"
