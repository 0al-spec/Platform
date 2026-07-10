"""Contracts for queue-backed Platform managed operations.

The queue transport is intentionally absent from this module.  It defines the
immutable request and receipt artifacts shared by local and hosted adapters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable


REQUEST_KIND = "platform_hosted_managed_operation_request"
REQUEST_CONTRACT_REF = "platform.hosted-managed-operation.request.v1"
RECEIPT_KIND = "platform_hosted_managed_operation_receipt"
RECEIPT_CONTRACT_REF = "platform.hosted-managed-operation.receipt.v1"
REGISTRY_CONTRACT_REF = "platform.managed-operation.registry.v1"

REQUEST_STATUSES = ("ready", "blocked")
RECEIPT_STATUSES = (
    "rejected",
    "queued",
    "leased",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "quarantined",
)
SIDE_EFFECT_CLASSES = (
    "workspace_initialization",
    "review_only_materialization",
    "public_bundle_publication",
    "git_dry_run",
    "git_review",
    "git_read_only",
    "read_model_publication",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WORKSPACE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
ARTIFACT_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ManagedOperationDefinition:
    operation_id: str
    platform_command: tuple[str, ...]
    input_refs: tuple[str, ...]
    output_reports: tuple[str, ...]
    idempotency_source: str
    side_effect_class: str
    lock_scopes: tuple[str, ...]
    timeout_seconds: int
    replay_policy: str
    conditional_input_refs: tuple[str, ...] = ()
    dry_run_only: bool = False
    irreversible: bool = False
    requires_explicit_confirmation: bool = False


_COMMON_LOCKS = ("workspace:{workspace_id}", "operation:{operation_id}:{workspace_id}")


MANAGED_OPERATIONS: tuple[ManagedOperationDefinition, ...] = (
    ManagedOperationDefinition(
        operation_id="workspace_initialization_execute",
        platform_command=("workspace", "execute-requested-initialization"),
        input_refs=("runs/product_workspace_initialization_execution_request.json",),
        output_reports=("runs/platform_product_workspace_initialization_execution_report.json",),
        idempotency_source="execution_request.summary.idempotency_key",
        side_effect_class="workspace_initialization",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=120,
        replay_policy="matching_request_only",
    ),
    ManagedOperationDefinition(
        operation_id="real_idea_intake_execute",
        platform_command=("product-real-idea-intake", "execute-requested"),
        input_refs=(
            "specspace-state://real_idea_intake_execution_requests.json",
            "specspace-state://real_idea_entry_requests.json",
            "runs/platform_product_workspace_initialization_execution_report.json",
        ),
        output_reports=("runs/platform_real_idea_entry_intake_execution_report.json",),
        idempotency_source="execution_request.request_id",
        side_effect_class="review_only_materialization",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=120,
        replay_policy="consume_on_attempt_new_request_required",
    ),
    ManagedOperationDefinition(
        operation_id="real_idea_answer_continuation_execute",
        platform_command=("product-real-idea-continuation", "execute-requested"),
        input_refs=(
            "specspace-state://real_idea_answer_continuation_execution_requests.json",
            "specspace-state://idea_to_spec_intake_clarification_answers.json",
            "runs/platform_product_workspace_initialization_execution_report.json",
            "runs/platform_real_idea_entry_intake_execution_report.json",
        ),
        conditional_input_refs=("specspace-state://idea_to_spec_intake_clarification_answers.json",),
        output_reports=("runs/platform_real_idea_answer_continuation_execution_report.json",),
        idempotency_source="execution_request.request_id",
        side_effect_class="review_only_materialization",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=120,
        replay_policy="consume_on_attempt_new_request_required",
    ),
    ManagedOperationDefinition(
        operation_id="repair_rerun_request_gate_execute",
        platform_command=("product-repair-rerun", "request-gate"),
        input_refs=(
            "specspace-state://idea_to_spec_repair_rerun_requests.json",
            "runs/specspace_repair_draft_import_preview.json",
            "runs/idea_to_spec_repair_session.json",
        ),
        output_reports=(
            "runs/platform_product_repair_rerun_request_gate_execution_report.json",
            "runs/specspace_repair_rerun_request_gate.json",
        ),
        idempotency_source="rerun_request.request_id",
        side_effect_class="review_only_materialization",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=120,
        replay_policy="consume_on_attempt_new_request_required",
    ),
    ManagedOperationDefinition(
        operation_id="repair_rerun_execute",
        platform_command=("product-repair-rerun", "plan", "execute"),
        input_refs=(
            "specspace-state://idea_to_spec_repair_rerun_requests.json",
            "runs/specspace_repair_draft_import_preview.json",
            "runs/idea_to_spec_repair_session.json",
            "runs/specspace_repair_rerun_request_gate.json",
        ),
        output_reports=(
            "runs/managed_repair_rerun_plans/<request-id>.platform_product_repair_rerun_execution_plan.json",
            "runs/platform_product_repair_rerun_execution_report.json",
        ),
        idempotency_source="rerun_request.request_id",
        side_effect_class="review_only_materialization",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=240,
        replay_policy="consume_on_attempt_new_request_required",
    ),
    ManagedOperationDefinition(
        operation_id="repair_rerun_publish",
        platform_command=("product-repair-rerun", "publish"),
        input_refs=("runs/platform_product_repair_rerun_execution_report.json",),
        output_reports=("runs/platform_product_repair_rerun_publication_report.json",),
        idempotency_source="execution_report.summary.execution_id",
        side_effect_class="public_bundle_publication",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=120,
        replay_policy="matching_execution_report_only",
    ),
    ManagedOperationDefinition(
        operation_id="candidate_approval_execute",
        platform_command=("product-candidate-approval", "approve"),
        input_refs=(
            "specspace-state://idea_to_spec_candidate_approval_intents.json",
            "runs/repaired_active_idea_to_spec_candidate.json",
            "runs/repaired_idea_to_spec_repair_session.json",
            "runs/repaired_idea_to_spec_promotion_gate.json",
            "runs/platform_product_repair_rerun_execution_report.json",
            "runs/platform_product_repair_rerun_publication_report.json",
        ),
        output_reports=(
            "runs/platform_candidate_approval_intent_gate_report.json",
            "runs/platform_candidate_approval_execution_report.json",
            "runs/candidate_approval_decision.json",
        ),
        idempotency_source="approval_intent.intent_id",
        side_effect_class="review_only_materialization",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=120,
        replay_policy="consume_on_attempt_new_request_required",
    ),
    ManagedOperationDefinition(
        operation_id="promotion_request_execute",
        platform_command=("product-candidate-promotion", "request"),
        input_refs=("runs/graph_repository_execution_plan.json", "runs/candidate_approval_decision.json"),
        output_reports=("runs/graph_repository_promotion_request.json",),
        idempotency_source="candidate_approval_decision.decision_id",
        side_effect_class="review_only_materialization",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=120,
        replay_policy="matching_approval_decision_only",
    ),
    ManagedOperationDefinition(
        operation_id="promotion_execute_dry_run",
        platform_command=("product-candidate-promotion", "execute", "--dry-run", "--open-review-dry-run"),
        input_refs=("runs/graph_repository_promotion_request.json", "runs/candidate_approval_decision.json"),
        output_reports=(
            "runs/product_candidate_promotion_execution_report.json",
            "runs/git_service_promotion_execution_report.json",
        ),
        idempotency_source="promotion_request.request_id",
        side_effect_class="git_dry_run",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=120,
        replay_policy="same_request_dry_run_only",
        dry_run_only=True,
    ),
    ManagedOperationDefinition(
        operation_id="promotion_review_execute",
        platform_command=("product-candidate-promotion", "execute"),
        input_refs=(
            "runs/graph_repository_promotion_request.json",
            "runs/candidate_approval_decision.json",
            "runs/product_candidate_promotion_execution_report.json",
        ),
        output_reports=(
            "runs/product_candidate_promotion_execution_report.json",
            "runs/git_service_promotion_execution_report.json",
        ),
        idempotency_source="promotion_request.request_id",
        side_effect_class="git_review",
        lock_scopes=_COMMON_LOCKS + ("git-review:{workspace_id}",),
        timeout_seconds=240,
        replay_policy="reconcile_before_retry",
        irreversible=True,
        requires_explicit_confirmation=True,
    ),
    ManagedOperationDefinition(
        operation_id="review_status_execute",
        platform_command=("product-candidate-promotion", "review-status"),
        input_refs=("runs/product_candidate_promotion_execution_report.json",),
        output_reports=("runs/product_candidate_promotion_review_status_report.json",),
        idempotency_source="review.pr_number",
        side_effect_class="git_read_only",
        lock_scopes=_COMMON_LOCKS,
        timeout_seconds=120,
        replay_policy="read_only_replay_allowed",
    ),
    ManagedOperationDefinition(
        operation_id="read_model_publication_execute",
        platform_command=("product-candidate-promotion", "publish-read-model"),
        input_refs=(
            "runs/product_candidate_promotion_review_status_report.json",
            "dist/specgraph-public/workspaces/<workspace-id>",
        ),
        output_reports=("runs/product_candidate_promotion_read_model_publication_report.json",),
        idempotency_source="review.merge_commit_sha",
        side_effect_class="read_model_publication",
        lock_scopes=_COMMON_LOCKS + ("read-model:{workspace_id}",),
        timeout_seconds=240,
        replay_policy="same_merge_commit_only",
        irreversible=True,
    ),
)


def operation_by_id(operation_id: str) -> ManagedOperationDefinition | None:
    return next((item for item in MANAGED_OPERATIONS if item.operation_id == operation_id), None)


def operation_payload(definition: ManagedOperationDefinition) -> dict[str, Any]:
    payload = asdict(definition)
    for key in (
        "platform_command",
        "input_refs",
        "output_reports",
        "lock_scopes",
        "conditional_input_refs",
    ):
        payload[key] = list(payload[key])
    return payload


def registry_payload() -> dict[str, Any]:
    return {
        "artifact_kind": "platform_managed_operation_registry",
        "schema_version": 1,
        "contract_ref": REGISTRY_CONTRACT_REF,
        "operation_count": len(MANAGED_OPERATIONS),
        "operations": [operation_payload(item) for item in MANAGED_OPERATIONS],
        "delivery_semantics": "at_least_once",
        "completion_evidence": "validated_platform_output_reports",
        "authority_boundary": request_authority_boundary(),
    }


def request_authority_boundary() -> dict[str, bool]:
    return {
        "request_only": True,
        "may_execute_platform": False,
        "may_execute_specgraph": False,
        "may_mutate_specspace_state": False,
        "may_mutate_canonical_specs": False,
        "may_write_ontology_packages": False,
        "may_accept_ontology_terms": False,
        "may_create_git_branch": False,
        "may_create_git_commit": False,
        "may_open_pull_request": False,
        "may_merge_pull_request": False,
        "may_publish_read_model": False,
    }


def safe_artifact_ref(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    if value.startswith("specspace-state://"):
        suffix = value.removeprefix("specspace-state://")
        return bool(suffix) and ".." not in PurePosixPath(suffix).parts
    if "://" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and not value.startswith("~")


def safe_operator_ref(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 256:
        return False
    if any(ord(character) < 32 for character in value):
        return False
    if value.startswith("operator://"):
        suffix = value.removeprefix("operator://")
        return bool(suffix) and "/" not in suffix and "\\" not in suffix
    return safe_artifact_ref(value)


def digest_path(path: Path) -> tuple[str, int, str, str | None]:
    if path.is_file():
        data = path.read_bytes()
        artifact_kind: str | None = None
        media_type = "application/octet-stream"
        if path.suffix == ".json":
            media_type = "application/json"
            try:
                payload = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("artifact_kind"), str):
                candidate_kind = payload["artifact_kind"]
                artifact_kind = (
                    candidate_kind if ARTIFACT_KIND_RE.fullmatch(candidate_kind) else None
                )
        return hashlib.sha256(data).hexdigest(), len(data), media_type, artifact_kind
    if path.is_dir():
        digest = hashlib.sha256()
        size = 0
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            relative = child.relative_to(path).as_posix().encode("utf-8")
            data = child.read_bytes()
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
            size += len(data)
        return digest.hexdigest(), size, "application/vnd.platform.directory", None
    raise ValueError(f"input path is not a file or directory: {path}")


def build_input_records(
    definition: ManagedOperationDefinition,
    inputs: dict[str, Path],
) -> tuple[list[dict[str, Any]], list[str]]:
    diagnostics: list[str] = []
    allowed = set(definition.input_refs)
    required = allowed - set(definition.conditional_input_refs)
    unknown = sorted(set(inputs) - allowed)
    missing = sorted(required - set(inputs))
    if unknown:
        diagnostics.append("unknown input refs: " + ", ".join(unknown))
    if missing:
        diagnostics.append("missing required input refs: " + ", ".join(missing))
    records: list[dict[str, Any]] = []
    for logical_ref, path in sorted(inputs.items()):
        if logical_ref not in allowed:
            continue
        if not safe_artifact_ref(logical_ref):
            diagnostics.append(f"unsafe input ref: {logical_ref}")
            continue
        try:
            sha256, size, media_type, artifact_kind = digest_path(path)
        except (OSError, ValueError):
            diagnostics.append(f"input path for {logical_ref} is not a readable file or directory")
            continue
        records.append(
            {
                "logical_ref": logical_ref,
                "sha256": sha256,
                "size_bytes": size,
                "media_type": media_type,
                "artifact_kind": artifact_kind,
            }
        )
    return records, diagnostics


def build_request(
    *,
    operation_id: str,
    workspace_binding: dict[str, Any],
    workspace_binding_ref: str,
    workspace_binding_source_sha256: str,
    inputs: dict[str, Path],
    generated_at: str,
    operator_ref: str | None = None,
    confirmation_ref: str | None = None,
    confirmation_sha256: str | None = None,
) -> dict[str, Any]:
    definition = operation_by_id(operation_id)
    diagnostics: list[str] = []
    if definition is None:
        diagnostics.append(f"unknown managed operation: {operation_id}")
        input_records: list[dict[str, Any]] = []
    else:
        input_records, input_diagnostics = build_input_records(definition, inputs)
        diagnostics.extend(input_diagnostics)
    identity = workspace_binding.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    workspace_id = identity.get("workspace_id")
    if not isinstance(workspace_id, str) or not WORKSPACE_ID_RE.fullmatch(workspace_id):
        diagnostics.append("workspace binding has invalid workspace identity")
    if not safe_artifact_ref(workspace_binding_ref):
        diagnostics.append("workspace binding ref must be a safe logical artifact ref")
    binding_revision = workspace_binding.get("binding_revision_sha256")
    if not isinstance(binding_revision, str) or not SHA256_RE.fullmatch(binding_revision):
        diagnostics.append("workspace binding revision digest is invalid")
    if not SHA256_RE.fullmatch(workspace_binding_source_sha256):
        diagnostics.append("workspace binding source digest is invalid")
    confirmation: dict[str, str] | None = None
    if definition is not None and definition.requires_explicit_confirmation:
        if not confirmation_ref or not SHA256_RE.fullmatch(confirmation_sha256 or ""):
            diagnostics.append("operation requires digest-pinned confirmation evidence")
        elif not safe_artifact_ref(confirmation_ref):
            diagnostics.append("confirmation ref must be a safe logical artifact ref")
        else:
            confirmation = {"logical_ref": confirmation_ref, "sha256": confirmation_sha256 or ""}
    elif confirmation_ref is not None or confirmation_sha256 is not None:
        diagnostics.append("operation does not accept confirmation evidence")
    if operator_ref is not None and not safe_operator_ref(operator_ref):
        diagnostics.append("operator ref must be an opaque queue-safe ref")

    idempotency_payload = {
        "contract_ref": REQUEST_CONTRACT_REF,
        "operation_id": operation_id,
        "workspace_id": workspace_id,
        "binding_revision_sha256": binding_revision,
        "inputs": [{"logical_ref": item["logical_ref"], "sha256": item["sha256"]} for item in input_records],
        "confirmation": confirmation,
    }
    idempotency_key = hashlib.sha256(
        json.dumps(idempotency_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    request_id = f"managed-operation://{workspace_id or 'invalid'}/{operation_id}/{idempotency_key[:24]}"
    selected_operation = (
        operation_payload(definition)
        if definition is not None
        else {"operation_id": operation_id}
    )
    return {
        "artifact_kind": REQUEST_KIND,
        "schema_version": 1,
        "contract_ref": REQUEST_CONTRACT_REF,
        "generated_at": generated_at,
        "status": "ready" if not diagnostics else "blocked",
        "request_only": True,
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "delivery_semantics": "at_least_once",
        "operation": selected_operation,
        "workspace": {"workspace_id": workspace_id, "route": identity.get("route")},
        "workspace_binding": {
            "binding_id": workspace_binding.get("binding_id"),
            "binding_revision_sha256": binding_revision,
            "source_ref": workspace_binding_ref,
            "source_sha256": workspace_binding_source_sha256,
        },
        "inputs": input_records,
        "expected_output_reports": list(definition.output_reports) if definition else [],
        "operator_ref": operator_ref,
        "confirmation": confirmation,
        "diagnostics": diagnostics,
        "authority_boundary": request_authority_boundary(),
        "privacy_boundary": {
            "raw_idea_included": False,
            "operator_notes_included": False,
            "local_paths_included": False,
            "secrets_included": False,
        },
        "summary": {
            "ready_for_queue": not diagnostics,
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "input_count": len(input_records),
            "diagnostic_count": len(diagnostics),
        },
    }


def request_diagnostics(payload: dict[str, Any]) -> list[str]:
    diagnostics: list[str] = []
    allowed_top_level = {
        "artifact_kind",
        "schema_version",
        "contract_ref",
        "generated_at",
        "status",
        "request_only",
        "request_id",
        "idempotency_key",
        "delivery_semantics",
        "operation",
        "workspace",
        "workspace_binding",
        "inputs",
        "expected_output_reports",
        "operator_ref",
        "confirmation",
        "diagnostics",
        "authority_boundary",
        "privacy_boundary",
        "summary",
    }
    unknown_top_level = sorted(set(payload) - allowed_top_level)
    if unknown_top_level:
        diagnostics.append(
            "request contains fields outside the v1 contract: "
            + ", ".join(unknown_top_level)
        )
    if payload.get("artifact_kind") != REQUEST_KIND:
        diagnostics.append("request artifact_kind is invalid")
    if payload.get("schema_version") != 1 or payload.get("contract_ref") != REQUEST_CONTRACT_REF:
        diagnostics.append("request contract version is unsupported")
    operation = payload.get("operation")
    operation = operation if isinstance(operation, dict) else {}
    definition = operation_by_id(str(operation.get("operation_id") or ""))
    if definition is None:
        diagnostics.append("request operation_id is not allowlisted")
    elif operation != operation_payload(definition):
        diagnostics.append("request operation definition does not match the operation registry")
    summary = payload.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    if payload.get("status") != "ready" or summary.get("ready_for_queue") is not True:
        diagnostics.append("request must be ready before queue acceptance")
    if payload.get("diagnostics") != []:
        diagnostics.append("ready request must not contain diagnostics")
    if payload.get("request_only") is not True:
        diagnostics.append("request must be request-only")
    if payload.get("delivery_semantics") != "at_least_once":
        diagnostics.append("request delivery semantics must be at_least_once")
    if not SHA256_RE.fullmatch(str(payload.get("idempotency_key") or "")):
        diagnostics.append("request idempotency key is invalid")
    workspace = payload.get("workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    if set(workspace) != {"workspace_id", "route"}:
        diagnostics.append("request workspace projection does not match the v1 contract")
    workspace_id = workspace.get("workspace_id")
    if not isinstance(workspace_id, str) or not WORKSPACE_ID_RE.fullmatch(workspace_id):
        diagnostics.append("request workspace identity is invalid")
    if workspace.get("route") != (f"/{workspace_id}" if isinstance(workspace_id, str) else None):
        diagnostics.append("request workspace route does not match workspace identity")
    binding = payload.get("workspace_binding")
    binding = binding if isinstance(binding, dict) else {}
    if set(binding) != {
        "binding_id",
        "binding_revision_sha256",
        "source_ref",
        "source_sha256",
    }:
        diagnostics.append("request workspace binding projection does not match the v1 contract")
    if binding.get("binding_id") != (
        f"product-workspace-binding://{workspace_id}" if isinstance(workspace_id, str) else None
    ):
        diagnostics.append("request workspace binding id does not match workspace identity")
    for field in ("binding_revision_sha256", "source_sha256"):
        if not SHA256_RE.fullmatch(str(binding.get(field) or "")):
            diagnostics.append(f"request workspace binding {field} is invalid")
    if not safe_artifact_ref(binding.get("source_ref")):
        diagnostics.append("request workspace binding source ref is unsafe")
    boundary = payload.get("authority_boundary")
    boundary = boundary if isinstance(boundary, dict) else {}
    for key, expected in request_authority_boundary().items():
        if boundary.get(key) is not expected:
            diagnostics.append(f"request authority boundary field {key} is invalid")
    for key, value in boundary.items():
        if key.startswith("may_") and value is not False:
            diagnostics.append(f"request authority boundary field {key} expands authority")
    inputs = payload.get("inputs")
    if not isinstance(inputs, list):
        diagnostics.append("request inputs must be an array")
        inputs = []
    refs: set[str] = set()
    ordered_refs: list[str] = []
    for index, item in enumerate(inputs):
        if not isinstance(item, dict):
            diagnostics.append(f"request input {index} must be an object")
            continue
        ref = item.get("logical_ref")
        if not safe_artifact_ref(ref) or ref in refs:
            diagnostics.append(f"request input {index} has an invalid or duplicate logical ref")
        elif isinstance(ref, str):
            refs.add(ref)
            ordered_refs.append(ref)
        if not SHA256_RE.fullmatch(str(item.get("sha256") or "")):
            diagnostics.append(f"request input {index} has an invalid digest")
        if set(item) != {
            "logical_ref",
            "sha256",
            "size_bytes",
            "media_type",
            "artifact_kind",
        }:
            diagnostics.append(f"request input {index} does not match the v1 contract")
        size = item.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            diagnostics.append(f"request input {index} has an invalid byte size")
        media_type = item.get("media_type")
        if media_type not in {
            "application/json",
            "application/octet-stream",
            "application/vnd.platform.directory",
        }:
            diagnostics.append(f"request input {index} has an unsupported media type")
        artifact_kind = item.get("artifact_kind")
        if artifact_kind is not None and (
            not isinstance(artifact_kind, str)
            or not ARTIFACT_KIND_RE.fullmatch(artifact_kind)
        ):
            diagnostics.append(f"request input {index} has an invalid artifact kind")
    if ordered_refs != sorted(ordered_refs):
        diagnostics.append("request inputs must use deterministic logical-ref ordering")
    if definition is not None:
        allowed = set(definition.input_refs)
        required = allowed - set(definition.conditional_input_refs)
        if not refs.issubset(allowed):
            diagnostics.append("request contains input refs outside the operation registry")
        if not required.issubset(refs):
            diagnostics.append("request is missing required operation inputs")
        if payload.get("expected_output_reports") != list(definition.output_reports):
            diagnostics.append("request output reports do not match the operation registry")
    confirmation = payload.get("confirmation")
    if definition is not None and definition.requires_explicit_confirmation:
        confirmation = confirmation if isinstance(confirmation, dict) else {}
        if set(confirmation) != {"logical_ref", "sha256"}:
            diagnostics.append("request confirmation does not match the v1 contract")
        if not safe_artifact_ref(confirmation.get("logical_ref")):
            diagnostics.append("request is missing a safe confirmation ref")
        if not SHA256_RE.fullmatch(str(confirmation.get("sha256") or "")):
            diagnostics.append("request confirmation digest is invalid")
    elif confirmation is not None:
        diagnostics.append("request contains confirmation for an operation that does not accept it")
    operator_ref = payload.get("operator_ref")
    if operator_ref is not None and not safe_operator_ref(operator_ref):
        diagnostics.append("request operator ref is unsafe")
    idempotency_payload = {
        "contract_ref": REQUEST_CONTRACT_REF,
        "operation_id": operation.get("operation_id"),
        "workspace_id": workspace_id,
        "binding_revision_sha256": binding.get("binding_revision_sha256"),
        "inputs": [
            {"logical_ref": item.get("logical_ref"), "sha256": item.get("sha256")}
            for item in inputs
            if isinstance(item, dict)
        ],
        "confirmation": payload.get("confirmation"),
    }
    expected_idempotency_key = hashlib.sha256(
        json.dumps(idempotency_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if payload.get("idempotency_key") != expected_idempotency_key:
        diagnostics.append("request idempotency key does not match pinned inputs")
    expected_request_id = (
        f"managed-operation://{workspace_id or 'invalid'}/"
        f"{operation.get('operation_id')}/{expected_idempotency_key[:24]}"
    )
    if payload.get("request_id") != expected_request_id:
        diagnostics.append("request id does not match its idempotency identity")
    privacy = payload.get("privacy_boundary")
    privacy = privacy if isinstance(privacy, dict) else {}
    for key in ("raw_idea_included", "operator_notes_included", "local_paths_included", "secrets_included"):
        if privacy.get(key) is not False:
            diagnostics.append(f"request privacy boundary field {key} must be false")
    if set(privacy) != {
        "raw_idea_included",
        "operator_notes_included",
        "local_paths_included",
        "secrets_included",
    }:
        diagnostics.append("request privacy boundary does not match the v1 contract")

    def inspect_authority(value: Any, path: str = "request") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child_path = f"{path}.{key}"
                if key.startswith("may_") and item is not False:
                    diagnostics.append(f"{child_path} expands authority")
                inspect_authority(item, child_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                inspect_authority(item, f"{path}[{index}]")

    inspect_authority(payload)
    return diagnostics


def build_receipt(
    *,
    request: dict[str, Any],
    status: str,
    generated_at: str,
    attempt: int,
    output_reports: Iterable[dict[str, Any]] = (),
    diagnostics: Iterable[str] = (),
) -> dict[str, Any]:
    if status not in RECEIPT_STATUSES:
        raise ValueError(f"unsupported receipt status: {status}")
    reports = list(output_reports)
    return {
        "artifact_kind": RECEIPT_KIND,
        "schema_version": 1,
        "contract_ref": RECEIPT_CONTRACT_REF,
        "generated_at": generated_at,
        "status": status,
        "request_ref": request.get("request_id"),
        "request_sha256": hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "operation_id": (request.get("operation") or {}).get("operation_id") if isinstance(request.get("operation"), dict) else None,
        "workspace_id": (request.get("workspace") or {}).get("workspace_id") if isinstance(request.get("workspace"), dict) else None,
        "idempotency_key": request.get("idempotency_key"),
        "attempt": attempt,
        "output_reports": reports,
        "diagnostics": list(diagnostics),
        "completion_evidence": "validated_platform_output_reports" if status == "succeeded" else None,
        "authority_boundary": {
            "transport_receipt_is_execution_authority": False,
            "transport_status_is_lifecycle_evidence": False,
            "platform_output_reports_are_authoritative": True,
        },
    }


def receipt_diagnostics(payload: dict[str, Any]) -> list[str]:
    diagnostics: list[str] = []
    if payload.get("artifact_kind") != RECEIPT_KIND:
        diagnostics.append("receipt artifact_kind is invalid")
    if payload.get("schema_version") != 1 or payload.get("contract_ref") != RECEIPT_CONTRACT_REF:
        diagnostics.append("receipt contract version is unsupported")
    if payload.get("status") not in RECEIPT_STATUSES:
        diagnostics.append("receipt status is unsupported")
    attempt = payload.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
        diagnostics.append("receipt attempt must be a non-negative integer")
    elif payload.get("status") not in {"rejected", "queued"} and attempt < 1:
        diagnostics.append("leased or completed receipt must record an execution attempt")
    if not SHA256_RE.fullmatch(str(payload.get("request_sha256") or "")):
        diagnostics.append("receipt request digest is invalid")
    if not SHA256_RE.fullmatch(str(payload.get("idempotency_key") or "")):
        diagnostics.append("receipt idempotency key is invalid")
    boundary = payload.get("authority_boundary")
    boundary = boundary if isinstance(boundary, dict) else {}
    expected_boundary = {
        "transport_receipt_is_execution_authority": False,
        "transport_status_is_lifecycle_evidence": False,
        "platform_output_reports_are_authoritative": True,
    }
    if boundary != expected_boundary:
        diagnostics.append("receipt authority boundary is invalid")
    reports = payload.get("output_reports")
    if not isinstance(reports, list):
        diagnostics.append("receipt output reports must be an array")
        reports = []
    for index, report in enumerate(reports):
        if not isinstance(report, dict) or not safe_artifact_ref(report.get("logical_ref")):
            diagnostics.append(f"receipt output report {index} has an unsafe ref")
            continue
        if not SHA256_RE.fullmatch(str(report.get("sha256") or "")):
            diagnostics.append(f"receipt output report {index} has an invalid digest")
    if payload.get("status") == "succeeded" and not reports:
        diagnostics.append("succeeded receipt must cite validated Platform output reports")
    return diagnostics
