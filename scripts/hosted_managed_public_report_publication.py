"""Build and dispatch bounded public-safe hosted managed-operation reports."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable
import urllib.error
import urllib.request


PACKET_ARTIFACT_KIND = "platform_hosted_managed_publication_packet"
PACKET_CONTRACT_REF = "platform.hosted-managed.public-report-publication.v1"
WORKSPACE_ID = "hosted-operation-canary"
OPERATION_ID = "review_status_execute"
CANDIDATE_BRANCH = "graph-candidate/hosted-operation-canary"
REVIEW_OBJECT_REF = "runs/product_candidate_promotion_review_object_evidence.json"
REVIEW_STATUS_REF = "runs/product_candidate_promotion_review_status_report.json"
REVIEW_OBJECT_KIND = "platform_product_candidate_promotion_review_object_evidence"
REVIEW_STATUS_KIND = "platform_product_candidate_promotion_review_status_report"
PROMOTION_EXECUTION_KIND = "platform_product_candidate_promotion_execution_report"
WORKER_WINDOW_KIND = "platform_hosted_managed_worker_window_report"
WORKER_WINDOW_CONTRACT_REF = "platform.hosted-managed.worker-window.v1"
DISPATCH_REPORT_KIND = "platform_hosted_managed_publication_dispatch_report"
GITHUB_REPOSITORY = "0al-spec/SpecGraph"
GITHUB_WORKFLOW = "publish-static-artifacts.yml"
MAX_INPUT_BYTES = 256 * 1024
MAX_PACKET_BYTES = 32 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVIEW_URL_RE = re.compile(
    r"^https://github\.com/0al-spec/SpecGraph/pull/([1-9][0-9]*)$"
)
LOCAL_PATH_RE = re.compile(
    r"(?:^|[\s\"'])(?:/Users/|/home/|/private/|/tmp/|/var/folders/|"
    r"/srv/|/workspace/|/github/workspace/|/opt/|/root/|/etc/0al/|"
    r"/run/secrets/|/data/|[A-Za-z]:\\)"
)
SECRET_VALUE_RE = re.compile(
    r"(?:"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"gh[opusr]_[A-Za-z0-9_]{20,}|"
    r"Bearer\s+\S{20,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:password|secret|token|authorization)\s*[:=]\s*\S+"
    r")",
    re.IGNORECASE,
)
FORBIDDEN_KEY_PARTS = (
    "command",
    "stdout",
    "stderr",
    "exit_code",
    "returncode",
    "password",
    "secret",
    "token",
    "raw_idea",
    "workspace_dir",
    "repository_dir",
)


class PublicationError(RuntimeError):
    """A hosted report cannot be published without widening its contract."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() == value and value else None


def _non_negative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_absolute():
        raise PublicationError(f"{label} path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise PublicationError(f"{label} must be a regular file")
    try:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise PublicationError(f"{label} is too large")
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PublicationError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise PublicationError(f"{label} must contain a JSON object")
    return payload


def _json_bytes(payload: dict[str, Any]) -> bytes:
    try:
        rendered = json.dumps(
            payload,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise PublicationError("publication packet contains non-strict JSON") from exc
    return (rendered + "\n").encode("utf-8")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PublicationError(f"cannot hash {path.name}") from exc
    return digest.hexdigest()


def _strict_false_boundary(
    value: Any,
    *,
    required: tuple[str, ...],
    allowed_true: tuple[str, ...] = (),
) -> bool:
    boundary = _record(value)
    return all(boundary.get(key) is False for key in required) and all(
        isinstance(key, str)
        and (
            item is False
            or (key in allowed_true and item is True)
        )
        for key, item in boundary.items()
    )


def _privacy_ready(value: Any) -> bool:
    privacy = _record(value)
    return (
        privacy.get("public_safe") is True
        and privacy.get("raw_idea_included") is False
        and privacy.get("local_paths_included") is False
    )


def _identity(payload: dict[str, Any]) -> tuple[str, str, str]:
    workspace_id = _text(payload.get("workspace_id"))
    candidate_id = _text(payload.get("candidate_id"))
    candidate_branch = _text(payload.get("candidate_branch"))
    if (
        workspace_id != WORKSPACE_ID
        or candidate_id != WORKSPACE_ID
        or candidate_branch != CANDIDATE_BRANCH
    ):
        raise PublicationError("hosted report workspace or candidate identity is invalid")
    return workspace_id, candidate_id, candidate_branch


def _public_workspace_binding(value: Any, *, workspace_id: str) -> dict[str, str]:
    binding = _record(value)
    authority = _record(binding.get("authority_boundary"))
    binding_id = f"product-workspace-binding://{workspace_id}"
    binding_revision = _text(binding.get("binding_revision_sha256"))
    source_digest = _text(binding.get("source_sha256"))
    if (
        binding.get("status") != "ready"
        or binding.get("workspace_id") != workspace_id
        or binding.get("binding_id") != binding_id
        or binding_revision is None
        or SHA256_RE.fullmatch(binding_revision) is None
        or source_digest is None
        or SHA256_RE.fullmatch(source_digest) is None
        or authority.get("report_only") is not True
        or not _strict_false_boundary(
            authority,
            required=(
                "may_create_git_commit",
                "may_execute_platform",
                "may_execute_specgraph",
                "may_open_pull_request",
                "may_publish_read_model",
            ),
            allowed_true=("report_only",),
        )
    ):
        raise PublicationError("review object workspace binding is invalid")
    return {
        "status": "ready",
        "workspace_id": workspace_id,
        "binding_id": binding_id,
    }


def _review_url(value: Any, number: Any) -> tuple[str, int]:
    review_url = _text(value)
    review_number = _non_negative_int(number)
    match = REVIEW_URL_RE.fullmatch(review_url or "")
    if (
        match is None
        or review_number is None
        or review_number == 0
        or int(match.group(1)) != review_number
    ):
        raise PublicationError("review URL and number must identify a SpecGraph pull request")
    return review_url, review_number


def _public_authority_boundary() -> dict[str, bool]:
    return {
        "accepts_arbitrary_commands": False,
        "creates_git_commits": False,
        "merges_pull_requests": False,
        "mutates_canonical_specs": False,
        "opens_pull_requests": False,
        "publishes_read_models": False,
        "writes_ontology_packages": False,
        "accepts_ontology_terms": False,
    }


def _public_privacy_boundary() -> dict[str, bool]:
    return {
        "public_safe": True,
        "raw_idea_included": False,
        "local_paths_included": False,
    }


def _scan_public(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PublicationError("publication packet contains a non-string key")
            negative_boundary_declaration = (
                path[-1:] == ("authority_boundary",) and item is False
            ) or (
                path[-1:] == ("privacy_boundary",)
                and key in {
                    "raw_idea_included",
                    "local_paths_included",
                }
                and item is False
            )
            if (
                any(part in key.lower() for part in FORBIDDEN_KEY_PARTS)
                and not negative_boundary_declaration
            ):
                raise PublicationError(
                    f"publication packet contains forbidden field {'.'.join((*path, key))}"
                )
            if key.startswith("may_") and item is not False:
                raise PublicationError("publication packet expands unknown may_* authority")
            _scan_public(item, path=(*path, key))
        return
    if isinstance(value, list):
        if len(value) > 128:
            raise PublicationError("publication packet contains an oversized list")
        for index, item in enumerate(value):
            _scan_public(item, path=(*path, str(index)))
        return
    if isinstance(value, str):
        if len(value) > 4096 or any(ord(character) < 32 for character in value):
            raise PublicationError("publication packet contains unsafe text")
        if LOCAL_PATH_RE.search(value):
            raise PublicationError("publication packet contains a local path")
        if SECRET_VALUE_RE.search(value):
            raise PublicationError("publication packet contains a secret-like value")


def validate_packet_for_dispatch(packet: dict[str, Any]) -> None:
    logical_ref = _text(packet.get("logical_ref"))
    report = _record(packet.get("report"))
    expected_kind = {
        REVIEW_OBJECT_REF: REVIEW_OBJECT_KIND,
        REVIEW_STATUS_REF: REVIEW_STATUS_KIND,
    }.get(logical_ref)
    if (
        packet.get("artifact_kind") != PACKET_ARTIFACT_KIND
        or packet.get("contract_ref") != PACKET_CONTRACT_REF
        or packet.get("schema_version") != 1
        or packet.get("workspace_id") != WORKSPACE_ID
        or packet.get("operation_id") != OPERATION_ID
        or expected_kind is None
        or report.get("artifact_kind") != expected_kind
        or packet.get("publication_scope")
        != {
            "workspace_bundle_only": True,
            "maximum_report_count": 1,
            "incremental_upload_required": True,
        }
        or packet.get("summary")
        != {
            "status": "publication_packet_ready",
            "report_count": 1,
        }
        or packet.get("privacy_boundary") != _public_privacy_boundary()
        or not _strict_false_boundary(
            packet.get("authority_boundary"),
            required=tuple(_public_authority_boundary()),
        )
        or packet.get("public_report_sha256")
        != hashlib.sha256(_json_bytes(report)).hexdigest()
        or len(_json_bytes(packet)) > MAX_PACKET_BYTES
    ):
        raise PublicationError("publication packet is not dispatch-ready")
    _scan_public(packet)


def _validate_promotion_execution(
    path: Path,
    payload: dict[str, Any],
) -> tuple[str, str, str]:
    identity = _identity(payload)
    authority = _record(payload.get("authority_boundary"))
    exercised_authority = (
        "controlled_git_service_execution",
        "creates_candidate_commit",
        "creates_candidate_worktree_or_branch",
        "opens_pull_requests",
    )
    if (
        payload.get("artifact_kind") != PROMOTION_EXECUTION_KIND
        or payload.get("schema_version") != 1
        or payload.get("ok") is not True
        or payload.get("dry_run") is not False
        or payload.get("open_review_dry_run") is not False
        or payload.get("workflow_lane") != "product_idea_to_spec"
    ):
        raise PublicationError("promotion execution report is not ready for review")
    if (
        not all(authority.get(key) is True for key in exercised_authority)
        or not _strict_false_boundary(
            authority,
            required=(
                "merges_pull_requests",
                "publishes_read_models",
                "ontology_package_write",
                "ontology_term_acceptance",
                "private_artifact_publication",
                "specspace_direct_git_write",
            ),
            allowed_true=exercised_authority,
        )
    ):
        raise PublicationError("promotion execution report expands authority")
    if not path.is_file():
        raise PublicationError("promotion execution report is missing")
    return identity


def build_review_object_report(
    *,
    evidence_path: Path,
    execution_report_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = _load_json(evidence_path, label="review object evidence")
    execution = _load_json(
        execution_report_path,
        label="promotion execution report",
    )
    execution_identity = _validate_promotion_execution(
        execution_report_path,
        execution,
    )
    evidence_identity = _identity(evidence)
    review_url, review_number = _review_url(
        evidence.get("review_url"),
        evidence.get("review_number"),
    )
    head_sha = _text(evidence.get("review_head_sha"))
    if (
        evidence.get("artifact_kind") != REVIEW_OBJECT_KIND
        or evidence.get("schema_version") != 1
        or evidence.get("ok") is not True
        or evidence.get("probe_only") is not True
        or evidence.get("review_state_at_capture") != "open"
        or evidence.get("base_branch") != "main"
        or evidence.get("promotion_execution_report_ref")
        != "runs/product_candidate_promotion_execution_report.json"
        or evidence.get("promotion_execution_report_sha256")
        != _file_sha256(execution_report_path)
        or evidence_identity != execution_identity
        or head_sha is None
        or not re.fullmatch(r"[0-9a-f]{40}", head_sha)
        or not _privacy_ready(evidence.get("privacy_boundary"))
        or not _strict_false_boundary(
            evidence.get("authority_boundary"),
            required=(
                "opens_pull_requests",
                "merges_pull_requests",
                "publishes_read_models",
                "creates_git_commits",
                "mutates_canonical_specs",
                "writes_ontology_packages",
                "accepts_ontology_terms",
            ),
        )
    ):
        raise PublicationError("review object evidence is not public-publication ready")
    workspace_id, candidate_id, candidate_branch = evidence_identity
    evidence_binding = _public_workspace_binding(
        evidence.get("workspace_binding"),
        workspace_id=workspace_id,
    )
    workspace_binding = _public_workspace_binding(
        execution.get("workspace_binding"),
        workspace_id=workspace_id,
    )
    evidence_binding_source = _record(evidence.get("workspace_binding"))
    execution_binding_source = _record(execution.get("workspace_binding"))
    if (
        evidence_binding != workspace_binding
        or evidence_binding_source.get("binding_revision_sha256")
        != execution_binding_source.get("binding_revision_sha256")
        or evidence_binding_source.get("source_sha256")
        != execution_binding_source.get("source_sha256")
    ):
        raise PublicationError(
            "review object workspace binding does not match promotion execution"
        )
    report = {
        "schema_version": 1,
        "artifact_kind": REVIEW_OBJECT_KIND,
        "generated_at": _text(evidence.get("generated_at")) or _now_iso(),
        "ok": True,
        "probe_only": True,
        "promotion_execution_report_ref": (
            "runs/product_candidate_promotion_execution_report.json"
        ),
        "promotion_execution_report_sha256": _file_sha256(execution_report_path),
        "workspace_id": workspace_id,
        "candidate_id": candidate_id,
        "candidate_branch": candidate_branch,
        "review_url": review_url,
        "review_number": review_number,
        "review_state_at_capture": "open",
        "review_head_sha": head_sha,
        "base_branch": "main",
        "workspace_binding": workspace_binding,
        "privacy_boundary": _public_privacy_boundary(),
        "authority_boundary": _public_authority_boundary(),
        "diagnostics": [],
        "summary": {
            "status": "review_object_ready",
            "error_count": 0,
            "next_action": (
                "Run read-only review status inspection in a bounded worker window."
            ),
        },
    }
    provenance = {
        "source_artifact_kind": REVIEW_OBJECT_KIND,
        "source_sha256": _file_sha256(evidence_path),
        "promotion_execution_report_sha256": _file_sha256(execution_report_path),
        "review_number": review_number,
        "review_head_sha": head_sha,
    }
    return report, provenance


def _safe_pull_request(payload: dict[str, Any]) -> dict[str, Any]:
    review_url, review_number = _review_url(payload.get("url"), payload.get("number"))
    head_sha = _text(payload.get("headRefOid"))
    head_branch = _text(payload.get("headRefName"))
    base_branch = _text(payload.get("baseRefName"))
    state = _text(payload.get("state"))
    if (
        head_sha is None
        or not re.fullmatch(r"[0-9a-f]{40}", head_sha)
        or head_branch != CANDIDATE_BRANCH
        or base_branch != "main"
        or state not in {"OPEN", "CLOSED", "MERGED"}
        or not isinstance(payload.get("isDraft"), bool)
    ):
        raise PublicationError("review status pull request identity is invalid")
    merge_commit = _record(payload.get("mergeCommit"))
    merge_oid = _text(merge_commit.get("oid"))
    if merge_oid is not None and not re.fullmatch(r"[0-9a-f]{40}", merge_oid):
        raise PublicationError("review status merge commit is invalid")
    return {
        "number": review_number,
        "url": review_url,
        "state": state,
        "isDraft": payload["isDraft"],
        "headRefName": head_branch,
        "baseRefName": "main",
        "headRefOid": head_sha,
        "reviewDecision": _text(payload.get("reviewDecision")) or "",
        "mergedAt": _text(payload.get("mergedAt")),
        "mergeCommit": {"oid": merge_oid} if merge_oid else None,
    }


def _validate_worker_window(
    payload: dict[str, Any],
    *,
    source_report_path: Path,
) -> dict[str, Any]:
    request = _record(payload.get("request"))
    execution = _record(payload.get("execution"))
    summary = _record(payload.get("summary"))
    outputs = execution.get("authoritative_output_reports")
    privacy = _record(payload.get("privacy_boundary"))
    authority = _record(payload.get("authority_boundary"))
    if (
        payload.get("artifact_kind") != WORKER_WINDOW_KIND
        or payload.get("contract_ref") != WORKER_WINDOW_CONTRACT_REF
        or payload.get("schema_version") != 1
        or request.get("operation_id") != OPERATION_ID
        or request.get("workspace_id") != WORKSPACE_ID
        or request.get("initial_attempt") != 0
        or execution.get("receipt_status") != "succeeded"
        or execution.get("attempt") != 1
        or execution.get("operation_processed") is not True
        or summary.get("status") != "bounded_worker_window_completed"
        or summary.get("one_shot_cycle_complete") is not True
        or summary.get("queue_drained") is not True
        or summary.get("processed_operation_count") != 1
        or summary.get("authoritative_reports_ready") is not True
        or not isinstance(outputs, list)
        or len(outputs) != 1
        or _record(outputs[0]).get("logical_ref") != REVIEW_STATUS_REF
        or _record(outputs[0]).get("sha256") != _file_sha256(source_report_path)
        or privacy
        != {
            "public_safe": True,
            "includes_request_payload": False,
            "includes_secret_values": False,
            "includes_local_paths": False,
        }
        or authority.get("platform_output_reports_are_authoritative") is not True
        or not _strict_false_boundary(
            authority,
            required=(
                "accepts_arbitrary_commands",
                "expands_operation_allowlist",
                "executes_unpinned_requests",
                "keeps_worker_running",
                "retries_irreversible_operations",
                "queue_status_is_lifecycle_evidence",
            ),
            allowed_true=("platform_output_reports_are_authoritative",),
        )
    ):
        raise PublicationError("bounded worker window does not pin one ready review report")
    return request


def build_review_status_report(
    *,
    worker_window_path: Path,
    source_report_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    window = _load_json(worker_window_path, label="bounded worker window report")
    source = _load_json(source_report_path, label="review status report")
    request = _validate_worker_window(window, source_report_path=source_report_path)
    workspace_id, candidate_id, candidate_branch = _identity(source)
    pull_request = _safe_pull_request(_record(source.get("pull_request")))
    summary = _record(source.get("summary"))
    graph_review = _record(source.get("graph_repository_review_status"))
    graph_summary = _record(graph_review.get("summary"))
    review_url, _review_number = _review_url(
        pull_request.get("url"),
        pull_request.get("number"),
    )
    review_state = _text(source.get("review_state"))
    expected_pull_request_state = {
        "open": "OPEN",
        "closed": "CLOSED",
        "merged": "MERGED",
    }.get(review_state)
    expected_summary_status = (
        "ready_for_read_model_publication"
        if review_state == "merged"
        else "waiting_for_review_merge"
    )
    review_merged = review_state == "merged"
    if (
        source.get("artifact_kind") != REVIEW_STATUS_KIND
        or source.get("schema_version") != 1
        or source.get("ok") is not True
        or source.get("workflow_lane") != "product_idea_to_spec"
        or expected_pull_request_state is None
        or source.get("review_probe_only") is not False
        or pull_request.get("headRefName") != candidate_branch
        or pull_request.get("state") != expected_pull_request_state
        or _text(graph_review.get("review_url")) != review_url
        or graph_review.get("ok") is not True
        or graph_review.get("review_state") != review_state
        or graph_summary.get("review_merged") is not review_merged
        or summary.get("status") != expected_summary_status
        or summary.get("review_merged") is not review_merged
        or summary.get("read_model_published") is not False
        or not _strict_false_boundary(
            source.get("authority_boundary"),
            required=(
                "executes_git_commands",
                "opens_pull_requests",
                "merges_pull_requests",
                "publishes_read_models",
                "canonical_spec_mutation_without_review",
                "ontology_package_write",
                "ontology_term_acceptance",
                "private_artifact_publication",
                "specspace_direct_git_write",
            ),
        )
    ):
        raise PublicationError("review status report is not public-publication ready")
    report = {
        "schema_version": 1,
        "artifact_kind": REVIEW_STATUS_KIND,
        "generated_at": _text(source.get("generated_at")) or _now_iso(),
        "ok": True,
        "workflow_lane": "product_idea_to_spec",
        "workspace_id": workspace_id,
        "candidate_id": candidate_id,
        "candidate_branch": candidate_branch,
        "promotion_execution_report_ref": (
            "runs/product_candidate_promotion_execution_report.json"
        ),
        "review_object_evidence_ref": REVIEW_OBJECT_REF,
        "review_probe_only": False,
        "review_state": review_state,
        "review_decision": _text(source.get("review_decision")) or "",
        "pull_request": pull_request,
        "graph_repository_review_status": {
            "artifact_kind": _text(graph_review.get("artifact_kind")),
            "ok": True,
            "review_state": review_state,
            "review_url": review_url,
            "summary": {
                "status": _text(graph_summary.get("status")),
                "review_merged": review_merged,
            },
        },
        "authority_boundary": _public_authority_boundary(),
        "privacy_boundary": _public_privacy_boundary(),
        "diagnostics": [],
        "summary": {
            "status": expected_summary_status,
            "review_merged": review_merged,
            "read_model_published": False,
            "error_count": 0,
        },
    }
    provenance = {
        "source_artifact_kind": REVIEW_STATUS_KIND,
        "source_sha256": _file_sha256(source_report_path),
        "worker_window_sha256": _file_sha256(worker_window_path),
        "window_id": _text(window.get("window_id")),
        "attempt": 1,
        "request_id_sha256": hashlib.sha256(
            str(request.get("request_id")).encode("utf-8")
        ).hexdigest(),
        "review_number": pull_request["number"],
        "review_head_sha": pull_request["headRefOid"],
    }
    return report, provenance


def build_packet(
    *,
    logical_ref: str,
    report: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    if logical_ref not in {REVIEW_OBJECT_REF, REVIEW_STATUS_REF}:
        raise PublicationError("publication logical ref is not allowlisted")
    expected_kind = (
        REVIEW_OBJECT_KIND if logical_ref == REVIEW_OBJECT_REF else REVIEW_STATUS_KIND
    )
    if report.get("artifact_kind") != expected_kind:
        raise PublicationError("publication report kind does not match its logical ref")
    report_bytes = _json_bytes(report)
    packet = {
        "schema_version": 1,
        "artifact_kind": PACKET_ARTIFACT_KIND,
        "contract_ref": PACKET_CONTRACT_REF,
        "generated_at": _now_iso(),
        "workspace_id": WORKSPACE_ID,
        "operation_id": OPERATION_ID,
        "logical_ref": logical_ref,
        "public_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "report": report,
        "source_provenance": provenance,
        "publication_scope": {
            "workspace_bundle_only": True,
            "maximum_report_count": 1,
            "incremental_upload_required": True,
        },
        "privacy_boundary": _public_privacy_boundary(),
        "authority_boundary": _public_authority_boundary(),
        "summary": {
            "status": "publication_packet_ready",
            "report_count": 1,
        },
    }
    if len(_json_bytes(packet)) > MAX_PACKET_BYTES:
        raise PublicationError("publication packet exceeds its bounded size")
    validate_packet_for_dispatch(packet)
    return packet


def write_json(path: Path, payload: dict[str, Any]) -> None:
    if not path.is_absolute():
        raise PublicationError("output path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(payload)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def dispatch_packet(
    *,
    packet_path: Path,
    token_file: Path,
    ref: str,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    if ref != "main":
        raise PublicationError("SpecGraph publication dispatch ref must be main")
    packet = _load_json(packet_path, label="publication packet")
    validate_packet_for_dispatch(packet)
    if not token_file.is_absolute() or token_file.is_symlink() or not token_file.is_file():
        raise PublicationError("GitHub token file must be an absolute regular file")
    try:
        if token_file.stat().st_size > 4096:
            raise PublicationError("GitHub token file is too large")
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PublicationError("GitHub token file is unreadable") from exc
    if len(token) < 20 or any(character.isspace() for character in token):
        raise PublicationError("GitHub token file is invalid")
    encoded_packet = base64.b64encode(_json_bytes(packet)).decode("ascii")
    dispatched_packet_sha256 = hashlib.sha256(_json_bytes(packet)).hexdigest()
    body = _json_bytes(
        {
            "ref": ref,
            "inputs": {
                "hosted_managed_publication_packet_b64": encoded_packet,
            },
        }
    )
    request = urllib.request.Request(
        (
            "https://api.github.com/repos/"
            f"{GITHUB_REPOSITORY}/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
        ),
        data=body,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "0al-platform-hosted-publication",
        },
        method="POST",
    )
    try:
        response = urlopen(request, timeout=15)
        status = getattr(response, "status", None)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PublicationError("SpecGraph publication workflow dispatch failed") from exc
    if status != 204:
        raise PublicationError("SpecGraph publication workflow rejected the dispatch")
    return {
        "schema_version": 1,
        "artifact_kind": DISPATCH_REPORT_KIND,
        "generated_at": _now_iso(),
        "ok": True,
        "repository": GITHUB_REPOSITORY,
        "workflow": GITHUB_WORKFLOW,
        "ref": ref,
        "publication_packet_sha256": dispatched_packet_sha256,
        "logical_ref": packet.get("logical_ref"),
        "workspace_id": packet.get("workspace_id"),
        "summary": {
            "status": "publication_dispatch_accepted",
        },
        "privacy_boundary": {
            "public_safe": True,
            "includes_token": False,
            "includes_local_paths": False,
        },
        "authority_boundary": {
            "accepts_arbitrary_workflows": False,
            "accepts_arbitrary_repositories": False,
            "accepts_arbitrary_commands": False,
            "mutates_canonical_specs": False,
            "opens_pull_requests": False,
        },
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Build or dispatch a bounded hosted public report packet."
    )
    subparsers = root.add_subparsers(dest="command", required=True)

    review_object = subparsers.add_parser("review-object")
    review_object.add_argument("--evidence", required=True)
    review_object.add_argument("--execution-report", required=True)
    review_object.add_argument("--output", required=True)

    review_status = subparsers.add_parser("review-status")
    review_status.add_argument("--worker-window-report", required=True)
    review_status.add_argument("--source-report", required=True)
    review_status.add_argument("--output", required=True)

    dispatch = subparsers.add_parser("dispatch")
    dispatch.add_argument("--packet", required=True)
    dispatch.add_argument("--github-token-file", required=True)
    dispatch.add_argument("--ref", default="main")
    dispatch.add_argument("--output", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        output = Path(args.output).resolve()
        if args.command == "review-object":
            report, provenance = build_review_object_report(
                evidence_path=Path(args.evidence).resolve(),
                execution_report_path=Path(args.execution_report).resolve(),
            )
            payload = build_packet(
                logical_ref=REVIEW_OBJECT_REF,
                report=report,
                provenance=provenance,
            )
        elif args.command == "review-status":
            report, provenance = build_review_status_report(
                worker_window_path=Path(args.worker_window_report).resolve(),
                source_report_path=Path(args.source_report).resolve(),
            )
            payload = build_packet(
                logical_ref=REVIEW_STATUS_REF,
                report=report,
                provenance=provenance,
            )
        else:
            payload = dispatch_packet(
                packet_path=Path(args.packet).resolve(),
                token_file=Path(args.github_token_file).resolve(),
                ref=args.ref,
            )
        write_json(output, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except PublicationError as exc:
        print(
            json.dumps(
                {
                    "artifact_kind": "platform_hosted_managed_publication_error",
                    "ok": False,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
