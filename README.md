# cutover

Zero-downtime deployments for `docker compose` projects.

`cutover` is a Docker CLI plugin that switches a compose service between two
running versions - blue and green - without dropping a single request. It
starts the new version, waits for it to become healthy, verifies it serves
real traffic through NGINX, switches NGINX to it, drains the old version's
in-flight requests, and only then stops it. If anything goes wrong along the
way, it rolls back automatically and leaves both versions running.

## Why

Most teams end up hand-rolling this exact sequence as a pile of shell and
`docker compose` calls: bring up the new container, poke it until it's
healthy, flip an NGINX upstream, hope nothing was mid-request, stop the old
one. `cutover` packages that sequence once, safely, as a reusable plugin -
so `docker cutover <image>:<tag>` replaces the bespoke script.

## What you get

- **`docker cutover doctor`** - validates a project before you ever deploy:
  compose file present, Docker reachable, `.env` has the required keys, the
  NGINX upstream config exists and points at exactly one slot, no stale lock
  left over from a crash.
- **Zero-downtime switches** - the old version keeps serving in-flight
  requests until they finish (configurable drain timeout), and NGINX is
  reloaded, never restarted.
- **Safe by construction** - a deployment lock rejects overlapping runs, any
  failure triggers an automatic rollback to the previous upstream, and exit
  codes are precise: `0` success, `1` failure, `2` drain timed out (old
  version deliberately left running, nothing was stopped).
- **Crash-safe** - containers use `restart: unless-stopped`, so a reboot
  brings back exactly what was running before, not what was already stopped;
  `doctor` flags a stale lock left over from a mid-deploy crash.
- **No lock-in to one app or one image** - the target is any full Docker
  image reference (`name:tag`, `namespace/repo:tag`, even a different
  registry/namespace entirely), and NGINX paths, service names, ports and the
  reload command are all read from `.env`, not hardcoded.
- **Zero dependencies** - a single, self-contained Python (stdlib-only)
  script; nothing to install beyond `python3` and `docker` itself.

Blue/green is the first switch strategy; the plugin is built so more can be
added later without changing the command surface.

## Quick start

```bash
scripts/install-plugin.sh        # symlinks the plugin into ~/.docker/cli-plugins
cd your-compose-project          # a docker-compose.yml + .env, see below
docker cutover doctor            # validate prerequisites
docker cutover myapp:2.0.0       # switch to myapp:2.0.0 with zero downtime
```

## License

MIT, see [LICENSE](LICENSE).

---

## Layout

```
demo-deploy/   docker-compose.yml, .env, nginx/  - the project docker cutover operates on
demo-app/      Dockerfile, server.py             - the demo application that gets built into images
cli-plugins/   the docker-cutover CLI plugin
scripts/       reset-demo.sh, build.py, plus the original deploy.py/status.py for manual testing
```

`demo-deploy/` and `demo-app/` are deliberately separate: `docker cutover` only ever
needs the former (any compose project following this layout works, not just this
demo app), and building a new image only ever needs the latter.

The `python3 scripts/*.py` and `scripts/*.sh` helpers below can be run from
anywhere (they resolve their own paths); plain `docker compose ...` commands
need to be run from inside `demo-deploy/`.

## Using `docker cutover` in your own project

From the root of a blue/green project (a `docker-compose.yml` plus an `.env`
with the keys below):

```bash
cd demo-deploy
docker cutover doctor                   # validate prerequisites, see below
docker cutover bluegreen-demo:2.0.0     # start the target slot, switch NGINX, stop the old slot
```

The argument is a full Docker image reference (`docker cutover` parses it the
same way `docker` itself does): `NAME:TAG`, or `namespace/repo:tag`, or
`registry.example.com:5000/namespace/repo:tag`. This lets one project switch
to a different image namespace entirely, not just a new tag of the same
image, e.g. `docker cutover acme/webshop:v1.0.0`.

`doctor` checks: a docker-compose file exists, the Docker daemon is
reachable, `docker compose config` is valid, `.env` exists, `.env` sets
these required keys, and there is no stale `.deploy.lock` left over from a
crashed deployment:

| Key | Meaning |
| --- | --- |
| `BLUE_VERSION` / `GREEN_VERSION` | Current image tag for each slot (compose reads these) |
| `NGINX_UPSTREAM_CONF` | Path (relative to the project root) to the upstream config `docker cutover` rewrites |
| `NGINX_RELOAD_CMD` | Command run inside the NGINX container to hot-reload, e.g. `nginx -s reload` |

`docker cutover` also persists `BLUE_IMAGE`/`GREEN_IMAGE` in `.env` (the image
name without its tag) once you've deployed at least one image to that slot;
`docker-compose.yml` falls back to `bluegreen-demo` for a slot that has
never been deployed to.

Everything else has a default matching this demo (`NGINX_SERVICE=nginx`,
`NGINX_TEST_CMD=nginx -t`, `APP_SERVICE_PREFIX=app`, `APP_PORT=8080`,
`PUBLIC_URL`, `DRAIN_TIMEOUT=60`) and can be overridden in `.env` if a
project's naming differs. `doctor` reports which ones are defaulted.

### Restart after a crash or power loss

Every service in `docker-compose.yml` uses `restart: unless-stopped`. Docker
remembers which containers were *explicitly* stopped (the old slot, via
`docker cutover`'s own `compose stop`) and will not restart those, but will
restart whatever was actually running - so after the Docker daemon or the
whole host comes back up, exactly the container that was active before the
outage comes back, and the previously-stopped slot stays stopped. There is
nothing to run manually.

If the outage happens mid-deployment, a `.deploy.lock` directory can be left
behind; `docker cutover doctor` flags this. If no deployment is actually
running, remove it (`rm -rf demo-deploy/.deploy.lock`) before deploying again.

## Try the included demo

The rest of this document walks through the included demo app end-to-end,
using `scripts/build.py` to build each version and `docker cutover` itself to
switch between them.

### 1. Prerequisites

Use macOS with Docker Desktop and Python 3 installed. No pip packages are required.

```bash
open -a Docker
python3 --version
# Continue once Docker Desktop is ready:
docker info
scripts/install-plugin.sh
```

### 2. Start from a clean demo

`scripts/reset-demo.sh` stops any running demo, (re)writes `demo-deploy/.env`
and the NGINX upstream config, builds the image, and starts blue at the
given image (default `bluegreen-demo:1.0.0`). It works the same way
for the very first setup and for resetting later - there is nothing to do
beforehand. Stop any deployment or traffic monitor before running it.

```bash
scripts/reset-demo.sh                            # blue bluegreen-demo:1.0.0
scripts/reset-demo.sh bluegreen-demo:3.2.1  # or reset to a different starting version
```

It prints `scripts/status.py` at the end. Expected: blue is running and
healthy, NGINX is running, and `/health` returns JSON containing `slot`,
`version` and `hostname`.

```bash
curl http://localhost:8080/health
open http://localhost:8080/          # small web page, refreshes slot/version every 2.5s
```

### 3. Send requests continuously

In terminal 1:

```bash
python3 scripts/test-zero-downtime.py 3600
```

This sends approximately five requests per second for one hour. Keep it running
during the deployments below. Stop with **Ctrl+C** to print the final counts.

Expected: HTTP 200 on every line and `failures=0` in the final result.
Any failed request is marked `!!! FAILED REQUEST !!!`.

### 4. Build and deploy two updates

In terminal 2:

```bash
python3 scripts/build.py bluegreen-demo:2.0.0
(cd demo-deploy && docker cutover bluegreen-demo:2.0.0)
python3 scripts/status.py
```

Expected: requests switch from blue `1.0.0` to green `2.0.0`. Blue stops only
after the old NGINX workers exit and the final smoke test passes.

Then deploy the next version:

```bash
python3 scripts/build.py bluegreen-demo:3.0.0
(cd demo-deploy && docker cutover bluegreen-demo:3.0.0)
python3 scripts/status.py
```

Expected: requests switch to blue `3.0.0`, green stops, and the traffic monitor
continues reporting HTTP 200. Status shows different image tags and IDs for the
two releases.

Build each version before deploying it. Deployment does not build or pull images.

### 5. Test a missing image

Use a unique version that has never been built:

```bash
missing_version="missing-$(uuidgen)"
(cd demo-deploy && docker cutover "bluegreen-demo:$missing_version")
echo "Exit code: $?"
python3 scripts/status.py
```

Expected: exit code `1` and an error telling you to build the image first.
The active slot, configuration and existing containers remain unchanged.
The traffic monitor continues returning HTTP 200.

### 6. Test worker draining and its timeout

After step 4, build the next image:

```bash
python3 scripts/build.py bluegreen-demo:4.0.0
```

In terminal 3, start a request whose headers remain incomplete for 30 seconds:

```bash
python3 - <<'PY'
import socket
import time

with socket.create_connection(("localhost", 8080), timeout=5) as connection:
    connection.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Pending: test")
    print("Request open. Start the deployment in terminal 2 now.", flush=True)
    time.sleep(30)
    connection.sendall(b"\r\nConnection: close\r\n\r\n")
    response = b""
    while chunk := connection.recv(8192):
        response += chunk
    print(response.decode())
PY
```

Immediately run this in terminal 2, while that request is still open:

```bash
(cd demo-deploy && docker cutover bluegreen-demo:4.0.0 --drain-timeout 2)
echo "Exit code: $?"
python3 scripts/status.py
(cd demo-deploy && docker compose exec nginx ps -o pid,args)
```

Expected: exit code `2`. New requests reach green `4.0.0`, but blue `3.0.0`
remains running. At least one old NGINX worker is marked `shutting down`.
A further deployment is rejected while that worker is still draining.
After 30 seconds, terminal 3 receives HTTP 200 from blue `3.0.0`.
Blue remains running after a timeout; it is not stopped automatically later.

To test successful draining instead, repeat from step 2 and use
`--drain-timeout 60` in this test. Expected: deployment waits until terminal 3's
request finishes, then stops blue and exits with code `0`.

### Inspect results and logs

```bash
python3 scripts/status.py
cd demo-deploy
docker compose ps -a
docker image ls bluegreen-demo
docker compose logs --tail=50 nginx app-blue app-green
docker compose logs -f nginx
docker compose exec nginx ps -o pid,args
```

Use **Ctrl+C** to stop following logs.

### Stop the demo

Stop the traffic monitor, finish any pending test request, and wait for any
running deployment to finish. Then run:

```bash
(cd demo-deploy && docker compose down)
```

The built images remain available. To repeat the test, start at step 2.
