"""Run exactly one request through a versioned bounded-worker policy."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable

try:
    from scripts import hosted_managed_operation_queue as queue_module
    from scripts.hosted_managed_production_profiles import (
        concrete_output_reports,
        profile_by_operation_id,
    )
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_operation_queue as queue_module
    from hosted_managed_production_profiles import (
        concrete_output_reports,
        profile_by_operation_id,
    )


POLICY_ARTIFACT_KIND = "platform_hosted_managed_worker_window_policy"
POLICY_CONTRACT_REF = "platform.hosted-managed.worker-window-policy.v1"
REPORT_ARTIFACT_KIND = "platform_hosted_managed_worker_window_report"
REPORT_CONTRACT_REF = "platform.hosted-managed.worker-window.v1"
READ_ONLY_OPERATION_ID = "review_status_execute"
READ_ONLY_OUTPUT_REF = "runs/product_candidate_promotion_review_status_report.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOW_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
REQUEST_ID_RE = re.compile(
    r"^managed-operation://[a-z0-9][a-z0-9-]{1,62}[a-z0-9]/"
    r"[a-z0-9_]+/[0-9a-f]{24}$"
)
POLICY_KEYS = {
    "artifact_kind",
    "schema_version",
    "contract_ref",
    "mode",
    "enabled_operation_ids",
    "max_duration_seconds",
    "max_processed_operations",
    "maximum_initial_attempt",
    "require_expected_request_id",
    "require_exclusive_queue",
    "require_strict_recovery_preflight",
    "require_authoritative_reports",
    "require_worker_stopped_after_window",
    "authority_boundary",
}
POLICY_AUTHORITY_KEYS = {
    "may_accept_arbitrary_commands",
    "may_expand_operation_allowlist",
    "may_execute_unpinned_requests",
    "may_keep_worker_running",
    "may_retry_irreversible_operations",
}


class WorkerWindowError(RuntimeError):
    """A bounded worker window cannot be opened safely."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_policy(path: Path) -> dict[str, Any]:
    if not path.is_absolute():
        raise WorkerWindowError("worker window policy path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise WorkerWindowError("worker window policy must be a regular file")
    try:
        if path.stat().st_size > 64 * 1024:
            raise WorkerWindowError("worker window policy is too large")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkerWindowError("worker window policy is unreadable") from exc
    if not isinstance(payload, dict):
        raise WorkerWindowError("worker window policy must be an object")
    diagnostics = policy_diagnostics(payload)
    if diagnostics:
        raise WorkerWindowError("worker window policy is invalid: " + ", ".join(diagnostics))
    return payload


def policy_diagnostics(policy: dict[str, Any]) -> list[str]:
    diagnostics: list[str] = []
    if set(policy) != POLICY_KEYS:
        diagnostics.append("policy_shape_invalid")
    if policy.get("artifact_kind") != POLICY_ARTIFACT_KIND:
        diagnostics.append("policy_artifact_kind_invalid")
    if policy.get("schema_version") != 1:
        diagnostics.append("policy_schema_version_invalid")
    if policy.get("contract_ref") != POLICY_CONTRACT_REF:
        diagnostics.append("policy_contract_ref_invalid")
    if policy.get("mode") != "bounded":
        diagnostics.append("policy_mode_invalid")
    enabled_operation_ids = policy.get("enabled_operation_ids")
    if (
        not isinstance(enabled_operation_ids, list)
        or len(enabled_operation_ids) != 1
        or not isinstance(enabled_operation_ids[0], str)
    ):
        diagnostics.append("policy_operation_scope_invalid")
    else:
        try:
            profile_by_operation_id(enabled_operation_ids[0])
        except ValueError:
            diagnostics.append("policy_operation_scope_invalid")
    duration = policy.get("max_duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 60 <= duration <= 1800:
        diagnostics.append("policy_duration_invalid")
    if policy.get("max_processed_operations") != 1:
        diagnostics.append("policy_operation_count_invalid")
    if policy.get("maximum_initial_attempt") != 0:
        diagnostics.append("policy_initial_attempt_invalid")
    for key in (
        "require_expected_request_id",
        "require_exclusive_queue",
        "require_strict_recovery_preflight",
        "require_authoritative_reports",
        "require_worker_stopped_after_window",
    ):
        if policy.get(key) is not True:
            diagnostics.append(f"{key}_not_enabled")
    boundary = policy.get("authority_boundary")
    if not isinstance(boundary, dict) or set(boundary) != POLICY_AUTHORITY_KEYS:
        diagnostics.append("policy_authority_boundary_invalid")
    elif any(boundary.get(key) is not False for key in POLICY_AUTHORITY_KEYS):
        diagnostics.append("policy_authority_expanded")
    return sorted(set(diagnostics))


def policy_sha256(policy: dict[str, Any]) -> str:
    canonical = json.dumps(
        policy,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def expected_output_reports(
    policy: dict[str, Any],
    *,
    request_id: str | None = None,
) -> tuple[str, ...]:
    diagnostics = policy_diagnostics(policy)
    if diagnostics:
        raise WorkerWindowError("worker window policy is invalid")
    operation_id = policy["enabled_operation_ids"][0]
    try:
        profile = profile_by_operation_id(operation_id)
        if request_id is not None:
            return concrete_output_reports(profile, request_id=request_id)
        return profile.expected_output_reports
    except ValueError as exc:
        raise WorkerWindowError("worker window policy operation is unsupported") from exc


def report_path(artifact_root: Path, window_id: str) -> Path:
    if not WINDOW_ID_RE.fullmatch(window_id):
        raise WorkerWindowError("worker window id is invalid")
    root = artifact_root.resolve()
    path = (root / "runs" / "managed-worker-windows" / f"{window_id}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkerWindowError("worker window report resolves outside artifact root") from exc
    return path


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    active_jobs = snapshot.get("active_jobs")
    active_jobs = active_jobs if isinstance(active_jobs, list) else []
    status_counts = snapshot.get("status_counts")
    status_counts = status_counts if isinstance(status_counts, dict) else {}
    return {
        "active_job_count": len(active_jobs),
        "active_lock_count": snapshot.get("active_lock_count"),
        "queued_count": status_counts.get("queued", 0),
        "leased_count": status_counts.get("leased", 0),
        "running_count": status_counts.get("running", 0),
    }


def _preflight_diagnostics(
    *,
    queue: queue_module.ManagedOperationQueue,
    policy: dict[str, Any],
    expected_request_id: str,
    allowed_operation_ids: frozenset[str],
) -> tuple[list[str], dict[str, Any], dict[str, Any] | None, bool]:
    diagnostics: list[str] = []
    if not REQUEST_ID_RE.fullmatch(expected_request_id):
        diagnostics.append("expected_request_id_invalid")
    expected_allowlist = frozenset(policy["enabled_operation_ids"])
    if allowed_operation_ids != expected_allowlist:
        diagnostics.append("deployment_allowlist_not_exact_window_scope")
    expired = queue.expired_requests(now_epoch=time.time())
    if expired:
        diagnostics.append("strict_recovery_required_before_window")
    snapshot = queue.operational_snapshot()
    active_jobs = snapshot.get("active_jobs")
    active_jobs = active_jobs if isinstance(active_jobs, list) else []
    expected_job = (
        queue.get(expected_request_id)
        if REQUEST_ID_RE.fullmatch(expected_request_id)
        else None
    )
    if snapshot.get("active_lock_count") != 0:
        diagnostics.append("active_queue_locks_present")
    reconcile_terminal = bool(
        expected_job
        and expected_job.get("status") == "succeeded"
        and expected_job.get("attempt") == 1
        and not active_jobs
        and snapshot.get("active_lock_count") == 0
    )
    if not reconcile_terminal:
        if len(active_jobs) != 1:
            diagnostics.append("queue_not_exclusive_to_expected_request")
        elif active_jobs[0].get("request_id") != expected_request_id:
            diagnostics.append("foreign_active_request_present")
    if expected_job is None:
        diagnostics.append("expected_request_missing")
    else:
        if expected_job.get("status") != "queued" and not reconcile_terminal:
            diagnostics.append("expected_request_not_queued")
        if expected_job.get("operation_id") not in expected_allowlist:
            diagnostics.append("expected_request_operation_not_allowed")
        if (
            expected_job.get("attempt") != policy["maximum_initial_attempt"]
            and not reconcile_terminal
        ):
            diagnostics.append("expected_request_attempt_not_fresh")
    return sorted(set(diagnostics)), snapshot, expected_job, reconcile_terminal


def run_window(
    *,
    queue: queue_module.ManagedOperationQueue,
    executor: queue_module.ManagedOperationExecutor,
    policy: dict[str, Any],
    window_id: str,
    expected_request_id: str,
    worker_id: str,
    allowed_operation_ids: frozenset[str],
    monotonic_clock: Callable[[], float] = time.monotonic,
    now_iso: Callable[[], str] = _now_iso,
) -> dict[str, Any]:
    policy_findings = policy_diagnostics(policy)
    if policy_findings:
        raise WorkerWindowError("worker window policy is invalid")
    if not WINDOW_ID_RE.fullmatch(window_id):
        raise WorkerWindowError("worker window id is invalid")
    if (
        not worker_id
        or len(worker_id) > 128
        or any(ord(item) < 33 for item in worker_id)
    ):
        raise WorkerWindowError("worker id is invalid")
    started_at = monotonic_clock()
    generated_at = now_iso()
    diagnostics, before_snapshot, expected_job, reconcile_terminal = (
        _preflight_diagnostics(
            queue=queue,
            policy=policy,
            expected_request_id=expected_request_id,
            allowed_operation_ids=allowed_operation_ids,
        )
    )
    receipt = (
        expected_job.get("receipt")
        if reconcile_terminal and isinstance(expected_job, dict)
        else None
    )
    receipt = receipt if isinstance(receipt, dict) else None
    operation_processed = False
    if not diagnostics and not reconcile_terminal:
        worker = queue_module.HostedManagedOperationWorker(
            queue,
            executor,
            worker_id=worker_id,
            lease_seconds=max(600, int(policy["max_duration_seconds"])),
            allowed_operation_ids=allowed_operation_ids,
            expected_request_id=expected_request_id,
            monotonic_clock=monotonic_clock,
        )
        receipt = worker.run_once()
        operation_processed = receipt is not None
        if receipt is None:
            diagnostics.append("expected_request_was_not_leased")
        elif receipt.get("status") != "succeeded":
            diagnostics.append(f"operation_{receipt.get('status') or 'unknown'}")
    after_snapshot = queue.operational_snapshot()
    elapsed_seconds = max(0.0, monotonic_clock() - started_at)
    if elapsed_seconds > policy["max_duration_seconds"]:
        diagnostics.append("worker_window_duration_exceeded")
    if after_snapshot.get("active_jobs"):
        diagnostics.append("queue_not_drained_after_window")
    if after_snapshot.get("active_lock_count") != 0:
        diagnostics.append("queue_locks_remain_after_window")
    diagnostics = sorted(set(diagnostics))
    receipt_outputs = receipt.get("output_reports") if isinstance(receipt, dict) else []
    receipt_outputs = receipt_outputs if isinstance(receipt_outputs, list) else []
    expected_outputs = expected_output_reports(
        policy,
        request_id=expected_request_id,
    )
    authoritative_reports_ready = bool(receipt_outputs) and all(
        isinstance(item, dict)
        and set(item) == {"logical_ref", "sha256"}
        and item.get("logical_ref") in expected_outputs
        and isinstance(item.get("sha256"), str)
        and SHA256_RE.fullmatch(item["sha256"])
        for item in receipt_outputs
    ) and {item["logical_ref"] for item in receipt_outputs} == set(expected_outputs)
    if not diagnostics and not authoritative_reports_ready:
        diagnostics.append("authoritative_reports_missing")
    status = "completed" if not diagnostics else "blocked"
    return {
        "artifact_kind": REPORT_ARTIFACT_KIND,
        "schema_version": 1,
        "contract_ref": REPORT_CONTRACT_REF,
        "generated_at": generated_at,
        "window_id": window_id,
        "request": {
            "request_id": expected_request_id,
            "operation_id": expected_job.get("operation_id") if expected_job else None,
            "workspace_id": expected_job.get("workspace_id") if expected_job else None,
            "initial_attempt": expected_job.get("attempt") if expected_job else None,
        },
        "policy": {
            "contract_ref": policy["contract_ref"],
            "sha256": policy_sha256(policy),
            "enabled_operation_ids": list(policy["enabled_operation_ids"]),
            "max_duration_seconds": policy["max_duration_seconds"],
            "max_processed_operations": policy["max_processed_operations"],
        },
        "execution": {
            "operation_processed": operation_processed,
            "reconciled_existing_completion": reconcile_terminal,
            "receipt_status": receipt.get("status") if receipt else None,
            "attempt": receipt.get("attempt") if receipt else None,
            "authoritative_output_reports": receipt_outputs,
            "elapsed_seconds": round(elapsed_seconds, 3),
        },
        "queue": {
            "before": _snapshot_summary(before_snapshot),
            "after": _snapshot_summary(after_snapshot),
        },
        "summary": {
            "status": f"bounded_worker_window_{status}",
            "one_shot_cycle_complete": True,
            "queue_drained": not after_snapshot.get("active_jobs")
            and after_snapshot.get("active_lock_count") == 0,
            "processed_operation_count": 1 if operation_processed else 0,
            "authoritative_reports_ready": authoritative_reports_ready,
            "diagnostic_count": len(diagnostics),
        },
        "diagnostics": diagnostics,
        "privacy_boundary": {
            "public_safe": True,
            "includes_request_payload": False,
            "includes_secret_values": False,
            "includes_local_paths": False,
        },
        "authority_boundary": {
            "executes_one_pinned_allowlisted_operation": operation_processed,
            "accepts_arbitrary_commands": False,
            "expands_operation_allowlist": False,
            "executes_unpinned_requests": False,
            "keeps_worker_running": False,
            "retries_irreversible_operations": False,
            "queue_status_is_lifecycle_evidence": False,
            "platform_output_reports_are_authoritative": True,
        },
    }


def load_existing_report(
    path: Path,
    *,
    window_id: str,
    expected_request_id: str,
    expected_policy_sha256: str,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkerWindowError("existing worker window report is invalid") from exc
    request = payload.get("request") if isinstance(payload, dict) else None
    request = request if isinstance(request, dict) else {}
    summary = payload.get("summary") if isinstance(payload, dict) else None
    summary = summary if isinstance(summary, dict) else {}
    privacy = payload.get("privacy_boundary") if isinstance(payload, dict) else None
    privacy = privacy if isinstance(privacy, dict) else {}
    authority = payload.get("authority_boundary") if isinstance(payload, dict) else None
    authority = authority if isinstance(authority, dict) else {}
    selected_policy = payload.get("policy") if isinstance(payload, dict) else None
    selected_policy = selected_policy if isinstance(selected_policy, dict) else {}
    if (
        not isinstance(payload, dict)
        or payload.get("artifact_kind") != REPORT_ARTIFACT_KIND
        or payload.get("contract_ref") != REPORT_CONTRACT_REF
        or payload.get("schema_version") != 1
        or payload.get("window_id") != window_id
        or request.get("request_id") != expected_request_id
        or selected_policy.get("sha256") != expected_policy_sha256
        or summary.get("status") not in {
            "bounded_worker_window_completed",
            "bounded_worker_window_blocked",
        }
        or summary.get("one_shot_cycle_complete") is not True
        or privacy
        != {
            "public_safe": True,
            "includes_request_payload": False,
            "includes_secret_values": False,
            "includes_local_paths": False,
        }
        or authority.get("accepts_arbitrary_commands") is not False
        or authority.get("expands_operation_allowlist") is not False
        or authority.get("executes_unpinned_requests") is not False
        or authority.get("keeps_worker_running") is not False
        or authority.get("retries_irreversible_operations") is not False
        or authority.get("queue_status_is_lifecycle_evidence") is not False
        or authority.get("platform_output_reports_are_authoritative") is not True
        or any(
            key.startswith("may_") and value is not False
            for key, value in authority.items()
        )
    ):
        raise WorkerWindowError("existing worker window report violates its contract")
    return payload


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{hashlib.sha256(os.urandom(16)).hexdigest()[:8]}.tmp"
    )
    data = json.dumps(report, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise WorkerWindowError("worker window report already exists") from exc
    finally:
        temporary.unlink(missing_ok=True)
