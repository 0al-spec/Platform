"""Semantic confirmation contract for hosted promotion-review execution."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

try:
    from scripts import hosted_managed_operations as managed_operations
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_operations as managed_operations


CONFIRMATION_KIND = "platform_hosted_promotion_review_confirmation"
CONFIRMATION_CONTRACT_REF = "platform.hosted-promotion-review-confirmation.v1"
CONFIRMATION_OPERATION_ID = "promotion_review_execute"
MAX_CONFIRMATION_LIFETIME_SECONDS = 15 * 60

PROMOTION_REQUEST_REF = "runs/graph_repository_promotion_request.json"
APPROVAL_DECISION_REF = "runs/candidate_approval_decision.json"
EXECUTION_PLAN_REF = "runs/graph_repository_execution_plan.json"

CONFIRMATION_FIELDS = frozenset(
    {
        "artifact_kind",
        "schema_version",
        "contract_ref",
        "confirmation_id",
        "workspace_id",
        "operation_id",
        "operator_ref",
        "status",
        "confirmed",
        "issued_at",
        "expires_at",
        "workspace_binding",
        "inputs",
        "predecessor_dry_run",
        "authority_boundary",
    }
)
BOUND_INPUT_REFS = {
    "promotion_request": PROMOTION_REQUEST_REF,
    "approval_decision": APPROVAL_DECISION_REF,
    "execution_plan": EXECUTION_PLAN_REF,
}
AUTHORITY_BOUNDARY = {
    "confirmation_is_execution_authority": False,
    "may_execute_platform": False,
    "may_mutate_canonical_specs": False,
    "may_write_ontology_packages": False,
    "may_accept_ontology_terms": False,
    "may_create_git_branch": False,
    "may_create_git_commit": False,
    "may_push_candidate_branch": False,
    "may_open_pull_request": False,
    "may_merge_pull_request": False,
    "may_publish_read_model": False,
}
PRODUCT_DRY_RUN_AUTHORITY_BOUNDARY = {
    "specspace_direct_git_write": False,
    "controlled_git_service_execution": False,
    "creates_candidate_worktree_or_branch": False,
    "creates_candidate_commit": False,
    "opens_pull_requests": False,
    "merges_pull_requests": False,
    "publishes_read_models": False,
    "canonical_spec_mutation_without_review": False,
    "ontology_package_write": False,
    "ontology_term_acceptance": False,
    "private_artifact_publication": False,
}
GIT_DRY_RUN_AUTHORITY_BOUNDARY = {
    "specspace_direct_git_write": False,
    "canonical_spec_mutation_without_review": False,
    "ontology_package_write": False,
    "auto_merge": False,
    "private_artifact_publication": False,
}
CONFIRMATION_ID_RE = re.compile(
    r"^confirmation://([a-z0-9][a-z0-9-]{1,62}[a-z0-9])/"
    r"promotion_review_execute/([0-9a-f]{32})$"
)
DRY_RUN_REQUEST_RE = re.compile(
    r"^managed-operation://([a-z0-9][a-z0-9-]{1,62}[a-z0-9])/"
    r"promotion_execute_dry_run/([0-9a-f]{24})$"
)


class PromotionReviewConfirmationError(ValueError):
    """Confirmation or predecessor evidence violates the bounded contract."""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _evidence_record_diagnostics(
    value: Any,
    *,
    expected_ref: str,
    subject: str,
) -> list[str]:
    record = _mapping(value)
    diagnostics: list[str] = []
    if set(record) != {"logical_ref", "sha256"}:
        diagnostics.append(f"{subject} does not match the evidence record contract")
    if record.get("logical_ref") != expected_ref:
        diagnostics.append(f"{subject} logical ref does not match current evidence")
    if not managed_operations.SHA256_RE.fullmatch(str(record.get("sha256") or "")):
        diagnostics.append(f"{subject} digest is invalid")
    return diagnostics


def _closed_authority_diagnostics(value: Any) -> list[str]:
    authority = _mapping(value)
    diagnostics: list[str] = []
    if set(authority) != set(AUTHORITY_BOUNDARY):
        diagnostics.append("confirmation authority boundary does not match the v1 contract")
    for key, expected in AUTHORITY_BOUNDARY.items():
        if authority.get(key) is not expected:
            diagnostics.append(f"confirmation authority field {key} must be false")
    for key, item in authority.items():
        if key.startswith("may_") and item is not False:
            diagnostics.append(f"confirmation authority field {key} expands authority")
    return diagnostics


def _dry_run_report_diagnostics(
    *,
    execution_report: dict[str, Any],
    git_service_report: dict[str, Any],
    workspace_id: str,
) -> list[str]:
    diagnostics: list[str] = []
    if (
        execution_report.get("artifact_kind")
        != "platform_product_candidate_promotion_execution_report"
        or execution_report.get("ok") is not True
        or execution_report.get("dry_run") is not True
        or execution_report.get("open_review_dry_run") is not True
    ):
        diagnostics.append("predecessor product report is not a successful promotion dry-run")
    if execution_report.get("workspace_id") != workspace_id:
        diagnostics.append("predecessor product report belongs to another workspace")
    summary = _mapping(execution_report.get("summary"))
    for field in (
        "worktree_prepared",
        "physical_worktree_created",
        "commit_created",
        "review_opened",
        "read_model_published",
    ):
        if summary.get(field) is not False:
            diagnostics.append(f"predecessor product report field {field} must be false")
    product_authority = _mapping(execution_report.get("authority_boundary"))
    if product_authority != PRODUCT_DRY_RUN_AUTHORITY_BOUNDARY:
        diagnostics.append(
            "predecessor product report authority boundary does not match "
            "the dry-run contract"
        )

    if (
        git_service_report.get("artifact_kind")
        != "platform_git_service_promotion_execution_report"
        or git_service_report.get("ok") is not True
        or git_service_report.get("dry_run") is not True
        or git_service_report.get("open_review_dry_run") is not True
    ):
        diagnostics.append("predecessor Git Service report is not a successful dry-run")
    copied = git_service_report.get("copied_materialized_files")
    if copied != []:
        diagnostics.append("predecessor Git Service report copied materialized files")
    operations = git_service_report.get("operations")
    if not isinstance(operations, list):
        diagnostics.append("predecessor Git Service operations must be an array")
        operations = []
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("status") == "succeeded":
            diagnostics.append("predecessor Git Service report records a write operation")
            break
    git_authority = _mapping(git_service_report.get("authority_boundary"))
    if git_authority != GIT_DRY_RUN_AUTHORITY_BOUNDARY:
        diagnostics.append(
            "predecessor Git Service authority boundary does not match "
            "the dry-run contract"
        )
    return diagnostics


def confirmation_diagnostics(
    payload: dict[str, Any],
    *,
    expected_workspace_id: str,
    expected_operator_ref: str,
    expected_confirmation_ref: str,
    expected_binding: Mapping[str, Any],
    expected_input_digests: Mapping[str, str],
    now_iso: str,
    resolve_ref: Callable[[str], Path],
) -> list[str]:
    """Validate one consumed confirmation and its current predecessor evidence."""

    diagnostics: list[str] = []
    if set(payload) != CONFIRMATION_FIELDS:
        diagnostics.append("promotion review confirmation does not match the v1 contract")
    if payload.get("artifact_kind") != CONFIRMATION_KIND:
        diagnostics.append("promotion review confirmation artifact kind is invalid")
    if payload.get("schema_version") != 1 or payload.get("contract_ref") != CONFIRMATION_CONTRACT_REF:
        diagnostics.append("promotion review confirmation contract version is unsupported")
    confirmation_match = CONFIRMATION_ID_RE.fullmatch(
        str(payload.get("confirmation_id") or "")
    )
    if confirmation_match is None or confirmation_match.group(1) != expected_workspace_id:
        diagnostics.append("promotion review confirmation identity is invalid")
    elif expected_confirmation_ref != (
        "specspace-state://confirmations/"
        f"{expected_workspace_id}/promotion_review_execute/"
        f"{confirmation_match.group(2)}.json"
    ):
        diagnostics.append(
            "promotion review confirmation state ref does not match its identity"
        )
    if payload.get("workspace_id") != expected_workspace_id:
        diagnostics.append("promotion review confirmation belongs to another workspace")
    if payload.get("operation_id") != CONFIRMATION_OPERATION_ID:
        diagnostics.append("promotion review confirmation targets another operation")
    if payload.get("operator_ref") != expected_operator_ref:
        diagnostics.append("promotion review confirmation operator identity changed")
    if payload.get("status") != "ready" or payload.get("confirmed") is not True:
        diagnostics.append("promotion review confirmation is not ready and confirmed")

    issued_at = _parse_time(payload.get("issued_at"))
    expires_at = _parse_time(payload.get("expires_at"))
    current_time = _parse_time(now_iso)
    if issued_at is None or expires_at is None or current_time is None:
        diagnostics.append("promotion review confirmation timestamps are invalid")
    elif (
        issued_at > current_time
        or expires_at <= current_time
        or (expires_at - issued_at).total_seconds() > MAX_CONFIRMATION_LIFETIME_SECONDS
    ):
        diagnostics.append("promotion review confirmation is expired or outside its bounded lifetime")

    binding = _mapping(payload.get("workspace_binding"))
    if set(binding) != {
        "binding_id",
        "binding_revision_sha256",
        "source_sha256",
    }:
        diagnostics.append("confirmation workspace binding does not match the v1 contract")
    for field in ("binding_id", "binding_revision_sha256", "source_sha256"):
        if binding.get(field) != expected_binding.get(field):
            diagnostics.append(f"confirmation workspace binding field {field} changed")

    inputs = _mapping(payload.get("inputs"))
    if set(inputs) != set(BOUND_INPUT_REFS):
        diagnostics.append("confirmation inputs do not match the v1 contract")
    for name, expected_ref in BOUND_INPUT_REFS.items():
        diagnostics.extend(
            _evidence_record_diagnostics(
                inputs.get(name),
                expected_ref=expected_ref,
                subject=f"confirmation inputs.{name}",
            )
        )
        record = _mapping(inputs.get(name))
        if record.get("sha256") != expected_input_digests.get(expected_ref):
            diagnostics.append(f"confirmation inputs.{name} digest changed")

    predecessor = _mapping(payload.get("predecessor_dry_run"))
    if set(predecessor) != {
        "request_id",
        "execution_report",
        "git_service_report",
    }:
        diagnostics.append("predecessor dry-run does not match the v1 contract")
    dry_run_match = DRY_RUN_REQUEST_RE.fullmatch(
        str(predecessor.get("request_id") or "")
    )
    request_fragment = dry_run_match.group(2) if dry_run_match else "invalid"
    if dry_run_match is None or dry_run_match.group(1) != expected_workspace_id:
        diagnostics.append("predecessor dry-run request identity is invalid")
    expected_execution_ref = (
        "runs/managed-promotion-dry-runs/"
        f"{request_fragment}.product_candidate_promotion_execution_report.json"
    )
    expected_git_ref = (
        "runs/managed-promotion-dry-runs/"
        f"{request_fragment}.git_service_promotion_execution_report.json"
    )
    execution_evidence = _mapping(predecessor.get("execution_report"))
    git_evidence = _mapping(predecessor.get("git_service_report"))
    diagnostics.extend(
        _evidence_record_diagnostics(
            execution_evidence,
            expected_ref=expected_execution_ref,
            subject="predecessor execution report",
        )
    )
    diagnostics.extend(
        _evidence_record_diagnostics(
            git_evidence,
            expected_ref=expected_git_ref,
            subject="predecessor Git Service report",
        )
    )

    reports: list[dict[str, Any]] = []
    for evidence, label in (
        (execution_evidence, "predecessor execution report"),
        (git_evidence, "predecessor Git Service report"),
    ):
        ref = evidence.get("logical_ref")
        if not isinstance(ref, str) or not managed_operations.safe_artifact_ref(ref):
            reports.append({})
            continue
        try:
            path = resolve_ref(ref)
            digest, _, media_type, _ = managed_operations.digest_path(path)
        except (OSError, ValueError):
            diagnostics.append(f"{label} is missing or unreadable")
            reports.append({})
            continue
        if digest != evidence.get("sha256") or media_type != "application/json":
            diagnostics.append(f"{label} digest or media type changed")
        report = _read_json(path)
        if report is None:
            diagnostics.append(f"{label} is not a JSON object")
            reports.append({})
        else:
            reports.append(report)
    if len(reports) == 2 and all(reports):
        diagnostics.extend(
            _dry_run_report_diagnostics(
                execution_report=reports[0],
                git_service_report=reports[1],
                workspace_id=expected_workspace_id,
            )
        )

    diagnostics.extend(_closed_authority_diagnostics(payload.get("authority_boundary")))
    return list(dict.fromkeys(diagnostics))


def validate_confirmation(**kwargs: Any) -> None:
    diagnostics = confirmation_diagnostics(**kwargs)
    if diagnostics:
        raise PromotionReviewConfirmationError("; ".join(diagnostics))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
