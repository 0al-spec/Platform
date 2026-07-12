"""Validate the TLS-fronted production hosted managed-operation profile."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.hosted-managed-production.example.yml"
ALLOWLIST_ENV = "PLATFORM_MANAGED_OPERATION_ALLOWLIST"
READ_ONLY_CANARY_OPERATION = "review_status_execute"
RUNTIME_SERVICES = {
    "managed-operation-postgres",
    "managed-operation-service",
    "managed-operation-worker",
    "managed-operation-ingress",
}
MAINTENANCE_SERVICE = "managed-operation-maintenance"
SHA256 = "1" * 64


def _command(*, maintenance: bool = False) -> list[str]:
    command = [
        "docker",
        "compose",
        "--file",
        str(COMPOSE_FILE),
    ]
    if maintenance:
        command.extend(("--profile", "maintenance"))
    command.extend(("config", "--format", "json"))
    return command


def _environment(temp_root: Path, *, allowlist: str | None) -> dict[str, str]:
    temp_root.mkdir(parents=True)
    artifact_root = temp_root / "specgraph"
    state_dir = temp_root / "state"
    secrets_dir = temp_root / "secrets"
    artifact_root.mkdir()
    state_dir.mkdir()
    backup_root = temp_root / "backups"
    backup_root.mkdir()
    secrets_dir.mkdir()
    secret_values = {
        "managed-operation-token": "fixture-token",
        "managed-operation-db-password": "fixture-password",
        "managed-operation-database-url": (
            "postgresql://managed_operations:fixture-password@"
            "managed-operation-postgres:5432/managed_operations"
        ),
        "managed-operation-github-token": "fixture-github-token",
        "managed-operation-tls-certificate": "fixture-certificate",
        "managed-operation-tls-private-key": "fixture-private-key",
    }
    for name, value in secret_values.items():
        (secrets_dir / name).write_text(value, encoding="utf-8")

    environment = dict(os.environ)
    environment.pop(ALLOWLIST_ENV, None)
    environment.update(
        {
            "PLATFORM_MANAGED_OPERATION_IMAGE": f"ghcr.io/0al/platform@sha256:{SHA256}",
            "PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE": f"postgres@sha256:{SHA256}",
            "PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE": f"caddy@sha256:{SHA256}",
            "PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT": str(artifact_root),
            "PLATFORM_MANAGED_OPERATION_STATE_DIR": str(state_dir),
            "PLATFORM_MANAGED_OPERATION_BACKUP_ROOT": str(backup_root),
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
            "PLATFORM_MANAGED_OPERATION_TLS_CERTIFICATE_FILE": str(
                secrets_dir / "managed-operation-tls-certificate"
            ),
            "PLATFORM_MANAGED_OPERATION_TLS_PRIVATE_KEY_FILE": str(
                secrets_dir / "managed-operation-tls-private-key"
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


def _assert_hardened(service_name: str, service: dict[str, Any]) -> None:
    if service.get("read_only") is not True:
        raise RuntimeError(f"{service_name} root filesystem must be read-only")
    if service.get("cap_drop") != ["ALL"]:
        raise RuntimeError(f"{service_name} must drop all Linux capabilities")
    if "no-new-privileges:true" not in service.get("security_opt", []):
        raise RuntimeError(f"{service_name} must disable privilege escalation")


def _assert_digest_pinned(service_name: str, service: dict[str, Any]) -> None:
    image = service.get("image")
    if not isinstance(image, str) or "@sha256:" not in image:
        raise RuntimeError(f"{service_name} image must be pinned by sha256 digest")


def validate_hosted_managed_production_compose() -> dict[str, Any]:
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
            raise RuntimeError("production Compose rendered without an allowlist")
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
                "configured production Compose did not render: "
                f"{configured.stderr.strip()}"
            )
        payload = json.loads(configured.stdout)

    services = payload.get("services")
    if not isinstance(services, dict) or set(services) != RUNTIME_SERVICES:
        raise RuntimeError("production Compose must contain exactly four runtime services")

    with tempfile.TemporaryDirectory() as temp_dir:
        maintenance_render = subprocess.run(
            _command(maintenance=True),
            cwd=REPO_ROOT,
            env=_environment(
                Path(temp_dir) / "maintenance",
                allowlist=READ_ONLY_CANARY_OPERATION,
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        if maintenance_render.returncode != 0:
            raise RuntimeError("maintenance profile did not render")
        maintenance_payload = json.loads(maintenance_render.stdout)
    maintenance_services = maintenance_payload.get("services")
    if not isinstance(maintenance_services, dict) or set(maintenance_services) != (
        RUNTIME_SERVICES | {MAINTENANCE_SERVICE}
    ):
        raise RuntimeError("maintenance profile must add exactly one service")
    maintenance = maintenance_services[MAINTENANCE_SERVICE]

    for service_name, service in services.items():
        _assert_digest_pinned(service_name, service)
    _assert_digest_pinned(MAINTENANCE_SERVICE, maintenance)

    for service_name in (
        "managed-operation-service",
        "managed-operation-worker",
        "managed-operation-ingress",
    ):
        _assert_hardened(service_name, services[service_name])
    _assert_hardened(MAINTENANCE_SERVICE, maintenance)

    for service_name in ("managed-operation-service", "managed-operation-worker"):
        environment = services[service_name].get("environment")
        if not isinstance(environment, dict) or environment.get(ALLOWLIST_ENV) != (
            READ_ONLY_CANARY_OPERATION
        ):
            raise RuntimeError(f"{service_name} did not receive the canary allowlist")
        state_mount = _bind_mount(service=services[service_name], target="/data/specspace-state")
        if state_mount.get("read_only") is not True:
            raise RuntimeError(f"{service_name} state mount must be read-only")

    service = services["managed-operation-service"]
    worker = services["managed-operation-worker"]
    ingress = services["managed-operation-ingress"]
    if service.get("ports"):
        raise RuntimeError("managed service must not publish a host port")
    service_artifacts = _bind_mount(service, "/workspace/SpecGraph")
    worker_artifacts = _bind_mount(worker, "/workspace/SpecGraph")
    if service_artifacts.get("read_only") is not True:
        raise RuntimeError("HTTP service artifact mount must be read-only")
    if worker_artifacts.get("read_only") is True:
        raise RuntimeError("worker artifact mount must allow authoritative reports")

    ingress_ports = ingress.get("ports")
    if not (
        isinstance(ingress_ports, list)
        and len(ingress_ports) == 1
        and ingress_ports[0].get("target") == 8443
        and ingress_ports[0].get("published") == "443"
    ):
        raise RuntimeError("TLS ingress must be the only published production port")
    if ingress.get("user") != "1000:1000":
        raise RuntimeError("TLS ingress must run as the unprivileged runtime user")
    if ingress.get("entrypoint") != ["/bin/sh", "-ec"]:
        raise RuntimeError("TLS ingress must strip upstream file capabilities in tmpfs")
    ingress_command = ingress.get("command")
    ingress_command_text = (
        " ".join(ingress_command) if isinstance(ingress_command, list) else ""
    )
    if not all(
        token in ingress_command_text
        for token in (
            "cp /usr/bin/caddy /tmp/caddy-runtime",
            "exec /tmp/caddy-runtime run",
        )
    ):
        raise RuntimeError("TLS ingress runtime command may retain upstream file capabilities")
    caddyfile = _bind_mount(ingress, "/etc/caddy/Caddyfile")
    if caddyfile.get("read_only") is not True:
        raise RuntimeError("TLS ingress Caddyfile must be read-only")
    if maintenance.get("profiles") != ["maintenance"]:
        raise RuntimeError("backup tooling must remain an explicit maintenance profile")
    if maintenance.get("user") != "1000:1000":
        raise RuntimeError("backup tooling must run as the unprivileged runtime user")
    maintenance_artifacts = _bind_mount(maintenance, "/workspace/SpecGraph")
    maintenance_backups = _bind_mount(maintenance, "/backups")
    if maintenance_artifacts.get("read_only") is not True:
        raise RuntimeError("backup tooling must read artifacts without mutation authority")
    if maintenance_backups.get("read_only") is True:
        raise RuntimeError("backup tooling requires only its dedicated writable backup root")

    networks = payload.get("networks")
    if not isinstance(networks, dict):
        raise RuntimeError("production Compose omitted networks")
    backend_names = [name for name, value in networks.items() if value.get("internal")]
    if len(backend_names) != 1:
        raise RuntimeError("production Compose must have one internal backend network")
    backend_name = backend_names[0]
    for service_name in (
        "managed-operation-postgres",
        "managed-operation-service",
        "managed-operation-ingress",
    ):
        if set(services[service_name].get("networks", {})) != {backend_name}:
            raise RuntimeError(f"{service_name} must use only the internal network")
    worker_networks = set(worker.get("networks", {}))
    if backend_name not in worker_networks or len(worker_networks) != 2:
        raise RuntimeError("worker must have internal queue access and one egress network")

    return {
        "artifact_kind": "platform_hosted_managed_production_compose_contract_report",
        "ok": True,
        "summary": {
            "missing_allowlist_blocked": True,
            "read_only_canary_allowlist": True,
            "runtime_service_count": len(services),
            "digest_pinned_images": True,
            "service_direct_port_absent": True,
            "tls_ingress_only": True,
            "internal_backend_network": True,
            "worker_egress_only": True,
            "maintenance_profile_isolated": True,
        },
    }


def main() -> int:
    try:
        report = validate_hosted_managed_production_compose()
    except (json.JSONDecodeError, OSError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "diagnostic": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
