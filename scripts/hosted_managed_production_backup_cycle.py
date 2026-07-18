"""Run one fail-closed production backup and isolated restore-smoke cycle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

try:
    from scripts.hosted_managed_production_probe import (
        ProductionProbeError,
        run_probe,
    )
    from scripts.hosted_managed_runtime_backup import BACKUP_ID_PATTERN
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    from hosted_managed_production_probe import ProductionProbeError, run_probe
    from hosted_managed_runtime_backup import BACKUP_ID_PATTERN


DEFAULT_COMPOSE_FILE = Path(
    "/srv/0al/platform/docker-compose.hosted-managed-production.example.yml"
)
DEFAULT_ENV_FILE = Path("/etc/0al/hosted-managed-production.env")
DEFAULT_BACKUP_ROOT = Path("/srv/0al/backups")
DEFAULT_PROBE_OUTPUT = Path("/srv/0al/evidence/probe-before-reboot.json")
DEFAULT_BACKUP_ID_OUTPUT = Path("/srv/0al/evidence/current-backup-id.txt")
DEFAULT_OUTPUT = Path("/srv/0al/evidence/hosted-managed-backup-cycle.json")
DEFAULT_SERVICE_URL = "https://managed.specgraph.tech"
DEFAULT_PROJECT_NAME = "platform-managed-production"
RUNTIME_SERVICES = (
    "specspace-state-service",
    "managed-operation-service",
    "managed-operation-ingress",
)
MINIMUM_HOST_PYTHON = (3, 12)
MAXIMUM_HOST_PYTHON = (3, 15)


class ProductionBackupCycleError(RuntimeError):
    """The backup cycle cannot continue without weakening its safety contract."""


Runner = Callable[..., subprocess.CompletedProcess[str]]
Probe = Callable[..., dict[str, Any]]
Sleep = Callable[[float], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_supported_python(version_info: tuple[int, ...] | Any) -> None:
    version = tuple(version_info[:2])
    if not MINIMUM_HOST_PYTHON <= version < MAXIMUM_HOST_PYTHON:
        raise ProductionBackupCycleError(
            "production backup requires Python 3.12, 3.13, or 3.14"
        )


def _write_atomic(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _run(
    command: list[str],
    *,
    runner: Runner,
    label: str,
) -> str:
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ProductionBackupCycleError(f"{label} failed")
    return completed.stdout


def _json_command(
    command: list[str],
    *,
    runner: Runner,
    label: str,
) -> dict[str, Any]:
    output = _run(command, runner=runner, label=label)
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ProductionBackupCycleError(f"{label} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ProductionBackupCycleError(f"{label} report must be an object")
    return payload


def _compose_prefix(
    *, env_file: Path, compose_file: Path, project_name: str
) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--project-name",
        project_name,
        "--file",
        str(compose_file),
    ]


def _maintenance_command(prefix: list[str], *args: str) -> list[str]:
    return [
        *prefix,
        "--profile",
        "maintenance",
        "run",
        "--rm",
        "--no-deps",
        "managed-operation-maintenance",
        "python3",
        *args,
    ]


def _queue_audit(prefix: list[str], *, runner: Runner) -> dict[str, Any]:
    report = _json_command(
        _maintenance_command(
            prefix,
            "scripts/hosted_managed_production_signoff.py",
            "queue-audit",
            "--database-url-file",
            "/run/secrets/managed_operation_database_url",
        ),
        runner=runner,
        label="production queue audit",
    )
    summary = report.get("summary")
    if (
        report.get("ok") is not True
        or not isinstance(summary, dict)
        or summary.get("rollback_ready") is not True
        or summary.get("active_job_count") != 0
        or summary.get("lock_count") != 0
    ):
        raise ProductionBackupCycleError(
            "production backup requires a drained queue without locks"
        )
    return report


def _backup_command(
    prefix: list[str], *, backup_id: str, runner: Runner
) -> dict[str, Any]:
    report = _json_command(
        _maintenance_command(
            prefix,
            "scripts/hosted_managed_runtime_backup.py",
            "backup",
            "--database-url-file",
            "/run/secrets/managed_operation_database_url",
            "--state-database-url-file",
            "/run/secrets/specspace_state_database_url",
            "--artifact-root",
            "/workspace/SpecGraph",
            "--backup-root",
            "/backups",
            "--backup-id",
            backup_id,
        ),
        runner=runner,
        label="private production backup",
    )
    if report.get("ok") is not True or report.get("summary", {}).get(
        "status"
    ) != "backup_ready":
        raise ProductionBackupCycleError("private production backup is not ready")
    return report


def _restore_smoke_command(
    prefix: list[str], *, backup_id: str, runner: Runner
) -> dict[str, Any]:
    report = _json_command(
        _maintenance_command(
            prefix,
            "scripts/hosted_managed_runtime_backup.py",
            "restore-smoke",
            "--database-url-file",
            "/run/secrets/managed_operation_database_url",
            "--state-database-url-file",
            "/run/secrets/specspace_state_database_url",
            "--backup-root",
            "/backups",
            "--backup-id",
            backup_id,
            "--output",
            f"/backups/{backup_id}/restore-smoke-report.json",
        ),
        runner=runner,
        label="isolated restore smoke",
    )
    summary = report.get("summary")
    if (
        report.get("ok") is not True
        or not isinstance(summary, dict)
        or summary.get("status") != "restore_smoke_passed"
        or summary.get("database_row_counts_verified") is not True
        or summary.get("state_database_row_counts_verified") is not True
        or summary.get("artifact_inventory_verified") is not True
        or summary.get("temporary_database_removed") is not True
    ):
        raise ProductionBackupCycleError("isolated restore smoke is not ready")
    return report


def _verify_backup_outputs(*, backup_root: Path, backup_id: str) -> None:
    backup_directory = backup_root / backup_id
    if backup_directory.is_symlink() or not backup_directory.is_dir():
        raise ProductionBackupCycleError("private backup directory is unavailable")
    for name in (
        "backup-report.json",
        "managed-operations.json",
        "specspace-state.json",
        "restore-smoke-report.json",
        "workspace-artifacts.tar.gz",
    ):
        path = backup_directory / name
        if path.is_symlink() or not path.is_file():
            raise ProductionBackupCycleError("private backup output set is incomplete")


def _probe(
    *,
    service_url: str,
    compose_file: Path,
    env_file: Path,
    project_name: str,
    probe: Probe,
    runner: Runner,
) -> dict[str, Any]:
    report = probe(
        service_url=service_url,
        compose_file=compose_file,
        env_file=env_file,
        project_name=project_name,
        runner=runner,
    )
    if report.get("ok") is not True:
        raise ProductionBackupCycleError("production runtime probe is not ready")
    return report


def _wait_for_probe(
    *,
    service_url: str,
    compose_file: Path,
    env_file: Path,
    project_name: str,
    probe: Probe,
    runner: Runner,
    sleep: Sleep,
    attempts: int,
    delay_seconds: float,
) -> dict[str, Any]:
    for attempt in range(attempts):
        try:
            return _probe(
                service_url=service_url,
                compose_file=compose_file,
                env_file=env_file,
                project_name=project_name,
                probe=probe,
                runner=runner,
            )
        except (ProductionBackupCycleError, ProductionProbeError):
            if attempt + 1 == attempts:
                break
            sleep(delay_seconds)
    raise ProductionBackupCycleError(
        "production runtime did not recover after the backup cycle"
    )


def run_backup_cycle(
    *,
    backup_id: str,
    service_url: str,
    compose_file: Path,
    env_file: Path,
    project_name: str,
    backup_root: Path,
    probe_output: Path,
    backup_id_output: Path,
    runner: Runner = subprocess.run,
    probe: Probe = run_probe,
    sleep: Sleep = time.sleep,
    recovery_attempts: int = 40,
    recovery_delay_seconds: float = 3.0,
) -> dict[str, Any]:
    generated_at = _now_iso()
    diagnostics: list[str] = []
    phases: list[dict[str, Any]] = []
    backup_report: dict[str, Any] | None = None
    restore_report: dict[str, Any] | None = None
    runtime_quiesced = False
    runtime_recovered = False
    if not BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise ProductionBackupCycleError("backup id is invalid")
    for path, label in (
        (compose_file, "Compose file"),
        (env_file, "environment file"),
        (backup_root, "backup root"),
        (probe_output, "probe output"),
        (backup_id_output, "backup id output"),
    ):
        if not path.is_absolute():
            raise ProductionBackupCycleError(f"{label} must be absolute")
    prefix = _compose_prefix(
        env_file=env_file,
        compose_file=compose_file,
        project_name=project_name,
    )

    try:
        before_probe = _probe(
            service_url=service_url,
            compose_file=compose_file,
            env_file=env_file,
            project_name=project_name,
            probe=probe,
            runner=runner,
        )
        _write_atomic(
            probe_output,
            json.dumps(before_probe, indent=2, sort_keys=True) + "\n",
            mode=0o444,
        )
        phases.append({"phase": "probe_before_backup", "status": "passed"})
        _queue_audit(prefix, runner=runner)
        phases.append({"phase": "queue_audit_before_quiesce", "status": "passed"})

        runtime_quiesced = True
        _run(
            [
                *prefix,
                "stop",
                "managed-operation-ingress",
                "managed-operation-service",
                "specspace-state-service",
            ],
            runner=runner,
            label="mutable state and enqueue boundary quiesce",
        )
        phases.append(
            {
                "phase": "mutable_state_and_enqueue_boundary_quiesce",
                "status": "passed",
            }
        )
        _queue_audit(prefix, runner=runner)
        phases.append({"phase": "queue_audit_after_quiesce", "status": "passed"})
        _run(
            [
                *prefix,
                "--profile",
                "continuous-worker",
                "stop",
                "managed-operation-worker",
            ],
            runner=runner,
            label="worker stop after drain",
        )
        phases.append({"phase": "worker_stop_after_drain", "status": "passed"})

        backup_report = _backup_command(
            prefix, backup_id=backup_id, runner=runner
        )
        phases.append({"phase": "private_backup", "status": "passed"})
        restore_report = _restore_smoke_command(
            prefix, backup_id=backup_id, runner=runner
        )
        phases.append({"phase": "isolated_restore_smoke", "status": "passed"})
        _verify_backup_outputs(backup_root=backup_root, backup_id=backup_id)
        phases.append({"phase": "backup_output_verification", "status": "passed"})
        _write_atomic(backup_id_output, f"{backup_id}\n", mode=0o444)
    except (ProductionBackupCycleError, ProductionProbeError) as exc:
        diagnostics.append(str(exc))
    finally:
        if runtime_quiesced:
            try:
                _run(
                    [*prefix, "up", "--detach", *RUNTIME_SERVICES],
                    runner=runner,
                    label="production runtime restart",
                )
                _wait_for_probe(
                    service_url=service_url,
                    compose_file=compose_file,
                    env_file=env_file,
                    project_name=project_name,
                    probe=probe,
                    runner=runner,
                    sleep=sleep,
                    attempts=recovery_attempts,
                    delay_seconds=recovery_delay_seconds,
                )
                runtime_recovered = True
                phases.append({"phase": "runtime_restart", "status": "passed"})
            except (ProductionBackupCycleError, ProductionProbeError) as exc:
                diagnostics.append(str(exc))
                phases.append({"phase": "runtime_restart", "status": "failed"})

    ok = (
        not diagnostics
        and backup_report is not None
        and restore_report is not None
        and runtime_recovered
    )
    return {
        "artifact_kind": "platform_hosted_managed_production_backup_cycle_report",
        "contract_ref": "platform.hosted-managed.production-backup-cycle.v1",
        "generated_at": generated_at,
        "ok": ok,
        "backup_id": backup_id,
        "backup_report_ref": f"backups/{backup_id}/backup-report.json",
        "restore_smoke_report_ref": f"backups/{backup_id}/restore-smoke-report.json",
        "phases": phases,
        "diagnostics": diagnostics,
        "summary": {
            "status": "backup_cycle_ready" if ok else "backup_cycle_failed",
            "backup_ready": backup_report is not None,
            "restore_smoke_passed": restore_report is not None,
            "runtime_recovered": runtime_recovered,
        },
        "privacy_boundary": {
            "public_safe": True,
            "includes_database_rows": False,
            "includes_workspace_artifacts": False,
            "includes_secret_values": False,
            "includes_local_paths": False,
        },
        "authority_boundary": {
            "may_enqueue_operations": False,
            "may_execute_managed_operations": False,
            "may_restore_production_database": False,
            "may_mutate_specs": False,
            "may_create_git_review": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-id")
    parser.add_argument("--service-url", default=DEFAULT_SERVICE_URL)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--probe-output", type=Path, default=DEFAULT_PROBE_OUTPUT)
    parser.add_argument(
        "--backup-id-output", type=Path, default=DEFAULT_BACKUP_ID_OUTPUT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    _require_supported_python(sys.version_info)
    backup_id = args.backup_id or datetime.now(timezone.utc).strftime(
        "production-%Y%m%dt%H%M%Sz"
    )
    try:
        report = run_backup_cycle(
            backup_id=backup_id,
            service_url=args.service_url,
            compose_file=args.compose_file.resolve(),
            env_file=args.env_file.resolve(),
            project_name=args.project_name,
            backup_root=args.backup_root.resolve(),
            probe_output=args.probe_output.resolve(),
            backup_id_output=args.backup_id_output.resolve(),
        )
    except ProductionBackupCycleError as exc:
        report = {
            "artifact_kind": "platform_hosted_managed_production_backup_cycle_report",
            "contract_ref": "platform.hosted-managed.production-backup-cycle.v1",
            "generated_at": _now_iso(),
            "ok": False,
            "backup_id": backup_id,
            "diagnostics": [str(exc)],
            "summary": {"status": "backup_cycle_blocked"},
            "privacy_boundary": {
                "public_safe": True,
                "includes_database_rows": False,
                "includes_workspace_artifacts": False,
                "includes_secret_values": False,
                "includes_local_paths": False,
            },
            "authority_boundary": {
                "may_enqueue_operations": False,
                "may_execute_managed_operations": False,
                "may_restore_production_database": False,
                "may_mutate_specs": False,
                "may_create_git_review": False,
            },
        }
    except OSError:
        report = {
            "artifact_kind": "platform_hosted_managed_production_backup_cycle_report",
            "contract_ref": "platform.hosted-managed.production-backup-cycle.v1",
            "generated_at": _now_iso(),
            "ok": False,
            "backup_id": backup_id,
            "diagnostics": ["production backup filesystem operation failed"],
            "summary": {"status": "backup_cycle_blocked"},
            "privacy_boundary": {
                "public_safe": True,
                "includes_database_rows": False,
                "includes_workspace_artifacts": False,
                "includes_secret_values": False,
                "includes_local_paths": False,
            },
            "authority_boundary": {
                "may_enqueue_operations": False,
                "may_execute_managed_operations": False,
                "may_restore_production_database": False,
                "may_mutate_specs": False,
                "may_create_git_review": False,
            },
        }
    _write_atomic(
        args.output.resolve(),
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        mode=0o444,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
