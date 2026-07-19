"""Open one fail-closed bounded worker window on a production Compose host."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

try:
    from scripts import hosted_managed_worker_window as window_module
    from scripts.hosted_managed_production_profiles import (
        PROMOTION_DRY_RUN_PROFILE_ID,
        REVIEW_STATUS_PROFILE_ID,
        ProductionOperationProfile,
        deployment_profile_by_operation_ids,
        profile_by_id,
        profile_ids,
    )
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_worker_window as window_module
    from hosted_managed_production_profiles import (
        PROMOTION_DRY_RUN_PROFILE_ID,
        REVIEW_STATUS_PROFILE_ID,
        ProductionOperationProfile,
        deployment_profile_by_operation_ids,
        profile_by_id,
        profile_ids,
    )


DEFAULT_COMPOSE_FILE = Path(
    "/srv/0al/platform/docker-compose.hosted-managed-production.example.yml"
)
DEFAULT_ENV_FILE = Path("/etc/0al/hosted-managed-production.env")
DEFAULT_PROJECT_NAME = "platform-managed-production"
DEFAULT_EVIDENCE_ROOT = Path("/srv/0al/evidence")
WINDOW_SERVICE = "managed-operation-window-worker"
PROMOTION_DRY_RUN_WINDOW_SERVICE = (
    "managed-operation-promotion-dry-run-window-worker"
)
CONTINUOUS_SERVICE = "managed-operation-worker"
MAINTENANCE_SERVICE = "managed-operation-maintenance"
Runner = Callable[..., subprocess.CompletedProcess[str]]


class ProductionWorkerWindowError(RuntimeError):
    """The production worker window cannot be opened or closed safely."""


def _parse_environment(path: Path) -> dict[str, str]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ProductionWorkerWindowError(
            "production environment must be an absolute regular file"
        )
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProductionWorkerWindowError(
            "production environment is unreadable"
        ) from exc
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or key in values:
            raise ProductionWorkerWindowError(
                "production environment has an invalid entry"
            )
        values[key] = value
    return values


def _run(
    command: list[str],
    *,
    runner: Runner,
    environment: dict[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=timeout_seconds,
    )


def _compose_prefix(
    *,
    compose_file: Path,
    env_file: Path,
    project_name: str,
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


def _running_worker_services(
    prefix: list[str],
    *,
    runner: Runner,
    environment: dict[str, str],
) -> list[str]:
    completed = _run(
        [
            *prefix,
            "--profile",
            "continuous-worker",
            "--profile",
            "bounded-worker",
            "--profile",
            "promotion-dry-run-window",
            "ps",
            "--status",
            "running",
            "--services",
        ],
        runner=runner,
        environment=environment,
        timeout_seconds=30,
    )
    if completed.returncode != 0:
        raise ProductionWorkerWindowError("worker-state inspection failed")
    return sorted(
        item.strip()
        for item in completed.stdout.splitlines()
        if item.strip()
        in {
            WINDOW_SERVICE,
            PROMOTION_DRY_RUN_WINDOW_SERVICE,
            CONTINUOUS_SERVICE,
        }
    )


def _write_atomic(path: Path, report: dict[str, Any]) -> None:
    if not path.is_absolute() or path.exists():
        raise ProductionWorkerWindowError(
            "production window evidence path must be absolute and new"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        path.chmod(0o444)
    except FileExistsError as exc:
        raise ProductionWorkerWindowError(
            "production window evidence already exists"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _load_existing_output(
    path: Path,
    *,
    window_id: str,
    request_id: str,
    profile: ProductionOperationProfile,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionWorkerWindowError(
            "existing production window evidence is invalid"
        ) from exc
    request = payload.get("request") if isinstance(payload, dict) else None
    request = request if isinstance(request, dict) else {}
    summary = payload.get("summary") if isinstance(payload, dict) else None
    summary = summary if isinstance(summary, dict) else {}
    privacy = payload.get("privacy_boundary") if isinstance(payload, dict) else None
    privacy = privacy if isinstance(privacy, dict) else {}
    authority = payload.get("authority_boundary") if isinstance(payload, dict) else None
    authority = authority if isinstance(authority, dict) else {}
    recorded_profile = payload.get("operation_profile")
    legacy_review_profile = (
        recorded_profile is None
        and profile.profile_id == REVIEW_STATUS_PROFILE_ID
    )
    if (
        not isinstance(payload, dict)
        or payload.get("artifact_kind")
        != "platform_hosted_managed_production_worker_window_report"
        or payload.get("schema_version") != 1
        or payload.get("contract_ref")
        != "platform.hosted-managed.production-worker-window.v1"
        or payload.get("window_id") != window_id
        or request.get("request_id") != request_id
        or request.get("operation_id") != profile.operation_id
        or (
            not legacy_review_profile
            and recorded_profile != profile.profile_id
        )
        or summary.get("status")
        not in {
            "production_bounded_worker_window_completed",
            "production_bounded_worker_window_blocked",
        }
        or summary.get("worker_stopped") is not True
        or summary.get("continuous_worker_enabled") is not False
        or privacy
        != {
            "public_safe": True,
            "includes_secret_values": False,
            "includes_secret_paths": False,
            "includes_local_paths": False,
            "includes_command_output": False,
        }
        or authority.get("uses_fixed_compose_service") is not True
        or authority.get("accepts_arbitrary_commands") is not False
        or authority.get("expands_operation_allowlist") is not False
        or authority.get("keeps_worker_running") is not False
        or authority.get("queue_status_is_lifecycle_evidence") is not False
        or authority.get("platform_output_reports_are_authoritative") is not True
        or any(
            key.startswith("may_") and value is not False
            for key, value in authority.items()
        )
    ):
        raise ProductionWorkerWindowError(
            "existing production window evidence violates its contract"
        )
    return payload


def _read_json_report(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _dry_run_report_diagnostics(
    *,
    artifact_root: Path,
    workspace_id: str | None,
    core_report: dict[str, Any] | None,
    profile: ProductionOperationProfile,
) -> list[str]:
    if profile.profile_id != PROMOTION_DRY_RUN_PROFILE_ID:
        return []
    diagnostics: list[str] = []
    if (
        not isinstance(workspace_id, str)
        or not window_module.REQUEST_ID_RE.fullmatch(
            f"managed-operation://{workspace_id}/{profile.operation_id}/"
            + "0" * 24
        )
    ):
        return ["dry_run_workspace_identity_invalid"]
    execution = core_report.get("execution") if isinstance(core_report, dict) else None
    execution = execution if isinstance(execution, dict) else {}
    output_rows = execution.get("authoritative_output_reports")
    output_rows = output_rows if isinstance(output_rows, list) else []
    output_digests = {
        row.get("logical_ref"): row.get("sha256")
        for row in output_rows
        if isinstance(row, dict)
    }
    reports: dict[str, dict[str, Any]] = {}
    root = artifact_root.resolve()
    workspace_root = (root / "runs" / workspace_id).resolve()
    try:
        workspace_root.relative_to(root)
    except ValueError:
        return ["dry_run_workspace_root_invalid"]
    for logical_ref in profile.expected_output_reports:
        relative = logical_ref.removeprefix("runs/")
        path = (workspace_root / relative).resolve()
        try:
            path.relative_to(workspace_root)
        except ValueError:
            diagnostics.append("dry_run_report_path_invalid")
            continue
        payload = _read_json_report(path)
        if payload is None:
            diagnostics.append("dry_run_authoritative_report_missing")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if output_digests.get(logical_ref) != digest:
            diagnostics.append("dry_run_authoritative_report_digest_mismatch")
        reports[logical_ref] = payload

    product = reports.get("runs/product_candidate_promotion_execution_report.json", {})
    product_summary = product.get("summary")
    product_summary = product_summary if isinstance(product_summary, dict) else {}
    git_review = product.get("git_review")
    git_review = git_review if isinstance(git_review, dict) else {}
    product_authority = product.get("authority_boundary")
    product_authority = (
        product_authority if isinstance(product_authority, dict) else {}
    )
    product_authority_keys = {
        "specspace_direct_git_write",
        "controlled_git_service_execution",
        "creates_candidate_worktree_or_branch",
        "creates_candidate_commit",
        "opens_pull_requests",
        "merges_pull_requests",
        "publishes_read_models",
        "canonical_spec_mutation_without_review",
        "ontology_package_write",
        "ontology_term_acceptance",
        "private_artifact_publication",
    }
    if (
        product.get("artifact_kind")
        != "platform_product_candidate_promotion_execution_report"
        or product.get("ok") is not True
        or product.get("dry_run") is not True
        or product.get("open_review_dry_run") is not True
        or product_summary.get("status") != "dry_run"
        or product_summary.get("worktree_prepare_dry_run") is not True
        or product_summary.get("physical_worktree_created") is not False
        or product_summary.get("commit_created") is not False
        or product_summary.get("review_opened") is not False
        or product_summary.get("read_model_published") is not False
        or git_review.get("physical_worktree_created") is not False
        or git_review.get("commit_sha") is not None
        or git_review.get("review_url") is not None
        or git_review.get("review_opened") is not False
        or not product_authority_keys.issubset(product_authority)
        or any(value is not False for value in product_authority.values())
    ):
        diagnostics.append("product_promotion_report_not_strict_dry_run")

    git_service = reports.get("runs/git_service_promotion_execution_report.json", {})
    operations = git_service.get("operations")
    operations = operations if isinstance(operations, list) else []
    statuses = {
        row.get("name"): row.get("status")
        for row in operations
        if isinstance(row, dict)
    }
    git_authority = git_service.get("authority_boundary")
    git_authority = git_authority if isinstance(git_authority, dict) else {}
    git_authority_keys = {
        "specspace_direct_git_write",
        "canonical_spec_mutation_without_review",
        "ontology_package_write",
        "auto_merge",
        "private_artifact_publication",
    }
    if (
        git_service.get("artifact_kind")
        != "platform_git_service_promotion_execution_report"
        or git_service.get("ok") is not True
        or git_service.get("dry_run") is not True
        or git_service.get("open_review_dry_run") is not True
        or statuses
        != {
            "prepare_worktree": "dry_run",
            "commit_candidate": "skipped_dry_run",
            "open_review": "skipped_dry_run",
        }
        or git_service.get("copied_materialized_files") not in (None, [])
        or not git_authority_keys.issubset(git_authority)
        or any(value is not False for value in git_authority.values())
    ):
        diagnostics.append("git_service_report_not_strict_dry_run")

    candidate_workspace = (root / ".platform" / "candidates" / workspace_id).resolve()
    try:
        candidate_workspace.relative_to(root)
    except ValueError:
        diagnostics.append("dry_run_candidate_workspace_path_invalid")
    else:
        if candidate_workspace.exists():
            diagnostics.append("dry_run_physical_worktree_present")
    return sorted(set(diagnostics))


def execute_window(
    *,
    compose_file: Path,
    env_file: Path,
    project_name: str,
    window_id: str,
    request_id: str,
    output: Path,
    operation_profile: str = REVIEW_STATUS_PROFILE_ID,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    try:
        profile = profile_by_id(operation_profile)
    except ValueError as exc:
        raise ProductionWorkerWindowError(
            "production operation profile is invalid"
        ) from exc
    if (
        not compose_file.is_absolute()
        or compose_file.is_symlink()
        or not compose_file.is_file()
    ):
        raise ProductionWorkerWindowError(
            "production Compose file must be an absolute regular file"
        )
    if not window_module.WINDOW_ID_RE.fullmatch(window_id):
        raise ProductionWorkerWindowError("worker window id is invalid")
    if not window_module.REQUEST_ID_RE.fullmatch(request_id):
        raise ProductionWorkerWindowError("managed-operation request id is invalid")
    request_operation_id = request_id.removeprefix("managed-operation://").split("/")[1]
    if request_operation_id != profile.operation_id:
        raise ProductionWorkerWindowError(
            "managed-operation request does not match the production profile"
        )
    if not output.is_absolute() or output.is_symlink():
        raise ProductionWorkerWindowError(
            "production window evidence path must be an absolute non-symlink path"
        )
    existing_output = _load_existing_output(
        output,
        window_id=window_id,
        request_id=request_id,
        profile=profile,
    )
    if existing_output is not None:
        return existing_output
    values = _parse_environment(env_file)
    artifact_root_value = values.get("PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT", "")
    artifact_root = Path(artifact_root_value)
    if not artifact_root.is_absolute():
        raise ProductionWorkerWindowError("artifact root is not absolute")
    deployed_operation_ids = tuple(
        item.strip()
        for item in values.get("PLATFORM_MANAGED_OPERATION_ALLOWLIST", "").split(",")
        if item.strip()
    )
    try:
        deployment_profile = deployment_profile_by_operation_ids(
            deployed_operation_ids
        )
    except ValueError as exc:
        raise ProductionWorkerWindowError(
            "production allowlist is not an approved deployment profile"
        ) from exc
    if profile.operation_id not in deployment_profile.enabled_operation_ids:
        raise ProductionWorkerWindowError(
            "bounded worker operation is not enabled by the production allowlist"
        )
    policy_path = (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "hosted-managed"
        / profile.policy_filename
    ).resolve()
    policy = window_module.load_policy(policy_path)
    core_report_path = window_module.report_path(artifact_root, window_id)
    prefix = _compose_prefix(
        compose_file=compose_file,
        env_file=env_file,
        project_name=project_name,
    )
    environment = dict(os.environ)
    environment.update(values)
    environment.update(
        {
            "PLATFORM_MANAGED_WORKER_WINDOW_ID": window_id,
            "PLATFORM_MANAGED_WORKER_WINDOW_REQUEST_ID": request_id,
        }
    )
    container_name = f"platform-worker-window-{window_id}"
    diagnostics: list[str] = []
    before_workers = _running_worker_services(
        prefix,
        runner=runner,
        environment=environment,
    )
    run_returncode: int | None = None
    recovery_returncode: int | None = None
    recovery_timed_out = False
    timed_out = False
    if before_workers:
        diagnostics.append("worker_already_running_before_window")
    else:
        try:
            recovery = _run(
                [
                    *prefix,
                    "--profile",
                    "maintenance",
                    "run",
                    "--rm",
                    "--no-deps",
                    MAINTENANCE_SERVICE,
                    "python3",
                    "scripts/platform.py",
                    "managed-operation",
                    "recover",
                    "--queue-adapter",
                    "postgresql",
                    "--database-url-file",
                    "/run/secrets/managed_operation_database_url",
                    "--strict",
                ],
                runner=runner,
                environment=environment,
                timeout_seconds=120,
            )
            recovery_returncode = recovery.returncode
            if recovery.returncode != 0:
                diagnostics.append("strict_recovery_preflight_failed")
        except subprocess.TimeoutExpired:
            recovery_timed_out = True
            diagnostics.append("strict_recovery_preflight_timed_out")
    if not diagnostics:
        try:
            completed = _run(
                [
                    *prefix,
                    "--profile",
                    profile.compose_profile,
                    "run",
                    "--rm",
                    "--no-deps",
                    "--env",
                    f"PLATFORM_MANAGED_OPERATION_ALLOWLIST={profile.operation_id}",
                    "--name",
                    container_name,
                    profile.worker_service,
                ],
                runner=runner,
                environment=environment,
                timeout_seconds=int(policy["max_duration_seconds"]) + 60,
            )
            run_returncode = completed.returncode
            if completed.returncode != 0:
                diagnostics.append("bounded_worker_container_failed")
        except subprocess.TimeoutExpired:
            timed_out = True
            diagnostics.append("bounded_worker_container_timed_out")
            removal = _run(
                ["docker", "rm", "--force", container_name],
                runner=runner,
                environment=environment,
                timeout_seconds=30,
            )
            if removal.returncode != 0:
                diagnostics.append("bounded_worker_container_removal_failed")
    after_workers = _running_worker_services(
        prefix,
        runner=runner,
        environment=environment,
    )
    if after_workers:
        diagnostics.append("worker_still_running_after_window")
    try:
        core_report = window_module.load_existing_report(
            core_report_path,
            window_id=window_id,
            expected_request_id=request_id,
            expected_policy_sha256=window_module.policy_sha256(policy),
        )
    except window_module.WorkerWindowError:
        core_report = None
        diagnostics.append("bounded_worker_report_invalid")
    if core_report is None:
        diagnostics.append("bounded_worker_report_missing")
    core_summary = core_report.get("summary") if core_report else None
    core_summary = core_summary if isinstance(core_summary, dict) else {}
    if core_summary.get("status") != "bounded_worker_window_completed":
        diagnostics.append("bounded_worker_report_not_completed")
    core_policy = core_report.get("policy") if core_report else None
    core_policy = core_policy if isinstance(core_policy, dict) else {}
    if core_policy.get("sha256") != window_module.policy_sha256(policy):
        diagnostics.append("bounded_worker_policy_digest_mismatch")
    core_request = core_report.get("request") if core_report else None
    core_request = core_request if isinstance(core_request, dict) else {}
    if core_request.get("operation_id") != profile.operation_id:
        diagnostics.append("bounded_worker_operation_mismatch")
    diagnostics.extend(
        _dry_run_report_diagnostics(
            artifact_root=artifact_root,
            workspace_id=core_request.get("workspace_id"),
            core_report=core_report,
            profile=profile,
        )
    )
    diagnostics = sorted(set(diagnostics))
    core_digest = None
    if core_report is not None:
        core_digest = hashlib.sha256(core_report_path.read_bytes()).hexdigest()
    report = {
        "artifact_kind": "platform_hosted_managed_production_worker_window_report",
        "schema_version": 1,
        "contract_ref": "platform.hosted-managed.production-worker-window.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_id": window_id,
        "operation_profile": profile.profile_id,
        "request": {
            "request_id": request_id,
            "operation_id": profile.operation_id,
        },
        "worker_window": {
            "report_ref": (
                f"runs/managed-worker-windows/{window_id}.json"
                if core_report is not None
                else None
            ),
            "report_sha256": core_digest,
            "container_returncode": run_returncode,
            "strict_recovery_returncode": recovery_returncode,
            "strict_recovery_timed_out": recovery_timed_out,
            "timed_out": timed_out,
            "policy_sha256": window_module.policy_sha256(policy),
        },
        "summary": {
            "status": (
                "production_bounded_worker_window_completed"
                if not diagnostics
                else "production_bounded_worker_window_blocked"
            ),
            "worker_stopped": not after_workers,
            "continuous_worker_enabled": False,
            "dry_run_reports_verified": (
                profile.profile_id != PROMOTION_DRY_RUN_PROFILE_ID
                or not diagnostics
            ),
            "diagnostic_count": len(diagnostics),
        },
        "diagnostics": diagnostics,
        "privacy_boundary": {
            "public_safe": True,
            "includes_secret_values": False,
            "includes_secret_paths": False,
            "includes_local_paths": False,
            "includes_command_output": False,
        },
        "authority_boundary": {
            "uses_fixed_compose_service": True,
            "accepts_arbitrary_commands": False,
            "expands_operation_allowlist": False,
            "keeps_worker_running": False,
            "queue_status_is_lifecycle_evidence": False,
            "platform_output_reports_are_authoritative": True,
        },
    }
    _write_atomic(output, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", default=str(DEFAULT_COMPOSE_FILE))
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument(
        "--operation-profile",
        choices=profile_ids(),
        default=REVIEW_STATUS_PROFILE_ID,
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    output = (
        Path(args.output)
        if args.output
        else DEFAULT_EVIDENCE_ROOT / f"worker-window-{args.window_id}.json"
    )
    try:
        report = execute_window(
            compose_file=Path(args.compose_file).resolve(),
            env_file=Path(args.env_file).resolve(),
            project_name=args.project_name,
            window_id=args.window_id,
            request_id=args.request_id,
            output=output,
            operation_profile=args.operation_profile,
        )
    except ProductionWorkerWindowError as exc:
        print(json.dumps({"ok": False, "diagnostic": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return (
        0
        if report["summary"]["status"]
        == "production_bounded_worker_window_completed"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
