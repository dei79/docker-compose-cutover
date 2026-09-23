# cutover

`cutover` is a Docker CLI plugin for zero-downtime blue/green deploys of
`docker compose` projects. It starts the new version, verifies it over real
traffic, and switches NGINX to it, draining the old version's in-flight
requests before stopping it. If any step fails, it rolls back automatically
and leaves both versions running.

## Quick start

Install (macOS/Linux, no repo checkout needed):

```bash
curl -fsSL https://raw.githubusercontent.com/dei79/docker-compose-cutover/main/install.sh | bash
```

Ubuntu/Debian and want a real package instead? See
[Building](#building) for the `.deb`.

Then try it against the published demo image - no local build required:

```bash
mkdir my-project && cd my-project
docker cutover init ghcr.io/dei79/docker-compose-cutover-demo:1.0.0
docker pull ghcr.io/dei79/docker-compose-cutover-demo:1.0.0
docker cutover up
curl http://localhost:8080/health
```

Expected: `{"service": "demo-service", "version": "1.0.0", "slot": "blue", ...}`.
Open `http://localhost:8080/` for a small page showing the same thing live.

Deploy an update with zero downtime:

```bash
docker pull ghcr.io/dei79/docker-compose-cutover-demo:2.0.0
docker cutover ghcr.io/dei79/docker-compose-cutover-demo:2.0.0
curl http://localhost:8080/health
```

Expected: `"version": "2.0.0", "slot": "green"` - traffic switched with zero
dropped requests, and blue was stopped automatically once it had no
in-flight requests left. Stop everything with:

```bash
docker cutover down
```

(`GETTING_STARTED.md` walks through the same four commands with more
explanation if any of that felt rushed.)

## Configuration

### Starting a new project

`docker cutover init <image>:<tag>` scaffolds a `docker-compose.yml`, `.env`
and `nginx/` for a blue/green setup in the current directory - no need to
hand-copy `demo-deploy/`:

```bash
docker cutover init myapp:1.0.0        # --port 8080 by default, --force to overwrite
```

It only writes files; nothing is started automatically. It refuses to run if
`docker-compose.yml`, `.env` or `nginx/` already exist (unless `--force`).
Review the generated healthcheck (it assumes `wget` is available in the
image) and see **Health contract** below before your first deploy.
`docker cutover` itself never pulls or builds images, so pull or build the
initial one before starting - see **Deploying updates** below.

### Starting and stopping

Use `docker cutover up`/`down` rather than plain `docker compose up -d`/`down`:
the compose file defines both slots, so a plain `up -d` would start both at
once, breaking the "only one slot running" invariant. `up` reads which slot
`nginx/conf.d/upstream.conf` currently points at (`blue` right after `init`)
and starts only NGINX plus that one; the same command resumes correctly
after a `down`, whichever slot was last active. `down` refuses (unless
`--force`) while a `.deploy.lock` suggests a deployment is in progress, so
you don't tear down containers mid-switch.

### Deploying updates

From the root of a blue/green project (a `docker-compose.yml` plus an `.env`
with the keys below):

```bash
docker cutover doctor                   # validate prerequisites, see below
docker cutover myapp:2.0.0              # start the target slot, switch NGINX, stop the old slot
```

The argument is a full Docker image reference (`docker cutover` parses it the
same way `docker` itself does): `NAME:TAG`, `namespace/repo:tag`, or
`registry.example.com:5000/namespace/repo:tag`. This lets one project switch
to a different image namespace entirely, not just a new tag of the same
image. `docker cutover` never builds or pulls images itself - the target
must already exist locally (`docker pull`/`docker build` it first).

Exit codes are precise: `0` success, `1` failure (rolled back automatically,
both versions still running), `2` the old slot's in-flight requests didn't
drain in time (`--drain-timeout`, default 60s) - nothing was stopped, retry
once it's actually idle.

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
name without its tag) once you've deployed at least one image to that slot.

Everything else has a default matching the demo (`NGINX_SERVICE=nginx`,
`NGINX_TEST_CMD=nginx -t`, `APP_SERVICE_PREFIX=app`, `APP_PORT=8080`,
`PUBLIC_URL`, `DRAIN_TIMEOUT=60`) and can be overridden in `.env` if a
project's naming differs. `doctor` reports which ones are defaulted.

### Health contract

For a switch to verify the new slot is really serving the new version before
stopping the old one, your app's health endpoint must return JSON:

```json
{"slot": "blue", "version": "1.0.0", "hostname": "anything-non-empty"}
```

`slot` and `version` are matched exactly against what's being deployed;
`hostname` just has to be present. This is the same contract `demo-app/`
implements (see `demo-app/server.py`) - an app that doesn't already return
this shape needs a small adapter or endpoint added before `docker cutover`
can deploy it with verification.

### Restart after a crash or power loss

Every service in a `docker cutover init`-generated (or `demo-deploy/`)
`docker-compose.yml` uses `restart: unless-stopped`. Docker remembers which
containers were *explicitly* stopped (the old slot, via `docker cutover`'s
own `compose stop`) and won't restart those, but will restart whatever was
actually running - so after the Docker daemon or the whole host comes back
up, exactly the container that was active before the outage comes back, and
the previously-stopped slot stays stopped. There is nothing to run manually.

If the outage happens mid-deployment, a `.deploy.lock` directory can be left
behind; `docker cutover doctor` flags this. If no deployment is actually
running, remove it (`rm -rf <project>/.deploy.lock`) before deploying again.

## Building

### Layout

```
cli-plugins/       the docker-cutover CLI plugin (entrypoint + bgswitch/ package)
demo-app/          Dockerfile, server.py - the demo application published to GHCR
demo-deploy/       docker-compose.yml, nginx/ - a hand-maintained example project for demo-app
scripts/           install-plugin.sh (local dev), reset-demo.sh, build.py, status.py, test-zero-downtime.py
packaging/deb/     builds the docker-compose-cutover .deb
install.sh         curl-installable installer (see Quick start)
.github/workflows/ release.yml (tag -> GitHub Release + .deb), publish-demo-app.yml (demo-app -> GHCR)
```

`demo-deploy/` and `demo-app/` are deliberately separate: `docker cutover`
only ever needs the former (any compose project following this layout
works, not just this demo app), and building a new image only ever needs
the latter.

### Installers

Two ways to distribute the plugin without a git checkout, both documented in
**Quick start** above:

- **`install.sh`** - a curl-able installer for macOS/Linux. It grabs the
  latest tagged release (or `main` if none exists yet), installs it into a
  versioned directory under `~/.docker/cutover/versions/`, and points
  `~/.docker/cli-plugins/docker-cutover` at it with a symlink - safe to
  re-run even if something else (this repo's own `scripts/install-plugin.sh`,
  or a previous run) already left a symlink or file there.
- **`packaging/deb/build.sh`** - builds a `docker-compose-cutover` `.deb`
  that installs the same plugin into `/usr/lib/docker/cli-plugins/`, so it
  can be installed with a plain
  `sudo apt-get install ./docker-compose-cutover_*.deb` (no APT repo needed).

Both stamp the release version into the plugin's own metadata (visible via
`docker cutover docker-cli-plugin-metadata`), even though the checked-in
source always shows `0.0.0-dev`.

### Releasing

Pushing a `vX.Y.Z` tag triggers `.github/workflows/release.yml`: it derives
the version from the tag, stamps it into the plugin, builds the `.deb`, and
attaches it to a new GitHub Release.

```bash
git tag v0.2.0 && git push origin v0.2.0
```

### Publishing the demo image

`.github/workflows/publish-demo-app.yml` builds and pushes
`ghcr.io/dei79/docker-compose-cutover-demo:1.0.0` and `:2.0.0` to GHCR
whenever `demo-app/` changes (or on manual dispatch) - both tags always
contain the current `demo-app/` code, just built with a different `VERSION`
build-arg, which is all the demo needs to tell the two apart.

## Contributing

Clone the repo and install the plugin as a symlink instead of a copy, so
edits under `cli-plugins/` take effect immediately:

```bash
git clone https://github.com/dei79/docker-compose-cutover.git
cd docker-compose-cutover
scripts/install-plugin.sh
```

The included demo is the manual test suite for changes to the plugin. It
walks through the exact same commands end users run, but against
`demo-deploy/` and (mostly) locally-built images, so you can watch every
exit code and edge case up close.

#### 1. Prerequisites

```bash
open -a Docker
python3 --version
docker info
```

#### 2. Start from a clean demo

`scripts/reset-demo.sh` stops any running demo (`docker cutover down --force`),
(re)writes `demo-deploy/.env` and the NGINX upstream config, pulls the given
image (default the published `ghcr.io/dei79/docker-compose-cutover-demo:1.0.0`,
skipped if that reference is already built locally), and starts blue with
`docker cutover up`. It works the same way for the very first setup and for
resetting later - there is nothing to do beforehand. Stop any deployment or
traffic monitor before running it.

```bash
scripts/reset-demo.sh                            # blue ghcr.io/.../docker-compose-cutover-demo:1.0.0
scripts/reset-demo.sh bluegreen-demo:3.2.1        # or reset to a locally built image instead
```

It prints `scripts/status.py` at the end. Expected: blue is running and
healthy, NGINX is running, and `/health` returns JSON containing `slot`,
`version` and `hostname`.

```bash
curl http://localhost:8080/health
open http://localhost:8080/          # small web page, refreshes slot/version every 2.5s
```

#### 3. Send requests continuously

In terminal 1:

```bash
python3 scripts/test-zero-downtime.py 3600
```

This sends approximately five requests per second for one hour. Keep it running
during the deployments below. Stop with **Ctrl+C** to print the final counts.

Expected: HTTP 200 on every line and `failures=0` in the final result.
Any failed request is marked `!!! FAILED REQUEST !!!`.

#### 4a. Deploy a published update

In terminal 2:

```bash
docker pull ghcr.io/dei79/docker-compose-cutover-demo:2.0.0
(cd demo-deploy && docker cutover ghcr.io/dei79/docker-compose-cutover-demo:2.0.0)
python3 scripts/status.py
```

Expected: requests switch from blue `1.0.0` to green `2.0.0`. Blue stops only
after the old NGINX workers exit and the final smoke test passes.

#### 4b. Deploy a locally built update

Steps 5 and 6 need versions that were never published, so build one locally
and deploy it the same way - `docker cutover` doesn't care whether an image
was pulled or built, only that it exists locally:

```bash
python3 scripts/build.py bluegreen-demo:3.0.0
(cd demo-deploy && docker cutover bluegreen-demo:3.0.0)
python3 scripts/status.py
```

Expected: requests switch to blue `3.0.0`, green stops, and the traffic monitor
continues reporting HTTP 200. Status shows different image tags and IDs for the
two releases.

Build each version before deploying it. Deployment does not build or pull images.

#### 5. Test a missing image

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

#### 6. Test worker draining and its timeout

After step 4b, build the next image:

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

#### Inspect results and logs

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

#### Stop the demo

Stop the traffic monitor, finish any pending test request, and wait for any
running deployment to finish. Then run:

```bash
(cd demo-deploy && docker cutover down)
```

The built images remain available. To repeat the test, start at step 2.

## License

MIT, see [LICENSE](LICENSE).
