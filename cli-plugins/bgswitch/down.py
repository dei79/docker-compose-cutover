"""`docker cutover down` - stop and remove this project's containers."""

from .compose import compose


def down(root, force):
    lock_path = root / ".deploy.lock"
    if lock_path.exists() and not force:
        raise RuntimeError(
            f"{lock_path} exists; a deployment looks like it's in progress. Tearing "
            "down now could kill it mid-switch. Wait for it to finish, or pass "
            "--force if you're sure it's stale (e.g. left over from a crash)."
        )
    print("==> Stopping and removing this project's containers")
    compose(root, "down")
    return 0
