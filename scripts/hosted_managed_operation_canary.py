"""Safe canary client for the authenticated hosted managed-operation service."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

try:
    from scripts import hosted_managed_operations as contracts
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_operations as contracts


CANARY_CONTRACT_REF = "platform.hosted-managed-operation.canary.v1"
READ_ONLY_OPERATION_IDS = frozenset({"review_status_execute"})
DRY_RUN_OPERATION_IDS = frozenset({"promotion_execute_dry_run"})
TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "timed_out", "quarantined", "rejected"}
)


class HostedCanaryError(ValueError):
    """The canary request or hosted service response is invalid."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _service_url(base_url: str, path: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HostedCanaryError("hosted service URL must be an HTTP(S) URL")
    if parsed.scheme != "https" and parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise HostedCanaryError("non-loopback hosted service URL must use HTTPS")
    return base_url.rstrip("/") + path


def _request_json(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "0al-platform-hosted-canary/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
    except urllib.error.URLError as exc:
        raise HostedCanaryError(f"hosted service request failed: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HostedCanaryError("hosted service returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise HostedCanaryError("hosted service response must be a JSON object")
    return status, parsed


def _output_matches(ref: str, expected: str, workspace_id: str) -> bool:
    return contracts.artifact_ref_matches_template(ref, expected)


def _artifact_path(artifact_root: Path, workspace_id: str, logical_ref: str) -> Path:
    if not logical_ref.startswith("runs/"):
        raise HostedCanaryError("canary artifact verification only supports runs refs")
    path = (
        artifact_root / "runs" / workspace_id / logical_ref.removeprefix("runs/")
    ).resolve()
    workspace_root = (artifact_root / "runs" / workspace_id).resolve()
    if path != workspace_root and workspace_root not in path.parents:
        raise HostedCanaryError("canary output ref escapes the workspace run directory")
    return path


def _verify_output_files(
    *,
    artifact_root: Path,
    workspace_id: str,
    output_reports: list[Any],
) -> tuple[list[str], list[str]]:
    verified: list[str] = []
    diagnostics: list[str] = []
    for item in output_reports:
        if not isinstance(item, dict):
            diagnostics.append("authoritative output report is not an object")
            continue
        logical_ref = item.get("logical_ref")
        expected_sha256 = item.get("sha256")
        if not isinstance(logical_ref, str) or not contracts.safe_artifact_ref(
            logical_ref
        ):
            diagnostics.append("authoritative output report has an unsafe logical ref")
            continue
        try:
            path = _artifact_path(artifact_root, workspace_id, logical_ref)
            actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, HostedCanaryError):
            diagnostics.append(
                f"authoritative output report is not locally verifiable: {logical_ref}"
            )
            continue
        if actual_sha256 != expected_sha256:
            diagnostics.append(
                f"authoritative output report digest mismatch: {logical_ref}"
            )
            continue
        verified.append(logical_ref)
    return verified, diagnostics


def service_enqueue_payload(request: dict[str, Any]) -> dict[str, Any]:
    """Project a validated v1 request into the hosted service enqueue contract."""
    operation = request.get("operation")
    operation = operation if isinstance(operation, dict) else {}
    workspace = request.get("workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    binding = request.get("workspace_binding")
    binding = binding if isinstance(binding, dict) else {}
    inputs = request.get("inputs")
    if not isinstance(inputs, list):
        raise HostedCanaryError("canary request inputs must be an array")
    input_refs = [
        item.get("logical_ref")
        for item in inputs
        if isinstance(item, dict) and isinstance(item.get("logical_ref"), str)
    ]
    payload: dict[str, Any] = {
        "operation_id": operation.get("operation_id"),
        "workspace_id": workspace.get("workspace_id"),
        "workspace_binding_ref": binding.get("source_ref"),
        "input_refs": input_refs,
    }
    operator_ref = request.get("operator_ref")
    if operator_ref is not None:
        payload["operator_ref"] = operator_ref
    confirmation = request.get("confirmation")
    if isinstance(confirmation, dict) and confirmation.get("logical_ref") is not None:
        payload["confirmation_ref"] = confirmation.get("logical_ref")
    if any(value is None for value in payload.values()):
        raise HostedCanaryError("canary request is missing a logical enqueue field")
    return payload


def run_canary(
    *,
    request: dict[str, Any],
    service_url: str,
    token: str,
    timeout_seconds: float = 10.0,
    poll_interval_seconds: float = 1.0,
    max_wait_seconds: float = 120.0,
    allow_dry_run: bool = False,
    artifact_root: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    generated_at = _now_iso()
    diagnostics: list[str] = []
    checks: list[dict[str, Any]] = []

    def check(check_id: str, ok: bool, message: str) -> None:
        checks.append(
            {"id": check_id, "status": "passed" if ok else "failed", "message": message}
        )
        if not ok:
            diagnostics.append(message)

    operation = request.get("operation")
    operation = operation if isinstance(operation, dict) else {}
    operation_id = str(operation.get("operation_id") or "")
    workspace = request.get("workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    workspace_id = str(workspace.get("workspace_id") or "")
    request_id = str(request.get("request_id") or "")
    request_digest = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    request_diagnostics = contracts.request_diagnostics(request)
    check(
        "request_contract_valid",
        not request_diagnostics,
        "canary request must satisfy the hosted operation contract",
    )
    definition = contracts.operation_by_id(operation_id)
    operation_allowed = operation_id in READ_ONLY_OPERATION_IDS or (
        allow_dry_run and operation_id in DRY_RUN_OPERATION_IDS
    )
    check(
        "operation_canary_allowed",
        operation_allowed,
        "canary operation must be read-only unless --allow-dry-run explicitly enables a dry-run operation",
    )
    if definition is None:
        operation_allowed = False

    queue_status = "not_started"
    status_history: list[str] = []
    receipt: dict[str, Any] = {}
    events: list[Any] = []
    started = clock()

    try:
        health_status, health = _request_json(
            _service_url(service_url, "/v1/health"),
            timeout=timeout_seconds,
        )
        check(
            "service_health",
            health_status == 200 and health.get("ok") is True,
            "hosted service health must be ready",
        )
        if (
            not request_diagnostics
            and operation_allowed
            and health_status == 200
            and health.get("ok") is True
        ):
            enqueue_payload = service_enqueue_payload(request)
            enqueue_status, enqueue = _request_json(
                _service_url(service_url, "/v1/managed-operations"),
                method="POST",
                token=token,
                payload=enqueue_payload,
                timeout=timeout_seconds,
            )
            check(
                "enqueue_accepted",
                enqueue_status == 202 and enqueue.get("ok") is True,
                "hosted service must accept the canary request",
            )
            receipt = (
                enqueue.get("receipt")
                if isinstance(enqueue.get("receipt"), dict)
                else {}
            )
            queue_status = str(receipt.get("status") or "rejected")
            enqueue_summary = enqueue.get("summary")
            enqueue_summary = (
                enqueue_summary if isinstance(enqueue_summary, dict) else {}
            )
            remote_request_id = enqueue_summary.get("request_id") or receipt.get(
                "request_ref"
            )
            if isinstance(remote_request_id, str) and remote_request_id.startswith(
                "managed-operation://"
            ):
                request_id = remote_request_id
            else:
                diagnostics.append(
                    "hosted service enqueue response did not include a request id"
                )
            status_history.append(queue_status)
            while queue_status not in TERMINAL_STATUSES:
                if clock() - started >= max_wait_seconds:
                    queue_status = "timed_out"
                    diagnostics.append(
                        "hosted canary exceeded its bounded wait timeout"
                    )
                    break
                request_ref = urllib.parse.quote(request_id, safe="")
                status_url = _service_url(
                    service_url,
                    f"/v1/managed-operations/status?request_id={request_ref}&include_events=true",
                )
                status_code, status_report = _request_json(
                    status_url,
                    token=token,
                    timeout=timeout_seconds,
                )
                check(
                    "status_available",
                    status_code == 200 and status_report.get("ok") is True,
                    "hosted service status must be available",
                )
                job = status_report.get("job")
                job = job if isinstance(job, dict) else {}
                receipt = (
                    job.get("receipt")
                    if isinstance(job.get("receipt"), dict)
                    else receipt
                )
                queue_status = str(job.get("status") or "unknown")
                status_history.append(queue_status)
                raw_events = status_report.get("events")
                events = raw_events if isinstance(raw_events, list) else []
                if queue_status in TERMINAL_STATUSES:
                    break
                sleep(max(0.0, poll_interval_seconds))
            check(
                "queue_terminal",
                queue_status in TERMINAL_STATUSES,
                "hosted canary must reach a terminal queue state",
            )
        else:
            queue_status = "rejected"
    except HostedCanaryError as exc:
        diagnostics.append(str(exc))

    output_reports = receipt.get("output_reports") if isinstance(receipt, dict) else []
    output_reports = output_reports if isinstance(output_reports, list) else []
    expected_outputs = request.get("expected_output_reports")
    expected_outputs = expected_outputs if isinstance(expected_outputs, list) else []
    observed_refs = [
        item.get("logical_ref")
        for item in output_reports
        if isinstance(item, dict) and isinstance(item.get("logical_ref"), str)
    ]
    outputs_match = all(
        any(_output_matches(ref, expected, workspace_id) for ref in observed_refs)
        for expected in expected_outputs
    ) and len(observed_refs) == len(expected_outputs)
    check(
        "authoritative_output_refs",
        queue_status == "succeeded" and outputs_match,
        "successful canary must pin every registered authoritative output report",
    )
    verified_refs: list[str] = []
    if artifact_root is not None and queue_status == "succeeded":
        verified_refs, file_diagnostics = _verify_output_files(
            artifact_root=artifact_root,
            workspace_id=workspace_id,
            output_reports=output_reports,
        )
        diagnostics.extend(file_diagnostics)
        check(
            "authoritative_output_files",
            not file_diagnostics and len(verified_refs) == len(output_reports),
            "authoritative output report files must match their receipt digests",
        )
    elif artifact_root is None:
        checks.append(
            {
                "id": "authoritative_output_files",
                "status": "not_run",
                "message": "local artifact verification was not requested",
            }
        )

    ok = not diagnostics and queue_status == "succeeded"
    return {
        "artifact_kind": "platform_hosted_managed_operation_canary_report",
        "schema_version": 1,
        "contract_ref": CANARY_CONTRACT_REF,
        "generated_at": generated_at,
        "service": {
            "origin": f"{urllib.parse.urlsplit(service_url).scheme}://{urllib.parse.urlsplit(service_url).netloc}",
        },
        "request": {
            "request_id": request_id,
            "request_sha256": request_digest,
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "idempotency_key": request.get("idempotency_key"),
        },
        "queue": {
            "status": queue_status,
            "status_history": status_history,
            "event_count": len(events),
            "attempt": receipt.get("attempt"),
        },
        "authoritative_outputs": {
            "expected_refs": expected_outputs,
            "observed_refs": observed_refs,
            "verified_refs": verified_refs,
            "receipt_pins_reports": queue_status == "succeeded" and outputs_match,
        },
        "checks": checks,
        "diagnostics": diagnostics,
        "summary": {
            "ok": ok,
            "status": "hosted_managed_canary_passed"
            if ok
            else "hosted_managed_canary_blocked",
            "profile": "dry_run"
            if operation_id in DRY_RUN_OPERATION_IDS
            else "read_only",
            "authoritative_output_report_count": len(observed_refs),
            "local_output_files_verified": artifact_root is not None
            and not diagnostics
            and queue_status == "succeeded",
        },
        "authority_boundary": {
            "accepts_arbitrary_commands": False,
            "allows_irreversible_operations": False,
            "browser_execution_authority": False,
            "queue_status_is_lifecycle_evidence": False,
            "platform_output_reports_are_authoritative": True,
            "is_promotion_gate": False,
        },
        "privacy_boundary": {
            "raw_idea_included": False,
            "operator_notes_included": False,
            "local_paths_included": False,
            "secrets_included": False,
        },
    }
