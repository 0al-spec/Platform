"""Run on the VPS as root; provider keys are read from the terminal, never argv."""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import tempfile
from pathlib import Path

SECRET_DIR = Path("/srv/0al/secrets/normlab-inference")
FILES = {
    "openai": "openai-api-key",
    "typesafe": "typesafe-api-key",
    "gateway": "gateway-token",
}


def install_secret(
    kind: str,
    value: str,
    folder: Path = SECRET_DIR,
    *,
    uid: int = 1000,
    gid: int = 1000,
) -> Path:
    """Atomic replacement; only the dedicated directory and selected file are touched."""
    if kind not in FILES or not re.fullmatch(r"[!-~]{32,8192}", value):
        raise ValueError("Invalid secret type or format; value was not printed.")
    if folder.is_symlink():
        raise ValueError("Secret directory must not be a symlink.")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.chmod(0o700)
    target = folder / FILES[kind]
    if target.is_symlink():
        raise ValueError("Secret file must not be a symlink.")
    descriptor, temporary = tempfile.mkstemp(prefix=".install-", dir=folder)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value.encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o400)
            os.fchown(stream.fileno(), uid, gid)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=FILES)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root on the VPS.")
    value = (
        secrets.token_hex(32)
        if args.kind == "gateway"
        else getpass.getpass(f"{args.kind} API key (hidden input): ")
    )
    try:
        target = install_secret(args.kind, value)
    except (OSError, ValueError):
        parser.exit(1, "Secret installation failed; no credential value was printed.\n")
    print(
        f"Installed {target} (UID/GID 1000, mode 0400). Recreate its consumers to rotate."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
