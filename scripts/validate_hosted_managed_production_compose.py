"""Validate the TLS-fronted production hosted managed-operation profile."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

try:
    from scripts import hosted_managed_worker_window
    from scripts.hosted_managed_production_profiles import (
        PROMOTION_DRY_RUN_PROFILE_ID,
        profile_by_id,
    )
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_worker_window
    from hosted_managed_production_profiles import (
        PROMOTION_DRY_RUN_PROFILE_ID,
        profile_by_id,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.hosted-managed-production.example.yml"
INGRESS_DOCKERFILE = REPO_ROOT / "Dockerfile.hosted-managed-ingress"
WORKER_WINDOW_POLICY = (
    REPO_ROOT / "deploy" / "hosted-managed" / "worker-window-policy.json"
)
PROMOTION_DRY_RUN_WORKER_WINDOW_POLICY = (
    REPO_ROOT
    / "deploy"
    / "hosted-managed"
    / "promotion-dry-run-worker-window-policy.json"
)
ALLOWLIST_ENV = "PLATFORM_MANAGED_OPERATION_ALLOWLIST"
READ_ONLY_CANARY_OPERATION = "review_status_execute"
RUNTIME_SERVICES = {
    "managed-operation-postgres",
    "managed-operation-service",
    "managed-operation-ingress",
}
CONTINUOUS_WORKER_SERVICE = "managed-operation-worker"
MAINTENANCE_SERVICE = "managed-operation-maintenance"
WINDOW_WORKER_SERVICE = "managed-operation-window-worker"
PROMOTION_DRY_RUN_WINDOW_WORKER_SERVICE = (
    "managed-operation-promotion-dry-run-window-worker"
)
SHA256 = "1" * 64


def _command(*, profile: str | None = None) -> list[str]:
    command = [
        "docker",
        "compose",
        "--file",
        str(COMPOSE_FILE),
    ]
    if profile is not None:
        command.extend(("--profile", profile))
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
    hosted_managed_worker_window.load_policy(WORKER_WINDOW_POLICY.resolve())
    dry_run_profile = profile_by_id(PROMOTION_DRY_RUN_PROFILE_ID)
    hosted_managed_worker_window.load_policy(
        PROMOTION_DRY_RUN_WORKER_WINDOW_POLICY.resolve()
    )
    ingress_dockerfile = INGRESS_DOCKERFILE.read_text(encoding="utf-8")
    if "ARG CADDY_BASE_IMAGE\n" not in ingress_dockerfile or (
        "ARG CADDY_BASE_IMAGE=" in ingress_dockerfile
    ):
        raise RuntimeError("ingress build must require an explicit Caddy base image")
    if "setcap -r /usr/bin/caddy" not in ingress_dockerfile:
        raise RuntimeError("ingress build must remove the upstream file capability")
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
        raise RuntimeError("production Compose must contain exactly three runtime services")

    with tempfile.TemporaryDirectory() as temp_dir:
        maintenance_render = subprocess.run(
            _command(profile="maintenance"),
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

    with tempfile.TemporaryDirectory() as temp_dir:
        window_render = subprocess.run(
            _command(profile="bounded-worker"),
            cwd=REPO_ROOT,
            env=_environment(
                Path(temp_dir) / "bounded-worker",
                allowlist=READ_ONLY_CANARY_OPERATION,
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        if window_render.returncode != 0:
            raise RuntimeError("bounded-worker profile did not render")
        window_payload = json.loads(window_render.stdout)
    window_services = window_payload.get("services")
    if not isinstance(window_services, dict) or set(window_services) != (
        RUNTIME_SERVICES | {WINDOW_WORKER_SERVICE}
    ):
        raise RuntimeError("bounded-worker profile must add exactly one service")
    window_worker = window_services[WINDOW_WORKER_SERVICE]

    with tempfile.TemporaryDirectory() as temp_dir:
        dry_run_render = subprocess.run(
            _command(profile=dry_run_profile.compose_profile),
            cwd=REPO_ROOT,
            env=_environment(
                Path(temp_dir) / "promotion-dry-run-window",
                allowlist=dry_run_profile.operation_id,
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        if dry_run_render.returncode != 0:
            raise RuntimeError("promotion-dry-run-window profile did not render")
        dry_run_payload = json.loads(dry_run_render.stdout)
    dry_run_services = dry_run_payload.get("services")
    if not isinstance(dry_run_services, dict) or set(dry_run_services) != (
        RUNTIME_SERVICES | {PROMOTION_DRY_RUN_WINDOW_WORKER_SERVICE}
    ):
        raise RuntimeError(
            "promotion-dry-run-window profile must add exactly one service"
        )
    dry_run_worker = dry_run_services[PROMOTION_DRY_RUN_WINDOW_WORKER_SERVICE]

    with tempfile.TemporaryDirectory() as temp_dir:
        continuous_render = subprocess.run(
            _command(profile="continuous-worker"),
            cwd=REPO_ROOT,
            env=_environment(
                Path(temp_dir) / "continuous-worker",
                allowlist=READ_ONLY_CANARY_OPERATION,
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        if continuous_render.returncode != 0:
            raise RuntimeError("continuous-worker profile did not render")
        continuous_payload = json.loads(continuous_render.stdout)
    continuous_services = continuous_payload.get("services")
    if not isinstance(continuous_services, dict) or set(continuous_services) != (
        RUNTIME_SERVICES | {CONTINUOUS_WORKER_SERVICE}
    ):
        raise RuntimeError("continuous-worker profile must add exactly one service")
    worker = continuous_services[CONTINUOUS_WORKER_SERVICE]

    for service_name, service in services.items():
        _assert_digest_pinned(service_name, service)
    _assert_digest_pinned(MAINTENANCE_SERVICE, maintenance)
    _assert_digest_pinned(WINDOW_WORKER_SERVICE, window_worker)
    _assert_digest_pinned(
        PROMOTION_DRY_RUN_WINDOW_WORKER_SERVICE,
        dry_run_worker,
    )
    _assert_digest_pinned(CONTINUOUS_WORKER_SERVICE, worker)

    for service_name in (
        "managed-operation-service",
        "managed-operation-ingress",
    ):
        _assert_hardened(service_name, services[service_name])
    _assert_hardened(MAINTENANCE_SERVICE, maintenance)
    _assert_hardened(WINDOW_WORKER_SERVICE, window_worker)
    _assert_hardened(
        PROMOTION_DRY_RUN_WINDOW_WORKER_SERVICE,
        dry_run_worker,
    )
    _assert_hardened(CONTINUOUS_WORKER_SERVICE, worker)

    for service_name, service_definition in (
        ("managed-operation-service", services["managed-operation-service"]),
        (CONTINUOUS_WORKER_SERVICE, worker),
    ):
        environment = service_definition.get("environment")
        if not isinstance(environment, dict) or environment.get(ALLOWLIST_ENV) != (
            READ_ONLY_CANARY_OPERATION
        ):
            raise RuntimeError(f"{service_name} did not receive the canary allowlist")
        state_mount = _bind_mount(
            service=service_definition,
            target="/data/specspace-state",
        )
        if state_mount.get("read_only") is not True:
            raise RuntimeError(f"{service_name} state mount must be read-only")

    service = services["managed-operation-service"]
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
    if ingress.get("init") is not True:
        raise RuntimeError("TLS ingress must use an init process to reap health checks")
    ingress_command = ingress.get("command")
    if ingress_command != [
        "run",
        "--config",
        "/etc/caddy/Caddyfile",
        "--adapter",
        "caddyfile",
    ]:
        raise RuntimeError("TLS ingress must use the fixed Caddy entrypoint contract")
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
    if window_worker.get("profiles") != ["bounded-worker"]:
        raise RuntimeError("bounded worker must remain an explicit profile")
    if window_worker.get("restart") not in (None, "no"):
        raise RuntimeError("bounded worker must not have a restart policy")
    window_environment = window_worker.get("environment")
    if not isinstance(window_environment, dict) or window_environment.get(
        ALLOWLIST_ENV
    ) != READ_ONLY_CANARY_OPERATION:
        raise RuntimeError("bounded worker did not receive the read-only allowlist")
    window_command = window_worker.get("command")
    window_command_text = (
        " ".join(window_command) if isinstance(window_command, list) else ""
    )
    for required_fragment in (
        "managed-operation worker-window",
        "--expected-request-id",
        "--window-id",
        "/workspace/Platform/deploy/hosted-managed/worker-window-policy.json",
    ):
        if required_fragment not in window_command_text:
            raise RuntimeError("bounded worker command contract is incomplete")
    window_artifacts = _bind_mount(window_worker, "/workspace/SpecGraph")
    window_state = _bind_mount(window_worker, "/data/specspace-state")
    if window_artifacts.get("read_only") is True:
        raise RuntimeError("bounded worker must write authoritative reports")
    if window_state.get("read_only") is not True:
        raise RuntimeError("bounded worker state mount must be read-only")
    if worker.get("profiles") != ["continuous-worker"]:
        raise RuntimeError("continuous worker must require an explicit profile")
    continuous_command = worker.get("command")
    continuous_command_text = (
        " ".join(continuous_command)
        if isinstance(continuous_command, list)
        else ""
    )
    if (
        'test "$${PLATFORM_MANAGED_OPERATION_ALLOWLIST}" = '
        '"review_status_execute"'
        not in continuous_command_text
    ):
        raise RuntimeError(
            "continuous worker must fail closed outside the review-status profile"
        )

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
    ):
        if set(services[service_name].get("networks", {})) != {backend_name}:
            raise RuntimeError(f"{service_name} must use only the internal network")
    worker_networks = set(worker.get("networks", {}))
    if backend_name not in worker_networks or len(worker_networks) != 2:
        raise RuntimeError("worker must have internal queue access and one egress network")
    ingress_networks = set(ingress.get("networks", {}))
    if backend_name not in ingress_networks or len(ingress_networks) != 2:
        raise RuntimeError("TLS ingress must have internal service access and one ingress network")
    if worker_networks == ingress_networks:
        raise RuntimeError("worker egress and public ingress networks must remain separate")
    if set(window_worker.get("networks", {})) != worker_networks:
        raise RuntimeError("bounded worker must use the worker network boundary")
    if dry_run_worker.get("profiles") != [dry_run_profile.compose_profile]:
        raise RuntimeError(
            "promotion dry-run worker must remain an explicit profile"
        )
    if dry_run_worker.get("restart") not in (None, "no"):
        raise RuntimeError("promotion dry-run worker must not have a restart policy")
    dry_run_environment = dry_run_worker.get("environment")
    if not isinstance(dry_run_environment, dict) or dry_run_environment.get(
        ALLOWLIST_ENV
    ) != dry_run_profile.operation_id:
        raise RuntimeError(
            "promotion dry-run worker did not receive the exact dry-run allowlist"
        )
    dry_run_command = dry_run_worker.get("command")
    dry_run_command_text = (
        " ".join(dry_run_command) if isinstance(dry_run_command, list) else ""
    )
    for required_fragment in (
        "managed-operation worker-window",
        "--expected-request-id",
        "--window-id",
        "/workspace/Platform/deploy/hosted-managed/"
        "promotion-dry-run-worker-window-policy.json",
    ):
        if required_fragment not in dry_run_command_text:
            raise RuntimeError(
                "promotion dry-run worker command contract is incomplete"
            )
    dry_run_artifacts = _bind_mount(dry_run_worker, "/workspace/SpecGraph")
    dry_run_state = _bind_mount(dry_run_worker, "/data/specspace-state")
    if dry_run_artifacts.get("read_only") is True:
        raise RuntimeError(
            "promotion dry-run worker must write authoritative reports"
        )
    if dry_run_state.get("read_only") is not True:
        raise RuntimeError("promotion dry-run worker state mount must be read-only")
    if set(dry_run_worker.get("networks", {})) != worker_networks:
        raise RuntimeError(
            "promotion dry-run worker must use the worker network boundary"
        )
    dry_run_service_environment = dry_run_services[
        "managed-operation-service"
    ].get("environment")
    if (
        not isinstance(dry_run_service_environment, dict)
        or dry_run_service_environment.get(ALLOWLIST_ENV)
        != dry_run_profile.operation_id
    ):
        raise RuntimeError(
            "managed service did not receive the promotion dry-run allowlist"
        )

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
            "bounded_worker_profile_isolated": True,
            "bounded_worker_policy_validated": True,
            "promotion_dry_run_profile_isolated": True,
            "promotion_dry_run_policy_validated": True,
            "promotion_dry_run_continuous_worker_forbidden": True,
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
