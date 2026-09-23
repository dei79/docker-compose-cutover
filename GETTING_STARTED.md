# Getting Started

Install `docker cutover`, then start a project from the published demo image
- no local build, no cloning this repo.

## 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/dei79/docker-compose-cutover/main/install.sh | bash
```

(Ubuntu/Debian and want a real package instead? See
[Packaging](README.md#packaging) for the `.deb`.)

```bash
docker cutover docker-cli-plugin-metadata
```

That should print a line of JSON. If you get `docker: unknown command:
cutover` instead, the plugin isn't on `PATH` for Docker yet - re-run the
install command above and check for errors.

## 2. Start a new project from the demo image

```bash
mkdir my-project && cd my-project
docker cutover init ghcr.io/dei79/docker-compose-cutover-demo:1.0.0
docker pull ghcr.io/dei79/docker-compose-cutover-demo:1.0.0
docker cutover up
docker cutover doctor
```

(`docker cutover` never pulls or builds images on its own, by design - see
`docker pull`/`scripts/build.py` in the main README - so the image has to be
present locally before `up` or a deploy can use it.)

`doctor` should report `All checks passed.`. Then:

```bash
curl http://localhost:8080/health
```

Expected: `{"service": "demo-service", "version": "1.0.0", "slot": "blue", "hostname": "..."}`.
Open `http://localhost:8080/` in a browser for a small page showing the same
thing live, plus a running request counter.

## 3. Deploy an update with zero downtime

```bash
docker pull ghcr.io/dei79/docker-compose-cutover-demo:2.0.0
docker cutover ghcr.io/dei79/docker-compose-cutover-demo:2.0.0
curl http://localhost:8080/health
```

Expected: `"version": "2.0.0", "slot": "green"` - traffic switched with zero
dropped requests, and the old (`blue`) container was stopped automatically
once it had no in-flight requests left.

## Stop

```bash
docker cutover down
```

## Next steps

This walked through the published demo image; see [README.md](README.md) for
the full picture - what `docker cutover` actually does, using it with your
own app instead of the demo, the JSON health-endpoint contract your app
needs for a switch to verify it, and the rest of the command reference
(`init --port`/`--force`, `up`, `down --force`, `--drain-timeout`, ...).
