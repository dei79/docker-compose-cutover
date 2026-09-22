#!/usr/bin/env python3
"""Build a local release image of the demo app without deploying it."""

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "demo-app"

# Reuse the plugin's own image-reference parsing/validation instead of a
# second copy that could silently drift from what `docker cutover` accepts.
sys.path.insert(0, str(ROOT / "cli-plugins"))
from bgswitch.compose import parse_image_reference  # noqa: E402


def build_image(reference):
    name, tag = parse_image_reference(reference)
    image = f"{name}:{tag}"
    print(f"Building {image}...", flush=True)
    subprocess.run(
        ["docker", "build", "--tag", image, "--build-arg", f"VERSION={tag}", str(APP_DIR)],
        cwd=ROOT, check=True,
    )
    print(f"Image ready: {image}")
    print(f"Deploy separately: docker cutover {image} (run from demo-deploy/)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image",
        help="Full image reference to build, e.g. bluegreen-demo:2.0.0 or "
             "namespace/repo:tag such as acme/webshop:v1.0.0",
    )
    args = parser.parse_args()
    try:
        build_image(args.image)
    except KeyboardInterrupt:
        print("Build interrupted.", file=sys.stderr)
        return 130
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
