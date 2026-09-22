"""Argument parsing and dispatch for the docker-cutover CLI plugin."""

import argparse
import json
import math
from pathlib import Path
import signal
import sys

from .compose import parse_image_reference
from .config import ConfigError, load_config
from .deploy import deploy
from .doctor import doctor

PLUGIN_COMMAND_PREFIX = "docker-"

PLUGIN_METADATA = {
    "SchemaVersion": "0.1.0",
    "Vendor": "cutover",
    # Patched to the real release tag by .github/workflows/release.yml before
    # packaging; this checked-in value only shows up in unreleased/dev builds.
    "Version": "0.0.0-dev",
    "ShortDescription": "Zero-downtime blue/green deploys for a docker compose project",
}

def interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv):
    # argv[0] is this executable's own path (e.g. .../cli-plugins/docker-cutover).
    # Docker's CLI plugin protocol invokes it with the *matched* command name
    # ("cutover") re-inserted as the next argument, so `docker cutover doctor`
    # arrives as ["doctor"] when run directly but ["cutover", "doctor"] when
    # run through `docker`. Derive that expected token from our own filename
    # instead of hardcoding "cutover", so renaming the plugin can't desync it.
    plugin_command = Path(argv[0]).name.removeprefix(PLUGIN_COMMAND_PREFIX)
    args = argv[1:]

    # Docker probes every plugin with this hidden command to build its help
    # and command listing; it must succeed without touching the project.
    if args[:1] == ["docker-cli-plugin-metadata"]:
        print(json.dumps(PLUGIN_METADATA))
        return 0

    if args[:1] == [plugin_command]:
        args = args[1:]

    if args[:1] == ["doctor"]:
        doctor_parser = argparse.ArgumentParser(
            prog="docker cutover doctor",
            description="Validate that this directory is ready for blue/green deployments.",
        )
        doctor_parser.parse_args(args[1:])
        return doctor(Path.cwd())

    parser = argparse.ArgumentParser(
        prog="docker cutover",
        description="Deploy IMAGE to the inactive slot, switch NGINX to it, then stop the old slot.",
    )
    parser.add_argument(
        "image",
        help="Full image reference to deploy, e.g. bluegreen-demo:2.0.0 "
             "or namespace/repo:tag such as acme/webshop:v1.0.0",
    )
    parser.add_argument(
        "--drain-timeout", type=float, default=None,
        help="Seconds to wait for old NGINX workers to drain (default: .env DRAIN_TIMEOUT or 60)",
    )
    parsed = parser.parse_args(args)

    try:
        parse_image_reference(parsed.image)
    except ValueError as error:
        parser.error(str(error))

    root = Path.cwd()
    try:
        config = load_config(root)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    drain_timeout = parsed.drain_timeout
    if drain_timeout is None:
        drain_timeout = float(config["DRAIN_TIMEOUT"])
    if not math.isfinite(drain_timeout) or drain_timeout <= 0:
        parser.error("Drain timeout must be a finite, positive number of seconds.")

    signal.signal(signal.SIGTERM, interrupt)
    try:
        return deploy(root, config, parsed.image, drain_timeout)
    except KeyboardInterrupt:
        print("Deployment interrupted.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        return 1
