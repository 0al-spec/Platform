"""Run a bounded hosted service/worker Compose health smoke."""

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
SERVICES = (
    "managed-operation-postgres",
    "managed-operation-service",
    "managed-operation-worker",
)
READ_ONLY_ALLOWLIST = "review_status_execute"


def _compose_command(project_name: str, env_file: Path) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        project_name,
        "--env-file",
        str(env_file),
    ]
    for compose_file in COMPOSE_FILES:
        command.extend(("--file", str(compose_file)))
    return command


def _run(
    command: list[str],
    *,
    environment: dict[str, str],
    timeout_seconds: int = 420,
) -> str:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        diagnostic = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Compose smoke command failed: {diagnostic}")
    return result.stdout


def _fixture_environment(root: Path) -> tuple[dict[str, str], Path]:
    org_root = root / "org"
    specgraph_dir = org_root / "SpecGraph"
    specgraph_dir.mkdir(parents=True)
    (specgraph_dir / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")

    token_file = root / "managed-operation-token"
    token_file.write_text(
        "hosted-compose-smoke-token-0123456789abcdef\n",
        encoding="utf-8",
    )
    token_file.chmod(0o600)
    password_file = root / "managed-operation-db-password"
    password_file.write_text("hosted-compose-smoke-password\n", encoding="utf-8")
    password_file.chmod(0o600)
    env_file = root / "empty.env"
    env_file.write_text("", encoding="utf-8")

    environment = dict(os.environ)
    environment.update(
        {
            "ORG_ROOT": str(org_root),
            "PLATFORM_MANAGED_OPERATION_TOKEN_FILE": str(token_file),
            "PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE": str(password_file),
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST": READ_ONLY_ALLOWLIST,
        }
    )
    return environment, env_file


def run_hosted_managed_compose_smoke() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix=".hosted-managed-compose-smoke-",
        dir=REPO_ROOT,
    ) as temp_dir:
        root = Path(temp_dir)
        environment, env_file = _fixture_environment(root)
        project_name = f"platform-hosted-smoke-{os.getpid()}"
        compose = _compose_command(project_name, env_file)
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
            service_health = json.loads(
                _run(
                    [
                        *compose,
                        "exec",
                        "--no-TTY",
                        "managed-operation-service",
                        "python3",
                        "-c",
                        (
                            "import urllib.request;"
                            "print(urllib.request.urlopen("
                            "'http://127.0.0.1:8091/v1/health',timeout=3)"
                            ".read().decode())"
                        ),
                    ],
                    environment=environment,
                )
            )
            worker_health = json.loads(
                _run(
                    [
                        *compose,
                        "exec",
                        "--no-TTY",
                        "managed-operation-worker",
                        "python3",
                        "-c",
                        (
                            "from pathlib import Path;"
                            "print(Path('/tmp/managed-operation-worker-health.json')"
                            ".read_text())"
                        ),
                    ],
                    environment=environment,
                )
            )
        finally:
            _run(
                [*compose, "down", "--volumes", "--remove-orphans"],
                environment=environment,
                timeout_seconds=120,
            )

    if service_health.get("ok") is not True:
        raise RuntimeError("hosted service health was not ready")
    if service_health.get("adapter") != "postgresql":
        raise RuntimeError("hosted service did not use PostgreSQL")
    if service_health.get("enabled_operation_ids") != [READ_ONLY_ALLOWLIST]:
        raise RuntimeError("hosted service did not enforce the read-only allowlist")
    if worker_health.get("ok") is not True:
        raise RuntimeError("hosted worker heartbeat was not ready")

    return {
        "artifact_kind": "platform_hosted_managed_compose_smoke_report",
        "ok": True,
        "summary": {
            "postgresql_ready": True,
            "service_ready": True,
            "worker_ready": True,
            "enabled_operation_ids": [READ_ONLY_ALLOWLIST],
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
        report = run_hosted_managed_compose_smoke()
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
