"""Validate the standalone hosted managed-operation runtime Compose profile."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.hosted-managed-runtime.example.yml"
ALLOWLIST_ENV = "PLATFORM_MANAGED_OPERATION_ALLOWLIST"
READ_ONLY_CANARY_OPERATION = "review_status_execute"
RUNTIME_SERVICES = {
    "managed-operation-postgres",
    "managed-operation-service",
    "managed-operation-worker",
}


def _command() -> list[str]:
    return [
        "docker",
        "compose",
        "--file",
        str(COMPOSE_FILE),
        "config",
        "--format",
        "json",
    ]


def _environment(temp_root: Path, *, allowlist: str | None) -> dict[str, str]:
    temp_root.mkdir(parents=True)
    artifact_root = temp_root / "specgraph"
    state_dir = temp_root / "state"
    secrets_dir = temp_root / "secrets"
    artifact_root.mkdir()
    state_dir.mkdir()
    secrets_dir.mkdir()
    secret_values = {
        "managed-operation-token": "fixture-token",
        "managed-operation-db-password": "fixture-password",
        "managed-operation-database-url": (
            "postgresql://managed_operations:fixture-password@"
            "managed-operation-postgres:5432/managed_operations"
        ),
        "managed-operation-github-token": "fixture-github-token",
    }
    for name, value in secret_values.items():
        (secrets_dir / name).write_text(value, encoding="utf-8")

    environment = dict(os.environ)
    environment.pop(ALLOWLIST_ENV, None)
    environment.update(
        {
            "PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT": str(artifact_root),
            "PLATFORM_MANAGED_OPERATION_STATE_DIR": str(state_dir),
            "PLATFORM_MANAGED_OPERATION_TOKEN_FILE": str(
                secrets_dir / "managed-operation-token"
            ),
            "PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE": str(
                secrets_dir / "managed-operation-db-password"
            ),
            "PLATFORM_MANAGED_OPERATION_DATABASE_URL_FILE": str(
                secrets_dir / "managed-operation-database-url"
            ),
            "PLATFORM_MANAGED_OPERATION_GITHUB_TOKEN_FILE": str(
                secrets_dir / "managed-operation-github-token"
            ),
        }
    )
    if allowlist is not None:
        environment[ALLOWLIST_ENV] = allowlist
    return environment


def _bind_mount(service: dict[str, Any], target: str) -> dict[str, Any]:
    volumes = service.get("volumes")
    if not isinstance(volumes, list):
        raise RuntimeError(f"service omitted volumes for {target}")
    for volume in volumes:
        if isinstance(volume, dict) and volume.get("target") == target:
            return volume
    raise RuntimeError(f"service omitted required bind mount {target}")


def validate_hosted_managed_runtime_compose() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        missing = subprocess.run(
            _command(),
            cwd=REPO_ROOT,
            env=_environment(temp_root / "missing", allowlist=None),
            capture_output=True,
            text=True,
            check=False,
        )
        if missing.returncode == 0:
            raise RuntimeError("runtime Compose rendered without an allowlist")
        if ALLOWLIST_ENV not in f"{missing.stdout}\n{missing.stderr}":
            raise RuntimeError("missing allowlist failure omitted the variable name")

        configured = subprocess.run(
            _command(),
            cwd=REPO_ROOT,
            env=_environment(
                temp_root / "configured",
                allowlist=READ_ONLY_CANARY_OPERATION,
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        if configured.returncode != 0:
            raise RuntimeError(
                "configured runtime Compose did not render: "
                f"{configured.stderr.strip()}"
            )
        payload = json.loads(configured.stdout)

    services = payload.get("services")
    if not isinstance(services, dict) or set(services) != RUNTIME_SERVICES:
        raise RuntimeError("runtime Compose must contain exactly three services")

    for service_name in ("managed-operation-service", "managed-operation-worker"):
        service = services[service_name]
        environment = service.get("environment")
        if not isinstance(environment, dict) or environment.get(ALLOWLIST_ENV) != (
            READ_ONLY_CANARY_OPERATION
        ):
            raise RuntimeError(f"{service_name} did not receive the allowlist")
        if service.get("read_only") is not True:
            raise RuntimeError(f"{service_name} root filesystem must be read-only")
        if service.get("cap_drop") != ["ALL"]:
            raise RuntimeError(f"{service_name} must drop all Linux capabilities")
        if "no-new-privileges:true" not in service.get("security_opt", []):
            raise RuntimeError(f"{service_name} must disable privilege escalation")
        state_mount = _bind_mount(service, "/data/specspace-state")
        if state_mount.get("read_only") is not True:
            raise RuntimeError(f"{service_name} state mount must be read-only")

    service_artifacts = _bind_mount(
        services["managed-operation-service"], "/workspace/SpecGraph"
    )
    worker_artifacts = _bind_mount(
        services["managed-operation-worker"], "/workspace/SpecGraph"
    )
    if service_artifacts.get("read_only") is not True:
        raise RuntimeError("HTTP service artifact mount must be read-only")
    if worker_artifacts.get("read_only") is True:
        raise RuntimeError("worker artifact mount must allow authoritative reports")

    ports = services["managed-operation-service"].get("ports")
    if not isinstance(ports, list) or not any(
        isinstance(port, dict)
        and port.get("host_ip") == "127.0.0.1"
        and port.get("target") == 8091
        for port in ports
    ):
        raise RuntimeError("managed service must publish only on loopback")

    worker_command = services["managed-operation-worker"].get("command")
    command_text = " ".join(worker_command) if isinstance(worker_command, list) else ""
    if "/run/secrets/managed_operation_github_token" not in command_text:
        raise RuntimeError("worker must load GitHub credentials from a secret file")

    return {
        "artifact_kind": "platform_hosted_managed_runtime_compose_contract_report",
        "ok": True,
        "summary": {
            "missing_allowlist_blocked": True,
            "configured_allowlist_rendered": True,
            "runtime_service_count": len(services),
            "service_artifact_mount_read_only": True,
            "worker_artifact_mount_write_enabled": True,
            "service_loopback_only": True,
        },
    }


def main() -> int:
    try:
        report = validate_hosted_managed_runtime_compose()
    except (json.JSONDecodeError, OSError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "diagnostic": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
