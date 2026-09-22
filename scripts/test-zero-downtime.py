#!/usr/bin/env python3
"""Monitor public traffic and highlight every failed request."""

import argparse
import datetime
import json
import math
import sys
import time
import urllib.request


def monitor(seconds):
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + seconds
    requests = failures = 0
    print(f"Monitoring for {seconds:g}s; deploy from another terminal. Ctrl-C to stop.", flush=True)
    try:
        while time.monotonic() < deadline:
            timestamp = datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")
            status = "NETWORK_ERROR"
            requests += 1
            try:
                with client.open("http://localhost:8080/health", timeout=2) as response:
                    status = response.status
                    data = json.load(response)
                if (status != 200 or not isinstance(data, dict)
                        or data.get("service") != "demo-service"
                        or data.get("slot") not in ("blue", "green")
                        or not data.get("version") or not data.get("hostname")):
                    raise ValueError("Unexpected service response")
                print(f'{timestamp} HTTP {status} version={data["version"]} slot={data["slot"]}', flush=True)
            except Exception as error:
                failures += 1
                status = getattr(error, "code", status)
                print(f"!!! FAILED REQUEST !!! {timestamp} HTTP {status} {error}", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        # Always print the counts, including when stopped with Ctrl-C.
        pass
    print(f"RESULT: requests={requests}, failures={failures}", flush=True)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seconds", nargs="?", type=float, default=120, help="Duration in seconds (default: 120)")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("Duration must be a finite, positive number of seconds.")
    return monitor(args.seconds)


if __name__ == "__main__":
    sys.exit(main())
