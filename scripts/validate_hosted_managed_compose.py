"""Validate fail-closed hosted managed-operation Compose interpolation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    REPO_ROOT / "docker-compose.example.yml",
    REPO_ROOT / "docker-compose.production-web.example.yml",
    REPO_ROOT / "docker-compose.hosted-managed.example.yml",
)
ALLOWLIST_ENV = "PLATFORM_MANAGED_OPERATION_ALLOWLIST"
READ_ONLY_CANARY_OPERATION = "review_status_execute"


def _command(env_file: Path) -> list[str]:
    command = ["docker", "compose", "--env-file", str(env_file)]
    for compose_file in COMPOSE_FILES:
        command.extend(("--file", str(compose_file)))
    command.extend(("config", "--format", "json"))
    return command


def _environment(*, allowlist: str | None) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop(ALLOWLIST_ENV, None)
    environment.update(
        {
            "ORG_ROOT": "/tmp/0al-hosted-managed-compose-contract",
            "PLATFORM_MANAGED_OPERATION_TOKEN_FILE": "/tmp/managed-operation-token",
            "PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE": (
                "/tmp/managed-operation-db-password"
            ),
        }
    )
    if allowlist is not None:
        environment[ALLOWLIST_ENV] = allowlist
    return environment


def validate_hosted_managed_compose() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        empty_env = Path(temp_dir) / "empty.env"
        empty_env.write_text("", encoding="utf-8")
        command = _command(empty_env)
        missing = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=_environment(allowlist=None),
            capture_output=True,
            text=True,
            check=False,
        )
        if missing.returncode == 0:
            raise RuntimeError(
                "hosted Compose rendered without a deployment allowlist"
            )
        missing_diagnostic = f"{missing.stdout}\n{missing.stderr}"
        if ALLOWLIST_ENV not in missing_diagnostic:
            raise RuntimeError(
                "missing allowlist failure did not identify the required variable"
            )

        configured = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=_environment(allowlist=READ_ONLY_CANARY_OPERATION),
            capture_output=True,
            text=True,
            check=False,
        )
        if configured.returncode != 0:
            raise RuntimeError(
                "configured hosted Compose did not render: "
                f"{configured.stderr.strip()}"
            )
        payload = json.loads(configured.stdout)

    services = payload.get("services")
    if not isinstance(services, dict):
        raise RuntimeError("configured hosted Compose omitted services")
    checked_services: list[str] = []
    for service_name in ("managed-operation-service", "managed-operation-worker"):
        service = services.get(service_name)
        environment = (
            service.get("environment") if isinstance(service, dict) else None
        )
        if not isinstance(environment, dict):
            raise RuntimeError(f"{service_name} omitted its environment")
        if environment.get(ALLOWLIST_ENV) != READ_ONLY_CANARY_OPERATION:
            raise RuntimeError(
                f"{service_name} did not receive the deployment allowlist"
            )
        checked_services.append(service_name)

    return {
        "artifact_kind": "platform_hosted_managed_compose_contract_report",
        "ok": True,
        "summary": {
            "missing_allowlist_blocked": True,
            "configured_allowlist_rendered": True,
            "checked_services": checked_services,
        },
    }


def main() -> int:
    try:
        report = validate_hosted_managed_compose()
    except (json.JSONDecodeError, OSError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "diagnostic": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
