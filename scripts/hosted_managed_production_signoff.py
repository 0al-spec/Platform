"""Audit queue drain state and assemble final hosted production canary sign-off."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


ACTIVE_QUEUE_STATUSES = {"queued", "leased", "running"}
DEFAULT_MAX_EVIDENCE_AGE_SECONDS = 86400.0
EXPECTED_KINDS = {
    "preflight": "platform_hosted_managed_production_preflight_report",
    "probe_before_reboot": "platform_hosted_managed_production_probe_report",
    "probe_after_reboot": "platform_hosted_managed_production_probe_report",
    "canary": "platform_hosted_managed_operation_canary_report",
    "replay_canary": "platform_hosted_managed_operation_canary_report",
    "recovery": "platform_hosted_managed_operation_queue_recovery_report",
    "backup": "platform_hosted_managed_runtime_backup_report",
    "restore_smoke": "platform_hosted_managed_runtime_restore_smoke_report",
    "queue_audit": "platform_hosted_managed_production_queue_audit_report",
    "hosted_specspace_smoke": "platform_specspace_product_workspace_production_smoke_report",
    "rollback_specspace_smoke": "platform_specspace_product_workspace_production_smoke_report",
}


class ProductionSignoffError(RuntimeError):
    """Production evidence is missing, stale, or contradictory."""


def _database_url(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProductionSignoffError("database URL secret file is unavailable") from exc
    if not value.startswith(("postgresql://", "postgres://")):
        raise ProductionSignoffError("database URL must use PostgreSQL")
    return value


def queue_audit(database_url_file: Path) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise ProductionSignoffError("psycopg is required for queue audit") from exc
    database_url = _database_url(database_url_file)
    status_counts: dict[str, int] = {}
    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status, COUNT(*) FROM managed_operation_jobs "
                    "GROUP BY status ORDER BY status"
                )
                status_counts = {
                    str(row[0]): int(row[1]) for row in cursor.fetchall()
                }
                cursor.execute("SELECT COUNT(*) FROM managed_operation_locks")
                lock_count = int(cursor.fetchone()[0])
                cursor.execute("SELECT COUNT(*) FROM managed_operation_events")
                event_count = int(cursor.fetchone()[0])
    except Exception as exc:
        raise ProductionSignoffError("production queue audit failed") from exc
    active_count = sum(status_counts.get(status, 0) for status in ACTIVE_QUEUE_STATUSES)
    rollback_ready = active_count == 0 and lock_count == 0
    return {
        "artifact_kind": "platform_hosted_managed_production_queue_audit_report",
        "contract_ref": "platform.hosted-managed.production-queue-audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": rollback_ready,
        "summary": {
            "status": "drained" if rollback_ready else "active",
            "rollback_ready": rollback_ready,
            "active_job_count": active_count,
            "lock_count": lock_count,
            "event_count": event_count,
            "job_status_counts": status_counts,
        },
        "privacy_boundary": {
            "public_safe": True,
            "includes_request_payloads": False,
            "includes_workspace_ids": False,
            "includes_database_url": False,
        },
        "authority_boundary": {
            "may_requeue_operations": False,
            "may_execute_platform": False,
            "may_mutate_queue": False,
            "may_mutate_specs": False,
        },
    }


def _load_report(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionSignoffError(f"{label} report is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise ProductionSignoffError(f"{label} report must be an object")
    return payload


def _canary_identity(report: dict[str, Any]) -> tuple[Any, ...]:
    request = report.get("request")
    request = request if isinstance(request, dict) else {}
    outputs = report.get("authoritative_outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    return (
        request.get("request_id"),
        request.get("idempotency_key"),
        request.get("operation_id"),
        request.get("workspace_id"),
        tuple(outputs.get("observed_refs") or []),
        tuple(outputs.get("verified_refs") or []),
    )


def _write_authority_findings(value: Any, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            if isinstance(key, str) and key.startswith("may_") and nested is not False:
                findings.append(nested_path)
            findings.extend(_write_authority_findings(nested, path=nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            findings.extend(_write_authority_findings(nested, path=f"{path}[{index}]"))
    return findings


def _report_ready(label: str, report: dict[str, Any]) -> bool:
    summary = report.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    if label in {"canary", "replay_canary"}:
        return (
            summary.get("ok") is True
            and summary.get("status") == "hosted_managed_canary_passed"
        )
    if label == "recovery":
        return (
            summary.get("status") == "hosted_managed_operation_queue_recovered"
            and summary.get("strict") is True
            and summary.get("policy_safe") is True
            and summary.get("preflight_blocked") is False
        )
    if label in {"hosted_specspace_smoke", "rollback_specspace_smoke"}:
        return (
            summary.get("ok") is True
            and summary.get("failed_check_count") == 0
            and summary.get("diagnostic_count") == 0
        )
    return report.get("ok") is True


def _evidence_timestamps(
    reports: dict[str, dict[str, Any]],
    *,
    now: datetime,
    max_age_seconds: float,
) -> tuple[dict[str, datetime], list[str]]:
    timestamps: dict[str, datetime] = {}
    diagnostics: list[str] = []
    for label, report in reports.items():
        value = report.get("generated_at")
        if not isinstance(value, str):
            diagnostics.append(f"{label}_generated_at_missing")
            continue
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            diagnostics.append(f"{label}_generated_at_invalid")
            continue
        if timestamp.tzinfo is None:
            diagnostics.append(f"{label}_generated_at_not_utc")
            continue
        timestamp = timestamp.astimezone(timezone.utc)
        age = (now - timestamp).total_seconds()
        if age < -300:
            diagnostics.append(f"{label}_generated_at_in_future")
        elif age > max_age_seconds:
            diagnostics.append(f"{label}_evidence_stale")
        timestamps[label] = timestamp
    return timestamps, diagnostics


def _ordering_diagnostics(timestamps: dict[str, datetime]) -> list[str]:
    ordered_edges = (
        ("preflight", "probe_before_reboot"),
        ("probe_before_reboot", "backup"),
        ("backup", "restore_smoke"),
        ("restore_smoke", "canary"),
        ("canary", "recovery"),
        ("recovery", "probe_after_reboot"),
        ("probe_after_reboot", "replay_canary"),
        ("replay_canary", "queue_audit"),
        ("queue_audit", "rollback_specspace_smoke"),
        ("preflight", "hosted_specspace_smoke"),
        ("hosted_specspace_smoke", "rollback_specspace_smoke"),
    )
    diagnostics: list[str] = []
    for earlier, later in ordered_edges:
        if earlier in timestamps and later in timestamps and timestamps[earlier] > timestamps[later]:
            diagnostics.append(f"evidence_order_invalid_{earlier}_after_{later}")
    return diagnostics


def build_signoff(
    reports: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
    max_evidence_age_seconds: float = DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
) -> dict[str, Any]:
    diagnostics: list[str] = []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamps, timestamp_diagnostics = _evidence_timestamps(
        reports,
        now=current,
        max_age_seconds=max_evidence_age_seconds,
    )
    diagnostics.extend(timestamp_diagnostics)
    diagnostics.extend(_ordering_diagnostics(timestamps))
    if set(reports) != set(EXPECTED_KINDS):
        diagnostics.append("evidence_set_incomplete")
    for label, expected_kind in EXPECTED_KINDS.items():
        report = reports.get(label, {})
        if report.get("artifact_kind") != expected_kind:
            diagnostics.append(f"{label}_artifact_kind_invalid")
        if not _report_ready(label, report):
            diagnostics.append(f"{label}_not_ready")
        if _write_authority_findings(report):
            diagnostics.append(f"{label}_write_authority_expanded")

    preflight_summary = reports.get("preflight", {}).get("summary")
    preflight_summary = preflight_summary if isinstance(preflight_summary, dict) else {}
    if (
        preflight_summary.get("status") != "ready"
        or preflight_summary.get("enabled_operations") != ["review_status_execute"]
        or preflight_summary.get("dry_run_enabled") is not False
    ):
        diagnostics.append("preflight_scope_invalid")

    for label in ("probe_before_reboot", "probe_after_reboot"):
        report = reports.get(label, {})
        summary = report.get("summary")
        service = report.get("service")
        if not isinstance(summary, dict) or summary.get("status") != "healthy":
            diagnostics.append(f"{label}_not_healthy")
        if not isinstance(service, dict) or service.get("enabled_operation_ids") != [
            "review_status_execute"
        ]:
            diagnostics.append(f"{label}_allowlist_invalid")
    before_service = reports.get("probe_before_reboot", {}).get("service")
    before_service = before_service if isinstance(before_service, dict) else {}
    after_service = reports.get("probe_after_reboot", {}).get("service")
    after_service = after_service if isinstance(after_service, dict) else {}
    before_origin = before_service.get("origin")
    after_origin = after_service.get("origin")
    if not before_origin or before_origin != after_origin:
        diagnostics.append("reboot_probe_origin_mismatch")

    for label in ("canary", "replay_canary"):
        report = reports.get(label, {})
        summary = report.get("summary")
        queue = report.get("queue")
        outputs = report.get("authoritative_outputs")
        if not isinstance(summary, dict) or summary.get("profile") != "read_only":
            diagnostics.append(f"{label}_profile_invalid")
        if not isinstance(queue, dict) or queue.get("status") != "succeeded":
            diagnostics.append(f"{label}_queue_not_succeeded")
        if not isinstance(queue, dict) or queue.get("attempt") != 1:
            diagnostics.append(f"{label}_attempt_not_one")
        if not isinstance(outputs, dict) or outputs.get("receipt_pins_reports") is not True:
            diagnostics.append(f"{label}_outputs_not_pinned")
        if not isinstance(outputs, dict) or outputs.get("verified_refs") != outputs.get(
            "observed_refs"
        ):
            diagnostics.append(f"{label}_output_files_not_verified")
    if _canary_identity(reports.get("canary", {})) != _canary_identity(
        reports.get("replay_canary", {})
    ):
        diagnostics.append("canary_replay_identity_mismatch")

    recovery_summary = reports.get("recovery", {}).get("summary")
    recovery_summary = recovery_summary if isinstance(recovery_summary, dict) else {}
    if (
        recovery_summary.get("strict") is not True
        or recovery_summary.get("policy_safe") is not True
        or recovery_summary.get("preflight_blocked") is not False
    ):
        diagnostics.append("strict_recovery_not_safe")

    backup = reports.get("backup", {})
    restore = reports.get("restore_smoke", {})
    backup_summary = backup.get("summary")
    backup_summary = backup_summary if isinstance(backup_summary, dict) else {}
    restore_summary = restore.get("summary")
    restore_summary = restore_summary if isinstance(restore_summary, dict) else {}
    if (
        backup_summary.get("status") != "backup_ready"
        or backup_summary.get("database_backup_schema_version") != 1
        or backup_summary.get("state_database_backup_schema_version") != 1
        or restore_summary.get("status") != "restore_smoke_passed"
        or restore_summary.get("database_row_counts_verified") is not True
        or restore_summary.get("state_database_row_counts_verified") is not True
        or restore_summary.get("state_mirror_record_count_verified") is not True
        or restore_summary.get("artifact_inventory_verified") is not True
        or restore_summary.get("temporary_database_removed") is not True
        or restore_summary.get("temporary_state_mirror_removed") is not True
    ):
        diagnostics.append("backup_restore_contract_invalid")
    if not backup.get("backup_id") or backup.get("backup_id") != restore.get("backup_id"):
        diagnostics.append("backup_restore_identity_mismatch")
    queue_summary = reports.get("queue_audit", {}).get("summary")
    queue_summary = queue_summary if isinstance(queue_summary, dict) else {}
    if queue_summary.get("rollback_ready") is not True:
        diagnostics.append("queue_not_drained_for_rollback")

    hosted_smoke = reports.get("hosted_specspace_smoke", {}).get("summary")
    hosted_smoke = hosted_smoke if isinstance(hosted_smoke, dict) else {}
    if hosted_smoke.get("expected_managed_mode") != "hosted_managed_ready":
        diagnostics.append("hosted_specspace_mode_not_ready")
    rollback_smoke = reports.get("rollback_specspace_smoke", {}).get("summary")
    rollback_smoke = rollback_smoke if isinstance(rollback_smoke, dict) else {}
    if rollback_smoke.get("expected_managed_mode") != "read_only":
        diagnostics.append("rollback_specspace_mode_not_read_only")

    diagnostics = sorted(set(diagnostics))
    canary_request = reports.get("canary", {}).get("request")
    canary_request = canary_request if isinstance(canary_request, dict) else {}
    return {
        "artifact_kind": "platform_hosted_managed_production_canary_signoff_report",
        "contract_ref": "platform.hosted-managed.production-canary-signoff.v1",
        "generated_at": current.isoformat(),
        "ok": not diagnostics,
        "summary": {
            "status": "production_canary_signed_off"
            if not diagnostics
            else "production_canary_blocked",
            "workspace_id": canary_request.get("workspace_id"),
            "operation_id": canary_request.get("operation_id"),
            "read_only_canary_passed": not any(
                item.startswith(("canary_", "replay_canary_"))
                for item in diagnostics
            ),
            "reboot_verified": not any(
                item.startswith(("probe_after_reboot_", "reboot_probe_"))
                for item in diagnostics
            ),
            "backup_restore_verified": not any(
                item.startswith("backup_restore_") for item in diagnostics
            ),
            "rollback_verified": not any(
                item.startswith(("queue_not_", "rollback_specspace_"))
                for item in diagnostics
            ),
        },
        "diagnostics": diagnostics,
        "evidence": {
            label: {
                "artifact_kind": report.get("artifact_kind"),
                "ok": _report_ready(label, report),
            }
            for label, report in sorted(reports.items())
        },
        "privacy_boundary": {
            "public_safe": True,
            "includes_secret_values": False,
            "includes_local_paths": False,
            "includes_request_payloads": False,
        },
        "authority_boundary": {
            "may_enqueue_operations": False,
            "may_execute_platform": False,
            "may_mutate_specs": False,
            "may_create_git_review": False,
            "may_publish_read_model": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    audit = subcommands.add_parser("queue-audit")
    audit.add_argument("--database-url-file", required=True)
    audit.add_argument("--output")
    signoff = subcommands.add_parser("signoff")
    for label in EXPECTED_KINDS:
        signoff.add_argument(f"--{label.replace('_', '-')}", required=True)
    signoff.add_argument("--output")
    signoff.add_argument(
        "--max-evidence-age",
        type=float,
        default=DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "queue-audit":
            report = queue_audit(Path(args.database_url_file))
        else:
            reports = {
                label: _load_report(Path(getattr(args, label)), label=label)
                for label in EXPECTED_KINDS
            }
            report = build_signoff(
                reports,
                max_evidence_age_seconds=args.max_evidence_age,
            )
    except ProductionSignoffError as exc:
        report = {
            "artifact_kind": "platform_hosted_managed_production_canary_signoff_report",
            "ok": False,
            "summary": {"status": "production_canary_blocked"},
            "diagnostics": [str(exc)],
        }
    except Exception:
        report = {
            "artifact_kind": "platform_hosted_managed_production_canary_signoff_report",
            "ok": False,
            "summary": {"status": "production_canary_blocked"},
            "diagnostics": ["production sign-off evaluation failed"],
        }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
