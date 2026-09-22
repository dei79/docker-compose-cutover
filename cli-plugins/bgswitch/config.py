"""Load and validate the project's .env configuration for docker-cutover."""

# These must be set explicitly in the project's .env file; `doctor` fails
# without them and `deploy` refuses to run.
REQUIRED_ENV_KEYS = ("BLUE_VERSION", "GREEN_VERSION", "NGINX_UPSTREAM_CONF", "NGINX_RELOAD_CMD")

# Everything else has a sensible default matching the reference demo, so
# existing projects keep working without touching .env.
DEFAULTS = {
    "NGINX_SERVICE": "nginx",
    "NGINX_TEST_CMD": "nginx -t",
    "APP_SERVICE_PREFIX": "app",
    "APP_PORT": "8080",
    # '/' is the human-facing web page, not JSON; the smoke test needs the JSON endpoint.
    "PUBLIC_URL": "http://localhost:8080/health",
    "DRAIN_TIMEOUT": "60",
}


class ConfigError(RuntimeError):
    pass


def parse_env_file(path):
    values = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def effective_config(env_values):
    config = dict(DEFAULTS)
    config.update(env_values)
    return config


def load_config(root):
    env_values = parse_env_file(root / ".env")
    missing = [key for key in REQUIRED_ENV_KEYS if not env_values.get(key)]
    if missing:
        raise ConfigError(
            "Missing required .env setting(s): " + ", ".join(missing) + ". "
            "Run 'docker cutover doctor' for details."
        )
    return effective_config(env_values)
