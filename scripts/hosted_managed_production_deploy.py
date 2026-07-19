"""Perform one fail-closed update of an existing hosted managed runtime."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

try:
    from scripts.hosted_managed_production_preflight import run_preflight
    from scripts.hosted_managed_production_probe import (
        ProductionProbeError,
        run_probe,
    )
    from scripts.render_hosted_managed_production_env import (
        ProductionEnvRenderError,
        _write_atomic,
        render_environment,
    )
    from scripts.hosted_managed_production_profiles import (
        REVIEW_STATUS_PROFILE_ID,
        deployment_profile_by_id,
        deployment_profile_by_operation_ids,
        deployment_profile_ids,
    )
    from scripts.validate_hosted_managed_image_lock import validate_image_lock
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    from hosted_managed_production_preflight import run_preflight
    from hosted_managed_production_probe import ProductionProbeError, run_probe
    from render_hosted_managed_production_env import (
        ProductionEnvRenderError,
        _write_atomic,
        render_environment,
    )
    from hosted_managed_production_profiles import (
        REVIEW_STATUS_PROFILE_ID,
        deployment_profile_by_id,
        deployment_profile_by_operation_ids,
        deployment_profile_ids,
    )
    from validate_hosted_managed_image_lock import validate_image_lock


CHECKOUT_HELPER = Path("/usr/local/sbin/0al-hosted-managed-checkout")
DEFAULT_COMPOSE_FILE = Path(
    "/srv/0al/platform/docker-compose.hosted-managed-production.example.yml"
)
DEFAULT_ENV_FILE = Path("/etc/0al/hosted-managed-production.env")
DEFAULT_IMAGE_LOCK = Path("/srv/0al/evidence/hosted-managed-image-lock.json")
DEFAULT_OUTPUT = Path("/srv/0al/evidence/hosted-managed-deployment.json")
DEFAULT_SERVICE_URL = "https://managed.specgraph.tech"
DEFAULT_PROJECT_NAME = "platform-managed-production"
COMMIT = re.compile(r"^[0-9a-f]{40}$")
ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
MINIMUM_HOST_PYTHON = (3, 12)
MAXIMUM_HOST_PYTHON = (3, 15)
RELEASE_IMAGE_KEYS = {
    "PLATFORM_MANAGED_OPERATION_IMAGE",
    "PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE",
}


class ProductionDeployError(RuntimeError):
    """The deployment cannot continue without violating its safety contract."""

    def __init__(self, message: str, *, status: str = "blocked") -> None:
        super().__init__(message)
        self.status = status


def _require_supported_python(version_info: tuple[int, ...] | Any) -> None:
    version = tuple(version_info[:2])
    if not MINIMUM_HOST_PYTHON <= version < MAXIMUM_HOST_PYTHON:
        raise ProductionDeployError(
            "host deployment requires Python 3.12, 3.13, or 3.14"
        )


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run(
    command: list[str],
    *,
    runner: Runner,
    label: str,
) -> str:
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ProductionDeployError(f"{label} failed")
    return completed.stdout


def _load_image_lock(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionDeployError("image lock is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise ProductionDeployError("image lock must be an object")
    diagnostics = validate_image_lock(payload)
    if diagnostics:
        raise ProductionDeployError(
            "image lock failed validation: " + ", ".join(diagnostics)
        )
    return payload


def _parse_environment(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in content.splitlines():
        if not line or line.startswith("#"):
            continue
        key, marker, value = line.partition("=")
        if not marker or not ENV_KEY.fullmatch(key) or key in values:
            raise ProductionDeployError("production environment is malformed")
        if not value or any(character in value for character in "\r\n\x00"):
            raise ProductionDeployError(
                "production environment contains an invalid value"
            )
        values[key] = value
    return values


def _required(values: dict[str, str], key: str) -> str:
    value = values.get(key)
    if not value:
        raise ProductionDeployError(f"production environment is missing {key}")
    return value


def _require_release_only_environment_change(
    *,
    current: dict[str, str],
    candidate: dict[str, str],
    operation_profile: str,
) -> None:
    if set(current) != set(candidate):
        raise ProductionDeployError(
            "production environment inventory drift requires a separate procedure"
        )
    changed = {key for key in current if current.get(key) != candidate.get(key)}
    allowed_changes = set(RELEASE_IMAGE_KEYS)
    if "PLATFORM_MANAGED_OPERATION_ALLOWLIST" in changed:
        try:
            current_profile = deployment_profile_by_operation_ids(
                tuple(current["PLATFORM_MANAGED_OPERATION_ALLOWLIST"].split(","))
            )
            candidate_profile = deployment_profile_by_id(operation_profile)
        except (KeyError, ValueError) as exc:
            raise ProductionDeployError(
                "operation profile transition is not approved"
            ) from exc
        if (
            current_profile.allowlist
            == candidate["PLATFORM_MANAGED_OPERATION_ALLOWLIST"]
            or candidate_profile.allowlist
            != candidate["PLATFORM_MANAGED_OPERATION_ALLOWLIST"]
        ):
            raise ProductionDeployError(
                "operation profile transition does not match the requested profile"
            )
        allowed_changes.add("PLATFORM_MANAGED_OPERATION_ALLOWLIST")
    if not changed.issubset(allowed_changes):
        raise ProductionDeployError(
            "non-image production configuration drift requires a separate procedure"
        )


def _checkout_commit(*, runner: Runner, helper: Path) -> str:
    output = _run(
        [str(helper), "status", "--repository", "platform"],
        runner=runner,
        label="Platform checkout validation",
    )
    fields = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    commit = fields.get("commit", "")
    if (
        fields.get("repository") != "platform"
        or fields.get("worktree") != "clean"
        or not COMMIT.fullmatch(commit)
    ):
        raise ProductionDeployError("Platform checkout status is invalid")
    return commit


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


def _queue_audit(
    *,
    env_file: Path,
    compose_file: Path,
    project_name: str,
    runner: Runner,
) -> dict[str, Any]:
    command = [
        *_compose_prefix(
            env_file=env_file,
            compose_file=compose_file,
            project_name=project_name,
        ),
        "--profile",
        "maintenance",
        "run",
        "--rm",
        "--no-deps",
        "managed-operation-maintenance",
        "python3",
        "scripts/hosted_managed_production_signoff.py",
        "queue-audit",
        "--database-url-file",
        "/run/secrets/managed_operation_database_url",
    ]
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode not in {0, 1}:
        raise ProductionDeployError("queue drain audit failed")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProductionDeployError("queue drain audit returned invalid JSON") from exc
    summary = report.get("summary") if isinstance(report, dict) else None
    if not isinstance(summary, dict) or not isinstance(
        summary.get("rollback_ready"), bool
    ):
        raise ProductionDeployError("queue drain audit contract is invalid")
    if (completed.returncode == 0) != (report.get("ok") is True):
        raise ProductionDeployError("queue drain audit exit status is inconsistent")
    return report


def _require_drained(report: dict[str, Any]) -> None:
    summary = report["summary"]
    if report.get("ok") is not True or summary.get("rollback_ready") is not True:
        raise ProductionDeployError("production queue is not drained")


def _wait_queue_drained(
    *,
    env_file: Path,
    compose_file: Path,
    project_name: str,
    runner: Runner,
    attempts: int,
    interval_seconds: float,
    sleeper: Callable[[float], None],
) -> tuple[dict[str, Any], int]:
    for attempt in range(1, attempts + 1):
        report = _queue_audit(
            env_file=env_file,
            compose_file=compose_file,
            project_name=project_name,
            runner=runner,
        )
        if report.get("ok") is True and report["summary"].get("rollback_ready") is True:
            return report, attempt
        if attempt < attempts:
            sleeper(interval_seconds)
    raise ProductionDeployError("production queue did not drain after ingress closed")


def _preflight(
    *, values: dict[str, str], service_url: str, operation_profile: str
) -> dict[str, Any]:
    secret_names = {
        "service_token": "PLATFORM_MANAGED_OPERATION_TOKEN_FILE",
        "database_password": "PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE",
        "database_url": "PLATFORM_MANAGED_OPERATION_DATABASE_URL_FILE",
        "specspace_state_token": "PLATFORM_SPECSPACE_STATE_TOKEN_FILE",
        "specspace_state_database_password": (
            "PLATFORM_SPECSPACE_STATE_DB_PASSWORD_FILE"
        ),
        "specspace_state_database_url": (
            "PLATFORM_SPECSPACE_STATE_DATABASE_URL_FILE"
        ),
        "github_token": "PLATFORM_MANAGED_OPERATION_GITHUB_TOKEN_FILE",
        "tls_certificate": "PLATFORM_MANAGED_OPERATION_TLS_CERTIFICATE_FILE",
        "tls_private_key": "PLATFORM_MANAGED_OPERATION_TLS_PRIVATE_KEY_FILE",
    }
    report = run_preflight(
        service_url=service_url,
        allowlist=_required(values, "PLATFORM_MANAGED_OPERATION_ALLOWLIST"),
        image_refs={
            "platform": _required(values, "PLATFORM_MANAGED_OPERATION_IMAGE"),
            "postgresql": _required(
                values, "PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE"
            ),
            "ingress": _required(values, "PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE"),
        },
        secret_paths={
            label: Path(_required(values, name)) for label, name in secret_names.items()
        },
        artifact_root=Path(
            _required(values, "PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT")
        ),
        state_dir=Path(_required(values, "PLATFORM_MANAGED_OPERATION_STATE_DIR")),
        operation_profile=operation_profile,
    )
    if report.get("ok") is not True:
        raise ProductionDeployError("production preflight blocked deployment")
    return report


def _probe_until_healthy(
    *,
    service_url: str,
    compose_file: Path,
    env_file: Path,
    project_name: str,
    runner: Runner,
    attempts: int,
    interval_seconds: float,
    sleeper: Callable[[float], None],
    operation_profile: str,
) -> tuple[dict[str, Any], int]:
    last_report: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        try:
            last_report = run_probe(
                service_url=service_url,
                compose_file=compose_file,
                env_file=env_file,
                project_name=project_name,
                runner=runner,
                operation_profile=operation_profile,
            )
        except ProductionProbeError:
            last_report = None
        if last_report is not None and last_report.get("ok") is True:
            return last_report, attempt
        if attempt < attempts:
            sleeper(interval_seconds)
    raise ProductionDeployError("updated runtime did not become healthy")


def deploy(
    *,
    image_lock_path: Path,
    env_file: Path,
    compose_file: Path,
    service_url: str,
    project_name: str,
    checkout_helper: Path = CHECKOUT_HELPER,
    runner: Runner = subprocess.run,
    health_attempts: int = 18,
    health_interval_seconds: float = 5.0,
    drain_attempts: int = 12,
    drain_interval_seconds: float = 5.0,
    sleeper: Callable[[float], None] = time.sleep,
    operation_profile: str = REVIEW_STATUS_PROFILE_ID,
) -> dict[str, Any]:
    try:
        selected_profile = deployment_profile_by_id(operation_profile)
    except ValueError as exc:
        raise ProductionDeployError("production operation profile is invalid") from exc
    if not all(
        path.is_absolute() for path in (image_lock_path, env_file, compose_file)
    ):
        raise ProductionDeployError("deployment paths must be absolute")
    if (
        health_attempts < 1
        or health_interval_seconds < 0
        or drain_attempts < 1
        or drain_interval_seconds < 0
    ):
        raise ProductionDeployError("deployment retry policy is invalid")
    image_lock = _load_image_lock(image_lock_path)
    source_commit = str(image_lock["source_commit"])
    if _checkout_commit(runner=runner, helper=checkout_helper) != source_commit:
        raise ProductionDeployError("image lock does not match Platform checkout HEAD")
    try:
        current_content = env_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProductionDeployError(
            "current production environment is unavailable"
        ) from exc
    current_values = _parse_environment(current_content)

    rendered, render_report = render_environment(
        image_lock=image_lock,
        artifact_root=_required(
            current_values, "PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT"
        ),
        state_dir=_required(current_values, "PLATFORM_MANAGED_OPERATION_STATE_DIR"),
        backup_root=_required(current_values, "PLATFORM_MANAGED_OPERATION_BACKUP_ROOT"),
        secret_root=str(
            Path(
                _required(current_values, "PLATFORM_MANAGED_OPERATION_TOKEN_FILE")
            ).parent
        ),
        ingress_bind_ip=_required(
            current_values, "PLATFORM_MANAGED_OPERATION_INGRESS_BIND_IP"
        ),
        ingress_port=int(
            _required(current_values, "PLATFORM_MANAGED_OPERATION_INGRESS_PORT")
        ),
        operation_profile=selected_profile.profile_id,
    )
    candidate_values = _parse_environment(rendered)
    if _required(
        candidate_values, "PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE"
    ) != _required(current_values, "PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE"):
        raise ProductionDeployError(
            "PostgreSQL image changes require the separate database migration procedure"
        )
    _require_release_only_environment_change(
        current=current_values,
        candidate=candidate_values,
        operation_profile=selected_profile.profile_id,
    )
    preflight_report = _preflight(
        values=candidate_values,
        service_url=service_url,
        operation_profile=selected_profile.profile_id,
    )
    try:
        current_profile = deployment_profile_by_operation_ids(
            tuple(
                _required(
                    current_values,
                    "PLATFORM_MANAGED_OPERATION_ALLOWLIST",
                ).split(",")
            )
        )
    except ValueError as exc:
        raise ProductionDeployError(
            "current production operation profile is unsupported"
        ) from exc

    env_file.parent.mkdir(parents=True, exist_ok=True)
    descriptor, candidate_name = tempfile.mkstemp(
        prefix=f".{env_file.name}.candidate.", dir=env_file.parent
    )
    os.close(descriptor)
    candidate_path = Path(candidate_name)
    candidate_path.write_text(rendered, encoding="utf-8")
    candidate_path.chmod(0o440)
    prefix = _compose_prefix(
        env_file=candidate_path,
        compose_file=compose_file,
        project_name=project_name,
    )
    env_installed = False
    runtime_quiesced = False
    rollback_ok = False
    try:
        _run([*prefix, "config", "--quiet"], runner=runner, label="Compose config")
        _run([*prefix, "pull"], runner=runner, label="pinned image pull")
        initial_queue_report = _queue_audit(
            env_file=candidate_path,
            compose_file=compose_file,
            project_name=project_name,
            runner=runner,
        )
        _require_drained(initial_queue_report)
        current_prefix = _compose_prefix(
            env_file=env_file,
            compose_file=compose_file,
            project_name=project_name,
        )
        # Treat an attempted stop as a mutation even if Compose reports failure;
        # some services may already have stopped before the command exits.
        runtime_quiesced = True
        _run(
            [
                *current_prefix,
                "stop",
                "managed-operation-ingress",
                "managed-operation-service",
            ],
            runner=runner,
            label="enqueue boundary quiesce",
        )
        queue_report, drain_attempt = _wait_queue_drained(
            env_file=candidate_path,
            compose_file=compose_file,
            project_name=project_name,
            runner=runner,
            attempts=drain_attempts,
            interval_seconds=drain_interval_seconds,
            sleeper=sleeper,
        )
        _run(
            [
                *current_prefix,
                "--profile",
                "continuous-worker",
                "stop",
                "managed-operation-worker",
            ],
            runner=runner,
            label="worker quiesce",
        )
        final_queue_report = _queue_audit(
            env_file=candidate_path,
            compose_file=compose_file,
            project_name=project_name,
            runner=runner,
        )
        _require_drained(final_queue_report)
        _write_atomic(env_file, rendered, overwrite=True)
        env_installed = True
        live_prefix = _compose_prefix(
            env_file=env_file,
            compose_file=compose_file,
            project_name=project_name,
        )
        _run(
            [*live_prefix, "up", "--detach", "--remove-orphans"],
            runner=runner,
            label="runtime recreation",
        )
        probe_report, probe_attempt = _probe_until_healthy(
            service_url=service_url,
            compose_file=compose_file,
            env_file=env_file,
            project_name=project_name,
            runner=runner,
            attempts=health_attempts,
            interval_seconds=health_interval_seconds,
            sleeper=sleeper,
            operation_profile=selected_profile.profile_id,
        )
    except (
        OSError,
        ProductionDeployError,
        ProductionEnvRenderError,
        ValueError,
    ) as exc:
        if not runtime_quiesced:
            raise ProductionDeployError(
                "deployment blocked before runtime mutation"
            ) from exc
        try:
            if env_installed:
                _write_atomic(env_file, current_content, overwrite=True)
            rollback_prefix = _compose_prefix(
                env_file=env_file,
                compose_file=compose_file,
                project_name=project_name,
            )
            _run(
                [*rollback_prefix, "up", "--detach", "--remove-orphans"],
                runner=runner,
                label="runtime rollback",
            )
            _probe_until_healthy(
                service_url=service_url,
                compose_file=compose_file,
                env_file=env_file,
                project_name=project_name,
                runner=runner,
                attempts=health_attempts,
                interval_seconds=health_interval_seconds,
                sleeper=sleeper,
                operation_profile=current_profile.profile_id,
            )
            rollback_ok = True
        except (OSError, ProductionDeployError):
            rollback_ok = False
        raise ProductionDeployError(
            "deployment failed and previous runtime was restored"
            if rollback_ok
            else "deployment failed; automatic rollback was not verified",
            status="rolled_back" if rollback_ok else "rollback_unverified",
        ) from exc
    finally:
        candidate_path.unlink(missing_ok=True)

    return {
        "artifact_kind": "platform_hosted_managed_production_deployment_report",
        "contract_ref": "platform.hosted-managed.production-deployment.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "summary": {
            "status": "production_runtime_updated",
            "source_commit": source_commit,
            "environment_sha256": render_report["summary"]["environment_sha256"],
            "operation_profile": selected_profile.profile_id,
            "enabled_operation_ids": list(selected_profile.enabled_operation_ids),
            "queue_drained": True,
            "drain_attempt": drain_attempt,
            "postgresql_image_unchanged": True,
            "healthy_service_count": probe_report["summary"]["healthy_service_count"],
            "health_attempt": probe_attempt,
        },
        "evidence": {
            "image_lock_validated": True,
            "checkout_commit_matched": True,
            "preflight_ready": preflight_report.get("ok") is True,
            "initial_queue_audit_status": initial_queue_report["summary"]["status"],
            "quiesced_queue_audit_status": queue_report["summary"]["status"],
            "final_queue_audit_status": final_queue_report["summary"]["status"],
            "compose_config_validated": True,
            "pinned_images_pulled": True,
            "runtime_probe_status": probe_report["summary"]["status"],
        },
        "effects": {
            "production_environment_replaced": True,
            "runtime_containers_recreated": True,
            "operation_profile_changed": (
                current_profile.profile_id != selected_profile.profile_id
            ),
            "enqueue_boundary_quiesced": True,
            "postgresql_volume_recreated": False,
            "managed_operation_enqueued": False,
        },
        "privacy_boundary": {
            "public_safe": True,
            "includes_secret_values": False,
            "includes_secret_paths": False,
            "includes_local_paths": False,
            "includes_command_output": False,
        },
        "authority_boundary": {
            "may_enqueue_operations": False,
            "may_expand_allowlist": False,
            "may_transfer_canary_artifacts": False,
            "may_create_git_review": False,
            "may_publish_read_model": False,
        },
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    _write_atomic(path, content, overwrite=True)
    path.chmod(0o444)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-lock", default=str(DEFAULT_IMAGE_LOCK))
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--compose-file", default=str(DEFAULT_COMPOSE_FILE))
    parser.add_argument("--service-url", default=DEFAULT_SERVICE_URL)
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--health-attempts", type=int, default=18)
    parser.add_argument("--health-interval", type=float, default=5.0)
    parser.add_argument("--drain-attempts", type=int, default=12)
    parser.add_argument("--drain-interval", type=float, default=5.0)
    parser.add_argument(
        "--operation-profile",
        choices=deployment_profile_ids(),
        default=REVIEW_STATUS_PROFILE_ID,
    )
    args = parser.parse_args(argv)
    python_error: ProductionDeployError | None = None
    try:
        _require_supported_python(sys.version_info)
    except ProductionDeployError as exc:
        python_error = exc
    if python_error is not None:
        report = {
            "artifact_kind": "platform_hosted_managed_production_deployment_report",
            "ok": False,
            "summary": {"status": "blocked"},
            "diagnostics": [str(python_error)],
        }
    elif os.geteuid() != 0:
        report = {
            "artifact_kind": "platform_hosted_managed_production_deployment_report",
            "ok": False,
            "summary": {"status": "blocked"},
            "diagnostics": ["production deployment must run as root"],
        }
    else:
        try:
            report = deploy(
                image_lock_path=Path(args.image_lock),
                env_file=Path(args.env_file),
                compose_file=Path(args.compose_file),
                service_url=args.service_url,
                project_name=args.project_name,
                health_attempts=args.health_attempts,
                health_interval_seconds=args.health_interval,
                drain_attempts=args.drain_attempts,
                drain_interval_seconds=args.drain_interval,
                operation_profile=args.operation_profile,
            )
        except (
            OSError,
            ProductionDeployError,
            ProductionEnvRenderError,
            ValueError,
        ) as exc:
            report = {
                "artifact_kind": "platform_hosted_managed_production_deployment_report",
                "contract_ref": "platform.hosted-managed.production-deployment.v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "ok": False,
                "summary": {
                    "status": exc.status
                    if isinstance(exc, ProductionDeployError)
                    else "blocked"
                },
                "diagnostics": [str(exc)],
                "privacy_boundary": {
                    "public_safe": True,
                    "includes_secret_values": False,
                    "includes_local_paths": False,
                },
                "authority_boundary": {
                    "may_enqueue_operations": False,
                    "may_expand_allowlist": False,
                    "may_transfer_canary_artifacts": False,
                    "may_create_git_review": False,
                    "may_publish_read_model": False,
                },
            }
    _write_report(Path(args.output), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
