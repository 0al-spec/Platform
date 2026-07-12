"""Run the TLS-fronted production Compose profile without enqueueing work."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import time
from typing import Any
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.hosted-managed-production.example.yml"
SERVICES = (
    "managed-operation-postgres",
    "managed-operation-service",
    "managed-operation-worker",
    "managed-operation-ingress",
)


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    timeout_seconds: int = 420,
) -> str:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"production Compose smoke command failed: {diagnostic[-500:]}")
    return completed.stdout.strip()


def _repo_digest(image: str) -> str:
    payload = json.loads(_run(["docker", "image", "inspect", image]))
    digests = payload[0].get("RepoDigests") if isinstance(payload, list) and payload else []
    if not isinstance(digests, list) or not digests:
        raise RuntimeError(f"image {image} did not expose a repository digest")
    return str(digests[0])


def _wait_registry(port: int) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v2/", timeout=1):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("temporary image registry did not become ready")


def _fixture(root: Path, *, platform_image: str, ingress_port: int) -> dict[str, str]:
    artifact_root = root / "specgraph"
    state_dir = root / "state"
    backup_root = root / "backups"
    secrets = root / "secrets"
    for directory in (artifact_root / "runs", state_dir, backup_root, secrets):
        directory.mkdir(parents=True)
    (artifact_root / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")

    password = "production-compose-smoke-password"
    secret_values = {
        "service-token": "production-compose-smoke-token-0123456789abcdef",
        "database-password": password,
        "database-url": (
            "postgresql://managed_operations:"
            f"{password}@managed-operation-postgres:5432/managed_operations"
        ),
        "github-token": "production-compose-smoke-github-token",
    }
    for name, value in secret_values.items():
        path = secrets / name
        path.write_text(value + "\n", encoding="utf-8")
        path.chmod(0o444)

    certificate = secrets / "tls-certificate.pem"
    private_key = secrets / "tls-private-key.pem"
    _run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ]
    )
    private_key.chmod(0o444)
    certificate.chmod(0o444)

    environment = dict(os.environ)
    environment.update(
        {
            "PLATFORM_MANAGED_OPERATION_IMAGE": platform_image,
            "PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE": _repo_digest(
                "postgres:16-alpine"
            ),
            "PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE": _repo_digest("caddy:2-alpine"),
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST": "review_status_execute",
            "PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT": str(artifact_root),
            "PLATFORM_MANAGED_OPERATION_STATE_DIR": str(state_dir),
            "PLATFORM_MANAGED_OPERATION_BACKUP_ROOT": str(backup_root),
            "PLATFORM_MANAGED_OPERATION_INGRESS_BIND_IP": "127.0.0.1",
            "PLATFORM_MANAGED_OPERATION_INGRESS_PORT": str(ingress_port),
            "PLATFORM_MANAGED_OPERATION_TOKEN_FILE": str(secrets / "service-token"),
            "PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE": str(
                secrets / "database-password"
            ),
            "PLATFORM_MANAGED_OPERATION_DATABASE_URL_FILE": str(
                secrets / "database-url"
            ),
            "PLATFORM_MANAGED_OPERATION_GITHUB_TOKEN_FILE": str(
                secrets / "github-token"
            ),
            "PLATFORM_MANAGED_OPERATION_TLS_CERTIFICATE_FILE": str(certificate),
            "PLATFORM_MANAGED_OPERATION_TLS_PRIVATE_KEY_FILE": str(private_key),
        }
    )
    return environment


def run_smoke() -> dict[str, Any]:
    registry_port = _port()
    ingress_port = _port()
    registry_name = f"platform-production-smoke-registry-{os.getpid()}"
    project_name = f"platform-production-smoke-{os.getpid()}"
    registry_image = f"127.0.0.1:{registry_port}/platform:smoke"
    compose = [
        "docker",
        "compose",
        "--project-name",
        project_name,
        "--file",
        str(COMPOSE_FILE),
    ]
    environment: dict[str, str] | None = None
    try:
        for image in ("registry:2", "postgres:16-alpine", "caddy:2-alpine"):
            _run(["docker", "pull", image])
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                registry_name,
                "--publish",
                f"127.0.0.1:{registry_port}:5000",
                "registry:2",
            ]
        )
        _wait_registry(registry_port)
        _run(
            [
                "docker",
                "build",
                "--file",
                str(REPO_ROOT / "Dockerfile.hosted-managed"),
                "--tag",
                registry_image,
                ".",
            ]
        )
        _run(["docker", "push", registry_image])
        platform_image = _repo_digest(registry_image)

        with tempfile.TemporaryDirectory(
            prefix=".hosted-managed-production-smoke-", dir=REPO_ROOT
        ) as temp_dir:
            environment = _fixture(
                Path(temp_dir),
                platform_image=platform_image,
                ingress_port=ingress_port,
            )
            try:
                _run(
                    [
                        *compose,
                        "up",
                        "--detach",
                        "--wait",
                        "--wait-timeout",
                        "300",
                        *SERVICES,
                    ],
                    environment=environment,
                )
            except RuntimeError as exc:
                try:
                    logs = _run(
                        [
                            *compose,
                            "logs",
                            "--no-color",
                            "--tail",
                            "80",
                            "managed-operation-ingress",
                        ],
                        environment=environment,
                        timeout_seconds=30,
                    )
                except RuntimeError:
                    logs = "ingress logs unavailable"
                raise RuntimeError(f"{exc}; ingress logs: {logs[-1500:]}") from exc
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(
                f"https://127.0.0.1:{ingress_port}/v1/health",
                context=context,
                timeout=5,
            ) as response:
                ingress_health = json.loads(response.read().decode("utf-8"))
            worker_health = json.loads(
                _run(
                    [
                        *compose,
                        "exec",
                        "--no-TTY",
                        "managed-operation-worker",
                        "cat",
                        "/tmp/managed-operation-worker-health.json",
                    ],
                    environment=environment,
                )
            )
    finally:
        if environment is not None:
            try:
                _run(
                    [*compose, "down", "--volumes", "--remove-orphans"],
                    environment=environment,
                    timeout_seconds=120,
                )
            except RuntimeError:
                pass
        subprocess.run(
            ["docker", "rm", "--force", registry_name],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    if ingress_health.get("ok") is not True or ingress_health.get("adapter") != "postgresql":
        raise RuntimeError("TLS ingress did not expose PostgreSQL-backed service health")
    operations = ingress_health.get("operations")
    operations = operations if isinstance(operations, dict) else {}
    if operations.get("enabled_operation_ids") != ["review_status_execute"]:
        raise RuntimeError("TLS ingress exposed an expanded operation allowlist")
    if worker_health.get("ok") is not True or worker_health.get("adapter") != "postgresql":
        raise RuntimeError("production worker heartbeat was not PostgreSQL-ready")
    return {
        "artifact_kind": "platform_hosted_managed_production_compose_smoke_report",
        "ok": True,
        "summary": {
            "tls_ingress_ready": True,
            "postgresql_ready": True,
            "service_ready": True,
            "worker_ready": True,
            "enabled_operation_ids": ["review_status_execute"],
            "managed_requests_executed": 0,
        },
        "authority_boundary": {
            "executes_managed_operations": False,
            "opens_pull_requests": False,
            "publishes_read_model": False,
        },
    }


def main() -> int:
    try:
        report = run_smoke()
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"ok": False, "diagnostic": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
