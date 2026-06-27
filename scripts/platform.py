#!/usr/bin/env python3
"""Small Platform operator CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_CATALOG = REPO_ROOT / "workspaces.local.yaml"
DEFAULT_EXAMPLE_CATALOG = REPO_ROOT / "workspaces.example.yaml"
DEFAULT_LOCAL_COMPOSE = REPO_ROOT / "docker-compose.local.yml"
DEFAULT_EXAMPLE_COMPOSE = REPO_ROOT / "docker-compose.example.yml"
DEFAULT_PRODUCTION_WEB_COMPOSE = REPO_ROOT / "docker-compose.production-web.example.yml"
DEFAULT_PRODUCT_IDEA_TO_SPEC_DEPLOYMENT_PROFILE = (
    REPO_ROOT / "deployment-profile.product-idea-to-spec.example.json"
)
DEFAULT_LOCAL_ENV = REPO_ROOT / ".env"
SPECGRAPH_SUPERVISOR_REL = Path("tools") / "supervisor.py"
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
PRODUCT_WORKSPACE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
INIT_TIMEOUT_SECONDS = 120
DEFAULT_TIMEWEB_HYPERPROMPT_WORK_DIR = "/tmp"
DEFAULT_TIMEWEB_HYPERPROMPT_COMPILE_TIMEOUT_SECONDS = "60"
DEFAULT_TIMEWEB_HYPERPROMPT_MAX_INPUT_BYTES = "1048576"
DEFAULT_TIMEWEB_HYPERPROMPT_MAX_OUTPUT_BYTES = "2097152"
DEFAULT_TIMEWEB_HYPERPROMPT_BUNDLE_RETENTION_COUNT = "20"
DIGEST_IMAGE_RE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*(?::[a-z0-9._-]+)?@sha256:[0-9a-f]{64}$"
)
GRAPH_REPOSITORY_REQUIRED_RUN_ARTIFACTS = {
    "idea_event_storming_intake": (
        "idea_event_storming_intake.json",
        "idea_event_storming_intake",
    ),
    "candidate_spec_graph": (
        "candidate_spec_graph.json",
        "candidate_spec_graph",
    ),
    "pre_sib_coherence_report": (
        "pre_sib_coherence_report.json",
        "pre_sib_coherence_report",
    ),
    "candidate_repair_loop_report": (
        "candidate_repair_loop_report.json",
        "candidate_repair_loop_report",
    ),
    "idea_to_spec_clarification_requests": (
        "idea_to_spec_clarification_requests.json",
        "idea_to_spec_clarification_requests",
    ),
    "idea_to_spec_clarification_answers": (
        "idea_to_spec_clarification_answers.json",
        "idea_to_spec_clarification_answers",
    ),
    "product_ontology_gap_review_decisions": (
        "product_ontology_gap_review_decisions.json",
        "product_ontology_gap_review_decisions",
    ),
    "idea_to_spec_answer_rerun_input": (
        "idea_to_spec_answer_rerun_input.json",
        "idea_to_spec_answer_rerun_input",
    ),
    "idea_to_spec_rerun_preview": (
        "idea_to_spec_rerun_preview.json",
        "idea_to_spec_rerun_preview",
    ),
    "idea_to_spec_rerun_materialization": (
        "idea_to_spec_rerun_materialization.json",
        "idea_to_spec_rerun_materialization",
    ),
    "idea_to_spec_repair_session": (
        "idea_to_spec_repair_session.json",
        "idea_to_spec_repair_session_journal",
    ),
}
GRAPH_REPOSITORY_REPAIR_SESSION_CONTRACT_REF = (
    "specgraph.idea-to-spec.repair-session-journal.v0.1"
)
GRAPH_REPOSITORY_REPAIR_SESSION_SOURCE_REFS = {
    "active_candidate": "runs/active_idea_to_spec_candidate.json",
    "clarification_requests": "runs/idea_to_spec_clarification_requests.json",
    "clarification_answers": "runs/idea_to_spec_clarification_answers.json",
    "ontology_decisions": "runs/product_ontology_gap_review_decisions.json",
    "rerun_input": "runs/idea_to_spec_answer_rerun_input.json",
    "rerun_preview": "runs/idea_to_spec_rerun_preview.json",
    "rerun_materialization": "runs/idea_to_spec_rerun_materialization.json",
    "promotion_gate": "runs/idea_to_spec_promotion_gate.json",
}
GRAPH_REPOSITORY_REPAIR_SESSION_AUTHORITY_FLAGS = (
    "may_accept_ontology_terms",
    "may_apply_answers_to_source_artifacts",
    "may_apply_decisions_to_source_artifacts",
    "may_create_branch_or_commit",
    "may_execute_prompt_agent",
    "may_mark_candidate_graph_accepted",
    "may_mutate_candidate_source_artifacts",
    "may_mutate_canonical_specs",
    "may_open_pull_request",
    "may_publish_read_model",
    "may_write_ontology_lockfile",
    "may_write_ontology_package",
)
GRAPH_REPOSITORY_REPAIR_SESSION_PRIVATE_FLAGS = (
    "raw_idea_text_published",
    "raw_model_output_published",
    "raw_operator_note_published",
    "raw_prompt_published",
)
GRAPH_REPOSITORY_PROMOTION_PATH_PREFIXES = (
    "specs/",
    "docs/proposals/",
    "runs/",
)
PRODUCT_REPAIR_RERUN_PLAN_KIND = "platform_product_repair_rerun_execution_plan"
PRODUCT_REPAIR_RERUN_EXECUTION_REPORT_KIND = (
    "platform_product_repair_rerun_execution_report"
)
PRODUCT_REPAIR_RERUN_PUBLICATION_REPORT_KIND = (
    "platform_product_repair_rerun_publication_report"
)
PRODUCT_REPAIR_RERUN_SMOKE_REPORT_KIND = "platform_product_repair_rerun_smoke_report"
PRODUCT_REPAIR_RERUN_REQUEST_KIND = (
    "specspace_idea_to_spec_repair_rerun_request_state"
)
PRODUCT_REPAIR_RERUN_IMPORT_PREVIEW_KIND = "specspace_repair_draft_import_preview"
PRODUCT_REPAIR_RERUN_IMPORT_PREVIEW_CONTRACT_REF = (
    "specgraph.idea-to-spec.specspace-repair-draft-import-preview.v0.1"
)
PRODUCT_REPAIR_RERUN_GATE_KIND = "specspace_repair_rerun_request_gate"
PRODUCT_REPAIR_RERUN_GATE_CONTRACT_REF = (
    "specgraph.idea-to-spec.specspace-repair-rerun-request-gate.v0.1"
)
PRODUCT_REPAIR_RERUN_REPORT_KIND = "specspace_repair_draft_rerun_report"
PRODUCT_REPAIR_RERUN_REPORT_CONTRACT_REF = (
    "specgraph.idea-to-spec.specspace-repair-draft-rerun.v0.1"
)
PRODUCT_REPAIR_RERUN_MAKE_TARGET = "product-workspace-requested-repair-draft-rerun"
PRODUCT_REPAIR_RERUN_DEFAULT_OUTPUTS = {
    "request_gate": "runs/specspace_repair_rerun_request_gate.json",
    "rerun_report": "runs/specspace_repair_draft_rerun_report.json",
    "repair_session": "runs/idea_to_spec_repair_session.json",
    "rerun_preview": "runs/idea_to_spec_rerun_preview.json",
    "rerun_materialization": "runs/idea_to_spec_rerun_materialization.json",
}
PRODUCT_REPAIR_RERUN_DEFAULT_INPUTS = {
    "rerun_request": "runs/idea_to_spec_repair_rerun_requests.json",
    "import_preview": "runs/specspace_repair_draft_import_preview.json",
    "repair_session": "runs/idea_to_spec_repair_session.json",
    "request_gate": "runs/specspace_repair_rerun_request_gate.json",
}
PRODUCT_REPAIR_RERUN_DEFAULT_REPORTS = {
    "plan": "runs/platform_product_repair_rerun_execution_plan.json",
    "execution": "runs/platform_product_repair_rerun_execution_report.json",
    "publication": "runs/platform_product_repair_rerun_publication_report.json",
    "smoke": "runs/platform_product_repair_rerun_smoke_report.json",
}
PRODUCT_REPAIR_RERUN_FALSE_TOP_LEVEL_FIELDS = (
    "canonical_mutations_allowed",
    "tracked_artifacts_written",
)
PRODUCT_REPAIR_RERUN_REQUEST_FALSE_FIELDS = (
    "may_execute_specgraph",
    "may_run_make_target",
    "may_execute_prompt_agent",
    "may_apply_to_specgraph",
    "may_apply_answers",
    "may_apply_decisions",
    "may_apply_drafts_to_source_artifacts",
    "may_apply_answers_to_source_artifacts",
    "may_apply_decisions_to_source_artifacts",
    "may_mutate_candidate_source_artifacts",
    "may_mutate_canonical_specs",
    "may_write_ontology_package",
    "may_write_ontology_lockfile",
    "may_accept_ontology_terms",
    "may_mark_candidate_graph_accepted",
    "may_create_branch_or_commit",
    "may_open_pull_request",
    "may_publish_read_model",
    "may_execute_git_service_operation",
    "canonical_mutations_allowed",
    "tracked_artifacts_written",
)
PRODUCT_REPAIR_RERUN_BOUNDARY_FALSE_FIELDS = (
    "may_execute_specgraph",
    "may_run_make_target",
    "may_execute_prompt_agent",
    "may_apply_to_specgraph",
    "may_apply_answers",
    "may_apply_decisions",
    "may_mutate_candidate_source_artifacts",
    "may_mutate_canonical_specs",
    "may_write_ontology_package",
    "may_accept_ontology_terms",
    "may_create_branch_or_commit",
    "may_open_pull_request",
    "may_execute_git_service_operation",
    "rerun_request_state_is_authority",
    "specgraph_execution_authority",
    "specgraph_artifact_authority",
    "ontology_authority",
    "git_service_authority",
    "canonical_mutations_allowed",
    "may_execute_specgraph_from_request",
    "may_run_make_target_from_request",
)
PRODUCT_CANDIDATE_APPROVAL_GATE_REPORT_KIND = (
    "platform_candidate_approval_intent_gate_report"
)
PRODUCT_CANDIDATE_APPROVAL_INTENT_STATE_KIND = (
    "specspace_idea_to_spec_candidate_approval_intent_state"
)
PRODUCT_CANDIDATE_APPROVAL_INTENT_ACTION = (
    "approve_candidate_for_promotion_review"
)
PRODUCT_CANDIDATE_APPROVAL_DECISION_KIND = "candidate_approval_decision"
PRODUCT_CANDIDATE_APPROVAL_DECISION_CONTRACT_REF = (
    "specgraph.idea-to-spec.candidate-approval-decision.v0.1"
)
PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS = {
    "approval_intents": "runs/idea_to_spec_candidate_approval_intents.json",
    "repair_session": "runs/idea_to_spec_repair_session.json",
    "promotion_gate": "runs/idea_to_spec_promotion_gate.json",
    "repair_execution": "runs/platform_product_repair_rerun_execution_report.json",
    "repair_publication": "runs/platform_product_repair_rerun_publication_report.json",
}
PRODUCT_CANDIDATE_APPROVAL_DEFAULT_OUTPUTS = {
    "gate": "runs/platform_candidate_approval_intent_gate_report.json",
    "decision": "runs/candidate_approval_decision.json",
}
PRODUCT_CANDIDATE_PROMOTION_DEFAULT_OUTPUTS = {
    "request": "runs/graph_repository_promotion_request.json",
    "execution": "runs/product_candidate_promotion_execution_report.json",
    "review_status": "runs/product_candidate_promotion_review_status_report.json",
    "read_model_publication": (
        "runs/product_candidate_promotion_read_model_publication_report.json"
    ),
}
PRODUCT_CANDIDATE_PROMOTION_EXECUTION_REPORT_KIND = (
    "platform_product_candidate_promotion_execution_report"
)
PRODUCT_CANDIDATE_PROMOTION_REVIEW_STATUS_REPORT_KIND = (
    "platform_product_candidate_promotion_review_status_report"
)
PRODUCT_CANDIDATE_PROMOTION_READ_MODEL_PUBLICATION_REPORT_KIND = (
    "platform_product_candidate_promotion_read_model_publication_report"
)
PRODUCT_CANDIDATE_PROMOTION_REQUEST_AUTHORITY_FALSE_FIELDS = (
    "executes_git_commands",
    "creates_commits",
    "opens_pull_requests",
    "merges_pull_requests",
    "writes_ontology_packages",
    "mutates_canonical_specs",
    "publishes_read_models",
)
PRODUCT_CANDIDATE_APPROVAL_FALSE_TOP_LEVEL_FIELDS = (
    "canonical_mutations_allowed",
    "ontology_writes_allowed",
    "tracked_artifacts_written",
)
PRODUCT_CANDIDATE_APPROVAL_CONSUMER_FALSE_FIELDS = (
    "may_execute_specgraph",
    "may_execute_prompt_agent",
    "may_apply_to_specgraph",
    "may_mutate_candidate_source_artifacts",
    "may_mutate_canonical_specs",
    "may_write_ontology_package",
    "may_accept_ontology_terms",
    "may_mark_candidate_accepted",
    "may_mark_candidate_graph_accepted",
    "may_create_branch_or_commit",
    "may_open_pull_request",
    "may_execute_git_service_operation",
)
PRODUCT_CANDIDATE_APPROVAL_AUTHORITY_FALSE_FIELDS = (
    "approval_intent_state_is_authority",
    "candidate_approval_intent_state_is_authority",
    "candidate_approval_authority",
    "candidate_approval_decision_authority",
    "specgraph_execution_authority",
    "specgraph_artifact_authority",
    "ontology_authority",
    "git_service_authority",
    "canonical_mutations_allowed",
)
PRODUCT_CANDIDATE_APPROVAL_INTENT_FALSE_FIELDS = (
    *PRODUCT_CANDIDATE_APPROVAL_CONSUMER_FALSE_FIELDS,
    "canonical_mutations_allowed",
    "tracked_artifacts_written",
)
PRODUCT_CANDIDATE_APPROVAL_REPORT_AUTHORITY_FALSE_FIELDS = (
    "executes_specgraph_make_target",
    "executes_git_commands",
    "opens_pull_requests",
    "merges_pull_requests",
    "writes_ontology_packages",
    "accepts_ontology_terms",
    "mutates_canonical_specs",
    "publishes_private_artifacts",
)
PRODUCT_CANDIDATE_APPROVAL_BOUNDARY = {
    "approval_intent_state_is_authority": False,
    "candidate_approval_decision_authority": False,
    "executes_specgraph_make_target": False,
    "executes_git_commands": False,
    "opens_pull_requests": False,
    "merges_pull_requests": False,
    "writes_ontology_packages": False,
    "accepts_ontology_terms": False,
    "mutates_canonical_specs": False,
    "publishes_private_artifacts": False,
    "may_execute_prompt_agent": False,
    "may_mutate_candidate_source_artifacts": False,
    "may_mutate_canonical_specs": False,
    "may_write_ontology_package": False,
    "may_write_ontology_lockfile": False,
    "may_mark_candidate_graph_accepted": False,
    "may_create_branch_or_commit": False,
    "may_open_pull_request": False,
    "may_publish_read_model": False,
    "git_service_promotion_started": False,
}
PRODUCT_CANDIDATE_PROMOTION_AUTHORITY_FALSE_FIELDS = (
    "may_execute_prompt_agent",
    "may_mutate_candidate_source_artifacts",
    "may_mutate_canonical_specs",
    "may_write_ontology_package",
    "may_write_ontology_lockfile",
    "may_mark_candidate_graph_accepted",
    "may_create_branch_or_commit",
    "may_open_pull_request",
    "may_publish_read_model",
    "may_execute_git_service_operation",
)
PRODUCT_CANDIDATE_PROMOTION_EXECUTION_AUTHORITY_FALSE_FIELDS = (
    "merges_pull_requests",
    "publishes_read_models",
    "canonical_spec_mutation_without_review",
    "ontology_package_write",
    "ontology_term_acceptance",
    "private_artifact_publication",
)
PRODUCT_CANDIDATE_PROMOTION_REVIEW_AUTHORITY_FALSE_FIELDS = (
    "specspace_direct_git_write",
    "executes_git_commands",
    "opens_pull_requests",
    "merges_pull_requests",
    "publishes_read_models",
    "canonical_spec_mutation_without_review",
    "ontology_package_write",
    "ontology_term_acceptance",
    "private_artifact_publication",
)
GIT_SERVICE_REQUIRED_OPERATIONS = {
    "prepare_worktree": {
        "adapter_command": "graph-repository prepare-worktree",
        "writes": {
            "candidate_ref": True,
            "review": False,
            "read_model": False,
        },
        "lock_scopes": {"candidate_ref"},
        "required_inputs": {
            "platform_graph_repository_promotion_request",
            "platform_graph_repository_execution_plan",
            "candidate_approval_decision",
        },
    },
    "commit_candidate": {
        "adapter_command": "graph-repository commit-worktree",
        "writes": {
            "candidate_ref": True,
            "review": False,
            "read_model": False,
        },
        "lock_scopes": {"candidate_ref"},
        "required_inputs": {
            "platform_graph_repository_worktree_prepare_report",
            "materialized_candidate_paths",
        },
    },
    "open_review": {
        "adapter_command": "graph-repository open-review",
        "writes": {
            "candidate_ref": True,
            "review": True,
            "read_model": False,
        },
        "lock_scopes": {"candidate_ref", "review_ref"},
        "required_inputs": {
            "platform_graph_repository_review_commit_report",
            "review_title",
            "review_body",
        },
    },
    "review_status": {
        "adapter_command": "graph-repository review-status",
        "writes": {
            "candidate_ref": False,
            "review": False,
            "read_model": False,
        },
        "lock_scopes": {"review_ref"},
        "required_inputs": {
            "platform_graph_repository_open_review_report",
        },
    },
    "publish_read_model": {
        "adapter_command": "graph-repository publish-read-model",
        "writes": {
            "candidate_ref": False,
            "review": False,
            "read_model": True,
        },
        "lock_scopes": {"read_model_publish"},
        "required_inputs": {
            "platform_graph_repository_review_status_report",
            "artifact_manifest",
        },
    },
}

GIT_SERVICE_REQUEST_REQUIRED_INPUTS = {
    "prepare_worktree": {
        "promotion_request",
        "execution_plan",
        "candidate_approval_decision",
    },
    "commit_candidate": {
        "worktree_prepare_report",
        "materialized_candidate_paths",
    },
    "open_review": {
        "review_commit_report",
        "review_title",
        "review_body",
    },
    "review_status": {
        "open_review_report",
    },
    "publish_read_model": {
        "review_status_report",
        "artifact_manifest",
    },
}


class PlatformError(Exception):
    """User-facing CLI error."""


@dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    subject: str
    message: str


@dataclass(frozen=True)
class ComposeInvocation:
    action: str
    compose_files: list[Path]
    env_file: Path | None
    project_name: str | None
    command: list[str]


@dataclass(frozen=True)
class DeployBundle:
    output_dir: Path
    compose_files: list[Path]
    env_example: Path | None
    manifest: Path
    command: list[str]


@dataclass(frozen=True)
class TimewebManifest:
    output_dir: Path
    compose_file: Path
    readme: Path
    manifest: Path


@dataclass(frozen=True)
class TimewebImageRefs:
    specspace_api_image_ref: str
    specspace_ui_image_ref: str
    image_lock: Path | None = None


@dataclass(frozen=True)
class TimewebHyperpromptRuntime:
    http_compile_enabled: bool
    work_dir: str
    compile_timeout_seconds: str
    max_input_bytes: str
    max_output_bytes: str
    bundle_retention_count: str


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise PlatformError(
            "PyYAML is required to read workspace catalogs. "
            "Install it with `python3 -m pip install PyYAML`."
        ) from exc

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        raise PlatformError(f"cannot read catalog {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise PlatformError(f"cannot parse catalog {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise PlatformError(f"catalog {path} must contain a YAML mapping")
    return data


def default_catalog_path() -> Path:
    env_path = os.environ.get("PLATFORM_WORKSPACES_CATALOG")
    if env_path:
        return Path(env_path)
    if DEFAULT_LOCAL_CATALOG.exists():
        return DEFAULT_LOCAL_CATALOG
    return DEFAULT_EXAMPLE_CATALOG


def catalog_workspaces(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    workspaces = catalog.get("workspaces")
    if not isinstance(workspaces, list):
        raise PlatformError("catalog must contain a `workspaces` list")

    normalized: list[dict[str, Any]] = []
    for index, workspace in enumerate(workspaces, start=1):
        if not isinstance(workspace, dict):
            raise PlatformError(f"workspace entry #{index} must be a mapping")
        normalized.append(workspace)
    return normalized


def catalog_registries(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    registries = catalog.get("registries", [])
    if registries is None:
        return []
    if not isinstance(registries, list):
        return []

    normalized: list[dict[str, Any]] = []
    for registry in registries:
        if isinstance(registry, dict):
            normalized.append(registry)
    return normalized


def catalog_workspace_mappings(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    workspaces = catalog.get("workspaces", [])
    if not isinstance(workspaces, list):
        return []
    return [workspace for workspace in workspaces if isinstance(workspace, dict)]


def workspace_row(workspace: dict[str, Any]) -> dict[str, str]:
    return {
        "project_id": str(workspace.get("project_id", "")),
        "display_name": str(workspace.get("display_name", "")),
        "kind": str(workspace.get("kind", "")),
        "status": str(workspace.get("status", "")),
        "governance_profile": str(workspace.get("governance_profile", "")),
        "path": str(workspace.get("path", "")),
    }


def filter_rows(
    rows: list[dict[str, str]],
    *,
    kind: str | None,
    status: str | None,
) -> list[dict[str, str]]:
    if kind is not None:
        rows = [row for row in rows if row["kind"] == kind]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return rows


def render_rows(rows: list[dict[str, str]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    widths = {
        key: max(len(label), *(len(row[key]) for row in rows))
        for key, label in columns
    }
    header = "  ".join(label.ljust(widths[key]) for key, label in columns)
    separator = "  ".join("-" * widths[key] for key, _label in columns)
    body = [
        "  ".join(row[key].ljust(widths[key]) for key, _label in columns)
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def render_workspace_table(rows: list[dict[str, str]]) -> str:
    columns = [
        ("project_id", "PROJECT"),
        ("kind", "KIND"),
        ("status", "STATUS"),
        ("governance_profile", "PROFILE"),
        ("path", "PATH"),
    ]
    return render_rows(rows, columns)


def diagnostic_row(diagnostic: Diagnostic) -> dict[str, str]:
    return {
        "level": diagnostic.level,
        "code": diagnostic.code,
        "subject": diagnostic.subject,
        "message": diagnostic.message,
    }


def render_diagnostic_table(diagnostics: list[Diagnostic]) -> str:
    rows = [diagnostic_row(diagnostic) for diagnostic in diagnostics]
    columns = [
        ("level", "LEVEL"),
        ("code", "CODE"),
        ("subject", "SUBJECT"),
        ("message", "MESSAGE"),
    ]
    return render_rows(rows, columns)


def schema_path_to_subject(path: Any) -> str:
    parts = [str(part) for part in path]
    if not parts:
        return "catalog"
    return ".".join(parts)


def import_jsonschema() -> Any:
    script_dir = Path(__file__).resolve().parent
    original_path = list(sys.path)
    sys.path[:] = [
        entry
        for entry in sys.path
        if not entry or Path(entry).resolve() != script_dir
    ]
    try:
        import jsonschema
    finally:
        sys.path[:] = original_path
    return jsonschema


def validate_catalog_schema(catalog: dict[str, Any]) -> list[Diagnostic]:
    try:
        jsonschema = import_jsonschema()
    except ImportError as exc:
        raise PlatformError(
            "jsonschema is required to run workspace doctor. "
            "Install it with `python3 -m pip install -r requirements-dev.txt`."
        ) from exc

    schema_path = REPO_ROOT / "schemas" / "workspace-catalog.schema.json"
    try:
        with schema_path.open("r", encoding="utf-8") as handle:
            schema = json.load(handle)
    except OSError as exc:
        raise PlatformError(f"cannot read schema {schema_path}: {exc}") from exc

    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    diagnostics: list[Diagnostic] = []
    for error in sorted(validator.iter_errors(catalog), key=lambda item: tuple(item.path)):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="catalog_schema_invalid",
                subject=schema_path_to_subject(error.absolute_path),
                message=error.message,
            )
        )
    return diagnostics


def duplicate_id_diagnostics(
    entries: list[dict[str, Any]],
    *,
    field: str,
    code: str,
    collection_name: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(entries):
        value = entry.get(field)
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code=code,
                    subject=f"{collection_name}[{index}].{field}",
                    message=(
                        f"duplicate {field} `{value}`; first seen at "
                        f"{collection_name}[{seen[value]}]"
                    ),
                )
            )
        else:
            seen[value] = index
    return diagnostics


def load_json_mapping(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlatformError(f"cannot read {label} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PlatformError(f"cannot parse {label} {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PlatformError(f"{label} {path} must contain a JSON object")
    return data


def validate_json_schema(
    payload: dict[str, Any],
    *,
    schema_path: Path,
    code: str,
) -> list[Diagnostic]:
    try:
        jsonschema = import_jsonschema()
    except ImportError as exc:
        raise PlatformError(
            "jsonschema is required to validate contracts. "
            "Install it with `python3 -m pip install -r requirements-dev.txt`."
        ) from exc

    try:
        schema = load_json_mapping(schema_path, label="schema")
    except PlatformError:
        raise

    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    return [
        Diagnostic(
            level="ERROR",
            code=code,
            subject=schema_path_to_subject(error.absolute_path),
            message=error.message,
        )
        for error in sorted(validator.iter_errors(payload), key=lambda item: tuple(item.path))
    ]


def validate_graph_repository_contract_schema(
    contract: dict[str, Any],
) -> list[Diagnostic]:
    return validate_json_schema(
        contract,
        schema_path=REPO_ROOT / "schemas" / "graph-repository-service-contract.schema.json",
        code="graph_repository_contract_schema_invalid",
    )


def graph_repository_contract_semantic_diagnostics(
    contract: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    promotion_policy = contract.get("promotion_policy")
    if isinstance(promotion_policy, dict) and promotion_policy.get("auto_merge_allowed") is True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_auto_merge_not_allowed",
                subject="promotion_policy.auto_merge_allowed",
                message="auto-merge is outside the MVP graph repository authority boundary",
            )
        )

    supported_operations = contract.get("supported_operations")
    if isinstance(supported_operations, list):
        operations = {
            item.get("name")
            for item in supported_operations
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        required = {
            "create_candidate_workspace",
            "validate_candidate_graph",
            "prepare_branch",
            "create_commit",
            "open_review",
            "publish_read_model",
        }
        missing = sorted(required - operations)
        if missing:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_operation_missing",
                    subject="supported_operations",
                    message=f"missing required operations: {', '.join(missing)}",
                )
            )
        expected_canonical_writes = {
            "create_candidate_workspace": False,
            "validate_candidate_graph": False,
            "prepare_branch": False,
            "create_commit": True,
            "open_review": False,
            "publish_read_model": False,
        }
        for index, item in enumerate(supported_operations):
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or name not in expected_canonical_writes:
                continue
            expected = expected_canonical_writes[name]
            if item.get("writes_canonical_store") != expected:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="graph_repository_operation_canonical_write_mismatch",
                        subject=f"supported_operations[{index}].writes_canonical_store",
                        message=(
                            f"operation `{name}` must set writes_canonical_store "
                            f"to {str(expected).lower()}"
                        ),
                    )
                )

    validation_gates = contract.get("validation_gates")
    if isinstance(validation_gates, dict):
        for key in (
            "required_before_branch",
            "required_before_commit",
            "required_before_publish",
        ):
            value = validation_gates.get(key)
            if isinstance(value, list) and not value:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="graph_repository_validation_gate_empty",
                        subject=f"validation_gates.{key}",
                        message="validation gate lists must not be empty",
                    )
                )
        required_before_branch = validation_gates.get("required_before_branch")
        if (
            isinstance(required_before_branch, list)
            and "idea_to_spec_repair_session" not in required_before_branch
        ):
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_repair_session_gate_missing",
                    subject="validation_gates.required_before_branch",
                    message=(
                        "required_before_branch must include "
                        "`idea_to_spec_repair_session`"
                    ),
                )
            )

    authority_boundary = contract.get("authority_boundary")
    if isinstance(authority_boundary, dict):
        for key, value in sorted(authority_boundary.items()):
            if value is True:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="graph_repository_authority_expanded",
                        subject=f"authority_boundary.{key}",
                        message="authority boundary flags must remain false in the MVP contract",
                    )
                )
    return diagnostics


def graph_repository_validate(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract)
    contract = load_json_mapping(contract_path, label="graph repository contract")
    diagnostics = [
        *validate_graph_repository_contract_schema(contract),
        *graph_repository_contract_semantic_diagnostics(contract),
    ]
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    payload = {
        "contract": str(contract_path),
        "ok": error_count == 0,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "operation_count": len(contract.get("supported_operations", []))
            if isinstance(contract.get("supported_operations"), list)
            else 0,
        },
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print("OK: graph repository service contract is valid")
    return 0 if error_count == 0 else 1


def validate_git_service_operation_contract_schema(
    contract: dict[str, Any],
) -> list[Diagnostic]:
    return validate_json_schema(
        contract,
        schema_path=REPO_ROOT
        / "schemas"
        / "git-service-operation-contract.schema.json",
        code="git_service_operation_contract_schema_invalid",
    )


def validate_git_service_operation_request_schema(
    request: dict[str, Any],
) -> list[Diagnostic]:
    return validate_json_schema(
        request,
        schema_path=REPO_ROOT / "schemas" / "git-service-operation-request.schema.json",
        code="git_service_operation_request_schema_invalid",
    )


def validate_git_service_operation_response_schema(
    response: dict[str, Any],
) -> list[Diagnostic]:
    return validate_json_schema(
        response,
        schema_path=REPO_ROOT
        / "schemas"
        / "git-service-operation-response.schema.json",
        code="git_service_operation_response_schema_invalid",
    )


def validate_deployment_profile_schema(profile: dict[str, Any]) -> list[Diagnostic]:
    return validate_json_schema(
        profile,
        schema_path=REPO_ROOT / "schemas" / "deployment-profile.schema.json",
        code="deployment_profile_schema_invalid",
    )


def deployment_profile_list(profile: dict[str, Any], section: str, key: str) -> list[str]:
    container = profile.get(section)
    if not isinstance(container, dict):
        return []
    return [item for item in container.get(key, []) if isinstance(item, str)]


def deployment_profile_semantic_diagnostics(
    profile: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    profile_id = str(profile.get("profile_id") or "")
    workflow_lane = str(profile.get("workflow_lane") or "")
    authority_profile = str(profile.get("authority_profile") or "")
    git_service = nested_mapping(profile, "git_service")
    authority_boundary = nested_mapping(profile, "authority_boundary")
    mode = str(git_service.get("mode") or "")

    if mode == "controlled_promotion" and authority_boundary.get(
        "permits_git_service_write"
    ) is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_git_service_write_boundary_mismatch",
                subject="authority_boundary.permits_git_service_write",
                message=(
                    "controlled_promotion profiles must explicitly permit Git "
                    "Service writes"
                ),
            )
        )
    if mode in {"disabled", "dry_run_only"} and authority_boundary.get(
        "permits_git_service_write"
    ) is True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_git_service_write_boundary_mismatch",
                subject="authority_boundary.permits_git_service_write",
                message="non-write Git Service profiles must not permit Git Service writes",
            )
        )

    allowed_lanes = deployment_profile_list(
        profile, "git_service", "allowed_workflow_lanes"
    )
    denied_lanes = deployment_profile_list(
        profile, "git_service", "denied_workflow_lanes"
    )
    if workflow_lane and allowed_lanes and workflow_lane not in allowed_lanes:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_workflow_lane_not_allowed",
                subject="git_service.allowed_workflow_lanes",
                message="profile workflow_lane must be allowed by its Git Service policy",
            )
        )
    if workflow_lane and workflow_lane in denied_lanes:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_workflow_lane_denied",
                subject="git_service.denied_workflow_lanes",
                message="profile workflow_lane must not be denied by its Git Service policy",
            )
        )

    allowed_authorities = deployment_profile_list(
        profile, "git_service", "allowed_authority_profiles"
    )
    denied_authorities = deployment_profile_list(
        profile, "git_service", "denied_authority_profiles"
    )
    if (
        authority_profile
        and allowed_authorities
        and authority_profile not in allowed_authorities
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_authority_profile_not_allowed",
                subject="git_service.allowed_authority_profiles",
                message=(
                    "profile authority_profile must be allowed by its Git "
                    "Service policy"
                ),
            )
        )
    if authority_profile and authority_profile in denied_authorities:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_authority_profile_denied",
                subject="git_service.denied_authority_profiles",
                message=(
                    "profile authority_profile must not be denied by its Git "
                    "Service policy"
                ),
            )
        )

    exposes = {item for item in profile.get("exposes", []) if isinstance(item, str)}
    hides = {item for item in profile.get("hides", []) if isinstance(item, str)}
    if profile_id == "product_idea_to_spec_workbench":
        required_hides = {
            "specgraph_bootstrap",
            "supervisor_self_evolution",
            "local_operator_diagnostics",
        }
        missing_hides = sorted(required_hides - hides)
        if missing_hides:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="deployment_profile_product_surface_leaks_bootstrap",
                    subject="hides",
                    message=(
                        "product idea-to-spec profile must hide bootstrap surfaces: "
                        + ", ".join(missing_hides)
                    ),
                )
            )
        if authority_boundary.get("exposes_bootstrap_surfaces") is True:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="deployment_profile_product_exposes_bootstrap",
                    subject="authority_boundary.exposes_bootstrap_surfaces",
                    message="product idea-to-spec profile must not expose bootstrap surfaces",
                )
            )
        allowed_roles = set(
            deployment_profile_list(
                profile, "git_service", "allowed_target_repository_roles"
            )
        )
        expected_allowed_roles = {"product_spec_workspace"}
        if allowed_roles != expected_allowed_roles:
            code = (
                "deployment_profile_product_repository_role_missing"
                if "product_spec_workspace" not in allowed_roles
                else "deployment_profile_product_repository_role_expanded"
            )
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code=code,
                    subject="git_service.allowed_target_repository_roles",
                    message=(
                        "product idea-to-spec profile must allow exactly "
                        "product_spec_workspace promotion targets"
                    ),
                )
            )
    if profile_id == "specgraph_bootstrap_internal":
        if mode == "controlled_promotion":
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="deployment_profile_bootstrap_git_service_write_enabled",
                    subject="git_service.mode",
                    message=(
                        "bootstrap internal profile must not enable Git Service "
                        "controlled promotion writes"
                    ),
                )
            )
        if "specgraph_bootstrap" not in exposes:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="deployment_profile_bootstrap_surface_missing",
                    subject="exposes",
                    message="bootstrap internal profile must expose specgraph_bootstrap",
                )
            )
    return diagnostics


def deployment_profile_validate(args: argparse.Namespace) -> int:
    profile_path = Path(args.profile)
    profile = load_json_mapping(profile_path, label="deployment profile")
    diagnostics = [
        *validate_deployment_profile_schema(profile),
        *deployment_profile_semantic_diagnostics(profile),
    ]
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    payload = {
        "profile": str(profile_path),
        "ok": error_count == 0,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "profile_id": profile.get("profile_id"),
            "workflow_lane": profile.get("workflow_lane"),
            "git_service_mode": nested_mapping(profile, "git_service").get("mode"),
        },
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print("OK: deployment profile is valid")
    return 0 if error_count == 0 else 1


def request_field_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def git_service_deployment_profile_diagnostics(
    *,
    profile: dict[str, Any],
    promotion_request: dict[str, Any],
    dry_run: bool,
) -> list[Diagnostic]:
    diagnostics = [
        *validate_deployment_profile_schema(profile),
        *deployment_profile_semantic_diagnostics(profile),
    ]
    git_service = nested_mapping(profile, "git_service")
    mode = str(git_service.get("mode") or "")
    profile_id = str(profile.get("profile_id") or "")
    request_profile_id = request_field_text(promotion_request, "deployment_profile_id")
    if request_profile_id != profile_id:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_request_profile_mismatch",
                subject="promotion_request.deployment_profile_id",
                message=(
                    "promotion request deployment_profile_id must match the "
                    "active deployment profile"
                ),
            )
        )

    if mode == "disabled":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_git_service_disabled",
                subject="deployment_profile.git_service.mode",
                message="Git Service is disabled for this deployment profile",
            )
        )
    elif mode == "dry_run_only" and not dry_run:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_git_service_dry_run_only",
                subject="deployment_profile.git_service.mode",
                message=(
                    "this deployment profile allows Git Service dry-run planning "
                    "only"
                ),
            )
        )
    elif mode != "controlled_promotion" and not (mode == "dry_run_only" and dry_run):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="deployment_profile_git_service_mode_unsupported",
                subject="deployment_profile.git_service.mode",
                message="unsupported Git Service deployment profile mode",
            )
        )

    required_fields = [
        item
        for item in git_service.get("required_promotion_request_fields", [])
        if isinstance(item, str)
    ]
    for field in required_fields:
        if not request_field_text(promotion_request, field):
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="deployment_profile_promotion_request_field_missing",
                    subject=f"promotion_request.{field}",
                    message="promotion request is missing a deployment profile field",
                )
            )

    field_specs = [
        (
            "workflow_lane",
            "allowed_workflow_lanes",
            "denied_workflow_lanes",
            "deployment_profile_workflow_lane_not_allowed",
            "deployment_profile_workflow_lane_denied",
        ),
        (
            "target_repository_role",
            "allowed_target_repository_roles",
            "denied_target_repository_roles",
            "deployment_profile_target_repository_role_not_allowed",
            "deployment_profile_target_repository_role_denied",
        ),
        (
            "authority_profile",
            "allowed_authority_profiles",
            "denied_authority_profiles",
            "deployment_profile_authority_profile_not_allowed",
            "deployment_profile_authority_profile_denied",
        ),
    ]
    for field, allowed_key, denied_key, not_allowed_code, denied_code in field_specs:
        value = request_field_text(promotion_request, field)
        if not value:
            continue
        allowed = deployment_profile_list(profile, "git_service", allowed_key)
        denied = deployment_profile_list(profile, "git_service", denied_key)
        if allowed and value not in allowed:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code=not_allowed_code,
                    subject=f"promotion_request.{field}",
                    message=f"{field} is not allowed by the deployment profile",
                )
            )
        if value in denied:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code=denied_code,
                    subject=f"promotion_request.{field}",
                    message=f"{field} is denied by the deployment profile",
                )
            )
    return diagnostics


def git_service_operation_contract_semantic_diagnostics(
    contract: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    operations = contract.get("operations")
    operation_by_name: dict[str, tuple[int, dict[str, Any]]] = {}
    if isinstance(operations, list):
        for index, item in enumerate(operations):
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str):
                continue
            if name in operation_by_name:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="git_service_operation_duplicate",
                        subject=f"operations[{index}].name",
                        message=f"duplicate operation `{name}`",
                    )
                )
            operation_by_name[name] = (index, item)

    missing = sorted(set(GIT_SERVICE_REQUIRED_OPERATIONS) - set(operation_by_name))
    if missing:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_operation_missing",
                subject="operations",
                message=f"missing required operations: {', '.join(missing)}",
            )
        )

    extra = sorted(set(operation_by_name) - set(GIT_SERVICE_REQUIRED_OPERATIONS))
    if extra:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_operation_unknown",
                subject="operations",
                message=f"unknown operations: {', '.join(extra)}",
            )
        )

    for name, expected in GIT_SERVICE_REQUIRED_OPERATIONS.items():
        entry = operation_by_name.get(name)
        if entry is None:
            continue
        index, operation = entry
        if operation.get("adapter_command") != expected["adapter_command"]:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_adapter_command_mismatch",
                    subject=f"operations[{index}].adapter_command",
                    message=(
                        f"operation `{name}` must use adapter command "
                        f"`{expected['adapter_command']}`"
                    ),
                )
            )
        writes = operation.get("writes")
        if isinstance(writes, dict):
            for field, expected_value in expected["writes"].items():
                if writes.get(field) != expected_value:
                    diagnostics.append(
                        Diagnostic(
                            level="ERROR",
                            code="git_service_write_boundary_mismatch",
                            subject=f"operations[{index}].writes.{field}",
                            message=(
                                f"operation `{name}` must set writes.{field} to "
                                f"{str(expected_value).lower()}"
                            ),
                        )
                    )
        lock_scopes = operation.get("lock_scopes")
        if isinstance(lock_scopes, list):
            missing_scopes = sorted(expected["lock_scopes"] - set(lock_scopes))
            if missing_scopes:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="git_service_lock_scope_missing",
                        subject=f"operations[{index}].lock_scopes",
                        message=(
                            f"operation `{name}` is missing lock scopes: "
                            f"{', '.join(missing_scopes)}"
                        ),
                    )
                )
        required_inputs = operation.get("required_inputs")
        if isinstance(required_inputs, list):
            missing_inputs = sorted(
                expected["required_inputs"] - set(required_inputs)
            )
            if missing_inputs:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="git_service_required_input_missing",
                        subject=f"operations[{index}].required_inputs",
                        message=(
                            f"operation `{name}` is missing required inputs: "
                            f"{', '.join(missing_inputs)}"
                        ),
                    )
                )

    repository_binding = contract.get("repository_binding")
    ref_ownership = contract.get("ref_ownership")
    if isinstance(repository_binding, dict) and isinstance(ref_ownership, dict):
        branch_prefix = repository_binding.get("candidate_branch_prefix")
        ref_prefix = ref_ownership.get("candidate_ref_prefix")
        if branch_prefix != ref_prefix:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_candidate_ref_prefix_mismatch",
                    subject="ref_ownership.candidate_ref_prefix",
                    message=(
                        "ref_ownership.candidate_ref_prefix must match "
                        "repository_binding.candidate_branch_prefix"
                    ),
                )
            )

    audit = contract.get("audit")
    if isinstance(audit, dict):
        required_fields = audit.get("required_fields")
        if isinstance(required_fields, list):
            required_audit_fields = {
                "event_id",
                "operation",
                "request_id",
                "actor_ref",
                "repository_ref",
                "candidate_id",
                "created_at",
                "status",
            }
            missing_audit_fields = sorted(required_audit_fields - set(required_fields))
            if missing_audit_fields:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="git_service_audit_field_missing",
                        subject="audit.required_fields",
                        message=(
                            "missing required audit fields: "
                            f"{', '.join(missing_audit_fields)}"
                        ),
                    )
                )

    authority_boundary = contract.get("authority_boundary")
    if isinstance(authority_boundary, dict):
        for key, value in sorted(authority_boundary.items()):
            if value is True:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="git_service_authority_expanded",
                        subject=f"authority_boundary.{key}",
                        message="authority boundary flags must remain false",
                    )
                )
    return diagnostics


def git_service_operation_request_semantic_diagnostics(
    request: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    operation = str(request.get("operation") or "")
    required_inputs = GIT_SERVICE_REQUEST_REQUIRED_INPUTS.get(operation)
    inputs = request.get("inputs")
    if not required_inputs or not isinstance(inputs, dict):
        return diagnostics
    missing_inputs = sorted(
        key
        for key in required_inputs
        if not isinstance(inputs.get(key), str) or not inputs.get(key).strip()
    )
    if missing_inputs:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_operation_request_input_missing",
                subject="inputs",
                message=(
                    f"operation `{operation}` is missing required inputs: "
                    f"{', '.join(missing_inputs)}"
                ),
            )
        )
    return diagnostics


def git_service_validate_contract(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract)
    contract = load_json_mapping(contract_path, label="git service contract")
    diagnostics = [
        *validate_git_service_operation_contract_schema(contract),
        *git_service_operation_contract_semantic_diagnostics(contract),
    ]
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    payload = {
        "contract": str(contract_path),
        "ok": error_count == 0,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "operation_count": len(contract.get("operations", []))
            if isinstance(contract.get("operations"), list)
            else 0,
        },
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print("OK: git service operation contract is valid")
    return 0 if error_count == 0 else 1


def git_service_validate_operation_payload(
    *,
    path: Path,
    label: str,
    validator: Any,
    success_message: str,
    args: argparse.Namespace,
) -> int:
    payload_data = load_json_mapping(path, label=label)
    diagnostics = validator(payload_data)
    if label == "git service request":
        diagnostics = [
            *diagnostics,
            *git_service_operation_request_semantic_diagnostics(payload_data),
        ]
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    output = {
        "path": str(path),
        "ok": error_count == 0,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "operation": payload_data.get("operation"),
        },
    }
    if args.format == "json":
        print(json.dumps(output, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(success_message)
    return 0 if error_count == 0 else 1


def git_service_validate_request(args: argparse.Namespace) -> int:
    return git_service_validate_operation_payload(
        path=Path(args.request),
        label="git service request",
        validator=validate_git_service_operation_request_schema,
        success_message="OK: git service operation request is valid",
        args=args,
    )


def git_service_validate_response(args: argparse.Namespace) -> int:
    return git_service_validate_operation_payload(
        path=Path(args.response),
        label="git service response",
        validator=validate_git_service_operation_response_schema,
        success_message="OK: git service operation response is valid",
        args=args,
    )


def resolve_artifact_path(raw_ref: Any, *, base_dir: Path) -> Path | None:
    if not isinstance(raw_ref, str) or not raw_ref.strip():
        return None
    raw_path = Path(raw_ref)
    candidates = [raw_path]
    if not raw_path.is_absolute():
        candidates.extend([base_dir / raw_path, REPO_ROOT / raw_path])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def git_service_promotion_request_diagnostics(
    *,
    contract: dict[str, Any],
    promotion_request: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics = [
        *validate_git_service_operation_contract_schema(contract),
        *git_service_operation_contract_semantic_diagnostics(contract),
    ]
    if promotion_request.get("artifact_kind") != "platform_graph_repository_promotion_request":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_promotion_request_kind_mismatch",
                subject="promotion_request.artifact_kind",
                message="expected platform_graph_repository_promotion_request",
            )
        )
    if promotion_request.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_promotion_request_not_ok",
                subject="promotion_request.ok",
                message="promotion request must be ok before Git Service execution",
            )
        )
    for field in ("canonical_mutations_allowed", "tracked_artifacts_written"):
        if promotion_request.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_promotion_request_authority_expanded",
                    subject=f"promotion_request.{field}",
                    message=f"{field} must be false before Git Service execution",
                )
            )
    authority_boundary = nested_mapping(promotion_request, "authority_boundary")
    for key, value in sorted(authority_boundary.items()):
        if value is True:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_promotion_request_authority_expanded",
                    subject=f"promotion_request.authority_boundary.{key}",
                    message="promotion request must not execute write actions itself",
                )
            )
    commit_paths = promotion_request.get("commit_paths")
    if not isinstance(commit_paths, list) or not commit_paths:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_promotion_paths_missing",
                subject="promotion_request.commit_paths",
                message="promotion request must include at least one commit path",
            )
        )
    elif graph_repository_relative_paths_diagnostics(
        [path for path in commit_paths if isinstance(path, str)]
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_promotion_paths_invalid",
                subject="promotion_request.commit_paths",
                message="promotion request commit paths must be relative safe paths",
            )
        )
    requested_operations = promotion_request.get("requested_operations")
    if isinstance(requested_operations, list):
        expected = ["prepare_branch", "create_commit", "open_review"]
        missing = [operation for operation in expected if operation not in requested_operations]
        if missing:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_requested_operation_missing",
                    subject="promotion_request.requested_operations",
                    message=f"promotion request is missing operations: {', '.join(missing)}",
                )
            )
    return diagnostics


def git_service_candidate_approval_diagnostics(
    *,
    approval_decision: dict[str, Any],
    promotion_request: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if approval_decision.get("artifact_kind") != "candidate_approval_decision":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_candidate_approval_kind_mismatch",
                subject="approval_decision.artifact_kind",
                message="expected candidate_approval_decision",
            )
        )
    if approval_decision.get("contract_ref") != (
        "specgraph.idea-to-spec.candidate-approval-decision.v0.1"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_candidate_approval_contract_mismatch",
                subject="approval_decision.contract_ref",
                message="expected candidate approval decision contract v0.1",
            )
        )
    for field in (
        "canonical_mutations_allowed",
        "ontology_writes_allowed",
        "tracked_artifacts_written",
    ):
        if approval_decision.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_candidate_approval_authority_expanded",
                    subject=f"approval_decision.{field}",
                    message=f"{field} must be false before Git Service execution",
                )
            )
    for key, value in sorted(
        nested_mapping(approval_decision, "authority_boundary").items()
    ):
        if value is True:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_candidate_approval_authority_expanded",
                    subject=f"approval_decision.authority_boundary.{key}",
                    message="candidate approval must not execute write actions itself",
                )
            )

    decision = nested_mapping(approval_decision, "decision")
    if decision.get("state") != "approved":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_candidate_approval_not_approved",
                subject="approval_decision.decision.state",
                message="Git Service execution requires an explicit approved decision",
            )
        )
    readiness = nested_mapping(approval_decision, "readiness")
    if readiness.get("ready") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_candidate_approval_not_ready",
                subject="approval_decision.readiness.ready",
                message="candidate approval decision must be ready before Git Service execution",
            )
        )

    candidate = nested_mapping(approval_decision, "candidate")
    if candidate.get("candidate_id") != promotion_request.get("candidate_id"):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_candidate_approval_candidate_mismatch",
                subject="approval_decision.candidate.candidate_id",
                message="candidate approval must reference the promotion request candidate",
            )
        )
    workspace = nested_mapping(approval_decision, "workspace")
    if workspace.get("mode") != promotion_request.get("workflow_lane"):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_candidate_approval_workflow_mismatch",
                subject="approval_decision.workspace.mode",
                message="candidate approval workflow lane must match the promotion request",
            )
        )
    if workspace.get("repository_role") != promotion_request.get(
        "target_repository_role"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_candidate_approval_repository_role_mismatch",
                subject="approval_decision.workspace.repository_role",
                message=(
                    "candidate approval repository role must match the promotion request"
                ),
            )
        )

    approved_paths = nested_mapping(approval_decision, "promotion_request").get("paths")
    request_paths = promotion_request.get("commit_paths")
    if not isinstance(approved_paths, list) or not approved_paths:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_candidate_approval_paths_missing",
                subject="approval_decision.promotion_request.paths",
                message="candidate approval must include approved promotion paths",
            )
        )
    elif approved_paths != request_paths:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_candidate_approval_paths_mismatch",
                subject="approval_decision.promotion_request.paths",
                message="candidate approval paths must match promotion request commit paths",
            )
        )
    return diagnostics


def run_platform_json_command(command: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any], Diagnostic | None]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *command],
        check=False,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result = {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }
    payload: dict[str, Any] | None = None
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = None
    if completed.returncode == 0 and payload is not None:
        return payload, result, None
    code = "git_service_adapter_command_failed"
    message = (
        f"adapter command failed with exit code {completed.returncode}: "
        f"{' '.join(command)}"
    )
    if completed.returncode == 0 and payload is None:
        code = "git_service_adapter_json_invalid"
        message = f"adapter command did not return a JSON object: {' '.join(command)}"
    return payload, result, Diagnostic(
        level="ERROR",
        code=code,
        subject=command[0] if command else "adapter_command",
        message=message,
    )


def git_service_operation_record(
    *,
    name: str,
    status: str,
    request_artifact_kind: str,
    response_artifact_kind: str,
    report_ref: str | None = None,
    adapter_command: list[str] | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "request_artifact_kind": request_artifact_kind,
        "response_artifact_kind": response_artifact_kind,
        "report_ref": report_ref,
        "adapter_command": adapter_command or [],
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics or []],
    }


def git_service_copy_materialized_paths(
    *,
    source_dir: Path | None,
    worktree_dir: Path,
    paths: list[str],
) -> tuple[list[dict[str, str]], list[Diagnostic]]:
    if source_dir is None:
        return [], []
    diagnostics: list[Diagnostic] = []
    copied: list[dict[str, str]] = []
    for index, raw_path in enumerate(paths):
        if Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_materialized_path_invalid",
                    subject=f"commit_paths[{index}]",
                    message="materialized path must be relative and stay inside worktree",
                )
            )
            continue
        source_path = source_dir / raw_path
        target_path = worktree_dir / raw_path
        if not source_path.is_file():
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_materialized_source_missing",
                    subject=f"materialized_source_dir/{raw_path}",
                    message="materialized source file is missing",
                )
            )
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied.append({"source": str(source_path), "target": str(target_path)})
    return copied, diagnostics


def git_service_execute_promotion(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract)
    promotion_request_path = Path(args.promotion_request)
    approval_decision_path = Path(args.approval_decision)
    repository_dir = Path(args.repository_dir).resolve()
    workspace_dir = Path(args.workspace_dir).resolve()
    materialized_source_dir = (
        Path(args.materialized_source_dir).resolve()
        if args.materialized_source_dir
        else None
    )
    contract = load_json_mapping(contract_path, label="git service contract")
    promotion_request = load_json_mapping(
        promotion_request_path,
        label="graph repository promotion request",
    )
    approval_decision = load_json_mapping(
        approval_decision_path,
        label="candidate approval decision",
    )
    deployment_profile_path = Path(args.deployment_profile)
    deployment_profile = load_json_mapping(
        deployment_profile_path,
        label="deployment profile",
    )
    diagnostics = git_service_promotion_request_diagnostics(
        contract=contract,
        promotion_request=promotion_request,
    )
    diagnostics.extend(
        git_service_candidate_approval_diagnostics(
            approval_decision=approval_decision,
            promotion_request=promotion_request,
        )
    )
    diagnostics.extend(
        git_service_deployment_profile_diagnostics(
            profile=deployment_profile,
            promotion_request=promotion_request,
            dry_run=args.dry_run,
        )
    )
    plan_path = resolve_artifact_path(
        promotion_request.get("plan_ref"),
        base_dir=promotion_request_path.parent,
    )
    if plan_path is None or not plan_path.is_file():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="git_service_plan_missing",
                subject="promotion_request.plan_ref",
                message="promotion request plan_ref must point at an execution plan",
            )
        )

    candidate_id = str(promotion_request.get("candidate_id") or "")
    review = nested_mapping(promotion_request, "review")
    commit_paths = [
        path for path in promotion_request.get("commit_paths", []) if isinstance(path, str)
    ]
    base_branch = str(review.get("base_branch") or "main")
    review_title = str(review.get("title") or "")
    review_body = str(review.get("body") or "")
    commit_message = args.message or review_title or f"Promote {candidate_id}"
    operation_records: list[dict[str, Any]] = []
    command_results: list[dict[str, Any]] = []
    copied_files: list[dict[str, str]] = []
    report_refs: dict[str, str] = {}

    preflight_error_count = sum(
        1 for diagnostic in diagnostics if diagnostic.level == "ERROR"
    )
    if preflight_error_count == 0 and args.dry_run:
        operation_records.extend(
            [
                git_service_operation_record(
                    name="prepare_worktree",
                    status="dry_run",
                    request_artifact_kind="platform_git_service_prepare_worktree_request",
                    response_artifact_kind="platform_git_service_prepare_worktree_response",
                ),
                git_service_operation_record(
                    name="commit_candidate",
                    status="skipped_dry_run",
                    request_artifact_kind="platform_git_service_commit_candidate_request",
                    response_artifact_kind="platform_git_service_commit_candidate_response",
                ),
                git_service_operation_record(
                    name="open_review",
                    status="skipped_dry_run",
                    request_artifact_kind="platform_git_service_open_review_request",
                    response_artifact_kind="platform_git_service_open_review_response",
                ),
            ]
        )
    elif preflight_error_count == 0:
        prepare_command = [
            "graph-repository",
            "prepare-worktree",
            "--plan",
            str(plan_path),
            "--repository-dir",
            str(repository_dir),
            "--candidate-id",
            candidate_id,
            "--workspace-dir",
            str(workspace_dir),
            "--format",
            "json",
        ]
        prepare_payload, prepare_result, prepare_diagnostic = run_platform_json_command(
            prepare_command
        )
        command_results.append(prepare_result)
        if prepare_diagnostic is not None:
            diagnostics.append(prepare_diagnostic)
        prepare_ok = prepare_payload is not None and prepare_payload.get("ok") is True
        prepare_report = (
            workspace_dir
            / ".platform"
            / "graph_repository_worktree_prepare_report.json"
        )
        if prepare_ok:
            report_refs["prepare_worktree"] = str(prepare_report)
        operation_records.append(
            git_service_operation_record(
                name="prepare_worktree",
                status="succeeded" if prepare_ok else "failed",
                request_artifact_kind="platform_git_service_prepare_worktree_request",
                response_artifact_kind="platform_git_service_prepare_worktree_response",
                report_ref=str(prepare_report) if prepare_ok else None,
                adapter_command=prepare_command,
                diagnostics=[prepare_diagnostic] if prepare_diagnostic else [],
            )
        )

        if prepare_ok:
            copied_files, copy_diagnostics = git_service_copy_materialized_paths(
                source_dir=materialized_source_dir,
                worktree_dir=workspace_dir,
                paths=commit_paths,
            )
            diagnostics.extend(copy_diagnostics)
            if copy_diagnostics:
                operation_records.append(
                    git_service_operation_record(
                        name="commit_candidate",
                        status="failed",
                        request_artifact_kind="platform_git_service_commit_candidate_request",
                        response_artifact_kind="platform_git_service_commit_candidate_response",
                        diagnostics=copy_diagnostics,
                    )
                )
            else:
                commit_command = [
                    "graph-repository",
                    "commit-worktree",
                    "--prepare-report",
                    str(prepare_report),
                    "--worktree-dir",
                    str(workspace_dir),
                    "--message",
                    commit_message,
                    "--format",
                    "json",
                ]
                for path in commit_paths:
                    commit_command.extend(["--path", path])
                commit_payload, commit_result, commit_diagnostic = (
                    run_platform_json_command(commit_command)
                )
                command_results.append(commit_result)
                if commit_diagnostic is not None:
                    diagnostics.append(commit_diagnostic)
                commit_ok = (
                    commit_payload is not None and commit_payload.get("ok") is True
                )
                commit_report = (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_review_commit_report.json"
                )
                if commit_ok:
                    report_refs["commit_candidate"] = str(commit_report)
                operation_records.append(
                    git_service_operation_record(
                        name="commit_candidate",
                        status="succeeded" if commit_ok else "failed",
                        request_artifact_kind="platform_git_service_commit_candidate_request",
                        response_artifact_kind="platform_git_service_commit_candidate_response",
                        report_ref=str(commit_report) if commit_ok else None,
                        adapter_command=commit_command,
                        diagnostics=[commit_diagnostic] if commit_diagnostic else [],
                    )
                )

                if commit_ok:
                    open_review_command = [
                        "graph-repository",
                        "open-review",
                        "--commit-report",
                        str(commit_report),
                        "--worktree-dir",
                        str(workspace_dir),
                        "--base",
                        base_branch,
                        "--title",
                        review_title,
                        "--body",
                        review_body,
                        "--gh-bin",
                        args.gh_bin,
                        "--format",
                        "json",
                    ]
                    if args.repo:
                        open_review_command.extend(["--repo", args.repo])
                    if args.open_review_dry_run:
                        open_review_command.append("--dry-run")
                    open_payload, open_result, open_diagnostic = (
                        run_platform_json_command(open_review_command)
                    )
                    command_results.append(open_result)
                    if open_diagnostic is not None:
                        diagnostics.append(open_diagnostic)
                    open_ok = open_payload is not None and open_payload.get("ok") is True
                    open_report = (
                        workspace_dir
                        / ".platform"
                        / "graph_repository_open_review_report.json"
                    )
                    if open_ok:
                        report_refs["open_review"] = str(open_report)
                    operation_records.append(
                        git_service_operation_record(
                            name="open_review",
                            status=(
                                "dry_run"
                                if open_ok and args.open_review_dry_run
                                else "succeeded"
                                if open_ok
                                else "failed"
                            ),
                            request_artifact_kind="platform_git_service_open_review_request",
                            response_artifact_kind="platform_git_service_open_review_response",
                            report_ref=str(open_report) if open_ok else None,
                            adapter_command=open_review_command,
                            diagnostics=[open_diagnostic] if open_diagnostic else [],
                        )
                    )
                else:
                    operation_records.append(
                        git_service_operation_record(
                            name="open_review",
                            status="skipped_commit_failed",
                            request_artifact_kind="platform_git_service_open_review_request",
                            response_artifact_kind="platform_git_service_open_review_response",
                        )
                    )
        else:
            operation_records.extend(
                [
                    git_service_operation_record(
                        name="commit_candidate",
                        status="skipped_prepare_failed",
                        request_artifact_kind="platform_git_service_commit_candidate_request",
                        response_artifact_kind="platform_git_service_commit_candidate_response",
                    ),
                    git_service_operation_record(
                        name="open_review",
                        status="skipped_prepare_failed",
                        request_artifact_kind="platform_git_service_open_review_request",
                        response_artifact_kind="platform_git_service_open_review_response",
                    ),
                ]
            )

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    ok = error_count == 0 and all(
        operation["status"] in {"succeeded", "dry_run", "skipped_dry_run"}
        for operation in operation_records
    )
    output_path = Path(args.output) if args.output else (
        workspace_dir / ".platform" / "git_service_promotion_execution_report.json"
    )
    report = {
        "schema_version": 1,
        "artifact_kind": "platform_git_service_promotion_execution_report",
        "generated_at": utc_now_iso(),
        "contract_ref": str(contract_path),
        "deployment_profile_ref": str(deployment_profile_path),
        "promotion_request_ref": str(promotion_request_path),
        "approval_decision_ref": str(approval_decision_path),
        "ok": ok,
        "dry_run": args.dry_run,
        "open_review_dry_run": args.open_review_dry_run,
        "workflow_lane": promotion_request.get("workflow_lane"),
        "deployment_profile": {
            "profile_id": deployment_profile.get("profile_id"),
            "workflow_lane": deployment_profile.get("workflow_lane"),
            "git_service_mode": nested_mapping(deployment_profile, "git_service").get(
                "mode"
            ),
        },
        "candidate_id": candidate_id,
        "approval_decision": {
            "decision_state": nested_mapping(approval_decision, "decision").get(
                "state"
            ),
            "review_state": nested_mapping(approval_decision, "readiness").get(
                "review_state"
            ),
            "operator_ref": nested_mapping(approval_decision, "decision").get(
                "operator_ref"
            ),
        },
        "candidate_ref": promotion_request.get("candidate_branch"),
        "repository_dir": str(repository_dir),
        "workspace_dir": str(workspace_dir),
        "materialized_source_dir": (
            None if materialized_source_dir is None else str(materialized_source_dir)
        ),
        "copied_materialized_files": copied_files,
        "operations": operation_records,
        "adapter_command_results": command_results,
        "report_refs": report_refs,
        "authority_boundary": {
            "specspace_direct_git_write": False,
            "canonical_spec_mutation_without_review": False,
            "ontology_package_write": False,
            "auto_merge": False,
            "private_artifact_publication": False,
        },
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "operation_count": len(operation_records),
            "completed_operation_count": sum(
                1
                for operation in operation_records
                if operation["status"] in {"succeeded", "dry_run"}
            ),
        },
    }

    if not args.no_write_report and (ok or output_path.parent.exists()):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "candidate_id": candidate_id,
                        "status": "ok" if ok else "blocked",
                        "operations": str(len(operation_records)),
                    }
                ],
                [
                    ("candidate_id", "CANDIDATE"),
                    ("status", "STATUS"),
                    ("operations", "OPS"),
                ],
            )
        )
    return 0 if ok else 1


def git_service_finalize_promotion(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract)
    open_review_report_path = Path(args.open_review_report).resolve()
    worktree_dir = Path(args.worktree_dir).resolve()
    bundle_dir = Path(args.bundle_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    contract = load_json_mapping(contract_path, label="git service contract")
    diagnostics = [
        *validate_git_service_operation_contract_schema(contract),
        *git_service_operation_contract_semantic_diagnostics(contract),
    ]
    operation_records: list[dict[str, Any]] = []
    command_results: list[dict[str, Any]] = []
    report_refs: dict[str, str] = {}
    review_state = "unknown"
    read_model_published = False

    preflight_error_count = sum(
        1 for diagnostic in diagnostics if diagnostic.level == "ERROR"
    )
    if preflight_error_count == 0:
        review_status_command = [
            "graph-repository",
            "review-status",
            "--open-review-report",
            str(open_review_report_path),
            "--worktree-dir",
            str(worktree_dir),
            "--gh-bin",
            args.gh_bin,
            "--format",
            "json",
        ]
        if args.repo:
            review_status_command.extend(["--repo", args.repo])
        review_payload, review_result, review_diagnostic = run_platform_json_command(
            review_status_command
        )
        command_results.append(review_result)
        if review_diagnostic is not None:
            diagnostics.append(review_diagnostic)
        review_ok = review_payload is not None and review_payload.get("ok") is True
        review_state = (
            str(review_payload.get("review_state"))
            if review_payload is not None
            and isinstance(review_payload.get("review_state"), str)
            else "unknown"
        )
        review_status_report = (
            worktree_dir
            / ".platform"
            / "graph_repository_review_status_report.json"
        )
        if review_ok:
            report_refs["review_status"] = str(review_status_report)
        operation_records.append(
            git_service_operation_record(
                name="review_status",
                status="succeeded" if review_ok else "failed",
                request_artifact_kind="platform_git_service_review_status_request",
                response_artifact_kind="platform_git_service_review_status_response",
                report_ref=str(review_status_report) if review_ok else None,
                adapter_command=review_status_command,
                diagnostics=[review_diagnostic] if review_diagnostic else [],
            )
        )

        if review_ok and review_state == "merged":
            publish_command = [
                "graph-repository",
                "publish-read-model",
                "--review-status-report",
                str(review_status_report),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--manifest-name",
                args.manifest_name,
                "--format",
                "json",
            ]
            if args.dry_run:
                publish_command.append("--dry-run")
            publish_payload, publish_result, publish_diagnostic = (
                run_platform_json_command(publish_command)
            )
            command_results.append(publish_result)
            if publish_diagnostic is not None:
                diagnostics.append(publish_diagnostic)
            publish_ok = (
                publish_payload is not None and publish_payload.get("ok") is True
            )
            read_model_published = (
                publish_payload is not None
                and nested_mapping(publish_payload, "summary").get("published")
                is True
            )
            publish_report = (
                output_dir
                / ".platform"
                / "graph_repository_publish_read_model_report.json"
            )
            if publish_ok:
                report_refs["publish_read_model"] = str(publish_report)
            operation_records.append(
                git_service_operation_record(
                    name="publish_read_model",
                    status="dry_run" if publish_ok and args.dry_run else "succeeded"
                    if publish_ok
                    else "failed",
                    request_artifact_kind=(
                        "platform_git_service_publish_read_model_request"
                    ),
                    response_artifact_kind=(
                        "platform_git_service_publish_read_model_response"
                    ),
                    report_ref=str(publish_report) if publish_ok else None,
                    adapter_command=publish_command,
                    diagnostics=[publish_diagnostic] if publish_diagnostic else [],
                )
            )
        elif review_ok:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="git_service_review_not_merged",
                    subject="review_state",
                    message="read-model publication requires merged review status",
                )
            )
            operation_records.append(
                git_service_operation_record(
                    name="publish_read_model",
                    status="skipped_review_not_merged",
                    request_artifact_kind=(
                        "platform_git_service_publish_read_model_request"
                    ),
                    response_artifact_kind=(
                        "platform_git_service_publish_read_model_response"
                    ),
                )
            )
        else:
            operation_records.append(
                git_service_operation_record(
                    name="publish_read_model",
                    status="skipped_review_status_failed",
                    request_artifact_kind=(
                        "platform_git_service_publish_read_model_request"
                    ),
                    response_artifact_kind=(
                        "platform_git_service_publish_read_model_response"
                    ),
                )
            )
    else:
        operation_records.extend(
            [
                git_service_operation_record(
                    name="review_status",
                    status="skipped_preflight_failed",
                    request_artifact_kind="platform_git_service_review_status_request",
                    response_artifact_kind=(
                        "platform_git_service_review_status_response"
                    ),
                ),
                git_service_operation_record(
                    name="publish_read_model",
                    status="skipped_preflight_failed",
                    request_artifact_kind=(
                        "platform_git_service_publish_read_model_request"
                    ),
                    response_artifact_kind=(
                        "platform_git_service_publish_read_model_response"
                    ),
                ),
            ]
        )

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    ok = error_count == 0 and all(
        operation["status"] in {"succeeded", "dry_run"}
        for operation in operation_records
    )
    output_path = Path(args.output) if args.output else (
        worktree_dir / ".platform" / "git_service_promotion_finalization_report.json"
    )
    report = {
        "schema_version": 1,
        "artifact_kind": "platform_git_service_promotion_finalization_report",
        "generated_at": utc_now_iso(),
        "contract_ref": str(contract_path),
        "open_review_report_ref": str(open_review_report_path),
        "ok": ok,
        "dry_run": args.dry_run,
        "review_state": review_state,
        "worktree_dir": str(worktree_dir),
        "bundle_dir": str(bundle_dir),
        "output_dir": str(output_dir),
        "operations": operation_records,
        "adapter_command_results": command_results,
        "report_refs": report_refs,
        "authority_boundary": {
            "specspace_direct_git_write": False,
            "canonical_spec_mutation_without_review": False,
            "ontology_package_write": False,
            "auto_merge": False,
            "private_artifact_publication": False,
        },
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "operation_count": len(operation_records),
            "completed_operation_count": sum(
                1
                for operation in operation_records
                if operation["status"] in {"succeeded", "dry_run"}
            ),
            "read_model_published": read_model_published,
        },
    }

    if not args.no_write_report and (ok or output_path.parent.exists()):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "review_state": review_state,
                        "status": "ok" if ok else "blocked",
                        "published": str(read_model_published),
                    }
                ],
                [
                    ("review_state", "REVIEW"),
                    ("status", "STATUS"),
                    ("published", "PUBLISHED"),
                ],
            )
        )
    return 0 if ok else 1


def nested_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def add_blocker(blockers: list[str], blocker: str) -> None:
    if blocker and blocker not in blockers:
        blockers.append(blocker)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def path_arg_or_default(
    value: str | None,
    *,
    base_dir: Path,
    default_rel: str,
) -> Path:
    if value:
        return Path(value).resolve()
    return (base_dir / default_rel).resolve()


def resolve_optional_path_arg(value: str | None) -> str | None:
    if not value:
        return None
    return str(Path(value).resolve())


def graph_repository_run_artifact_status(
    *,
    runs_dir: Path,
    artifact_key: str,
    filename: str,
    expected_kind: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[Diagnostic]]:
    path = runs_dir / filename
    subject = f"runs.{filename}"
    if not path.is_file():
        return (
            {
                "key": artifact_key,
                "path": str(path),
                "available": False,
                "artifact_kind": None,
                "expected_artifact_kind": expected_kind,
            },
            None,
            [
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_artifact_missing",
                    subject=subject,
                    message="required SpecGraph run artifact is missing",
                )
            ],
        )

    try:
        payload = load_json_mapping(path, label="SpecGraph run artifact")
    except PlatformError as exc:
        return (
            {
                "key": artifact_key,
                "path": str(path),
                "available": False,
                "artifact_kind": None,
                "expected_artifact_kind": expected_kind,
            },
            None,
            [
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_artifact_unreadable",
                    subject=subject,
                    message=str(exc),
                )
            ],
        )

    diagnostics: list[Diagnostic] = []
    artifact_kind = payload.get("artifact_kind")
    if artifact_kind != expected_kind:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_artifact_kind_mismatch",
                subject=f"{subject}.artifact_kind",
                message=(
                    f"expected `{expected_kind}` but found "
                    f"`{artifact_kind if artifact_kind is not None else 'missing'}`"
                ),
            )
        )

    for field in ("canonical_mutations_allowed", "tracked_artifacts_written"):
        if payload.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_artifact_authority_expanded",
                    subject=f"{subject}.{field}",
                    message=f"{field} must be false before repository materialization",
                )
            )

    readiness = nested_mapping(payload, "readiness")
    pre_sib_readiness = nested_mapping(payload, "pre_sib_readiness")
    review_state = payload.get("review_state")
    if not isinstance(review_state, str):
        review_state = readiness.get("review_state")
    if not isinstance(review_state, str):
        review_state = pre_sib_readiness.get("review_state")

    status = {
        "key": artifact_key,
        "path": str(path),
        "available": True,
        "artifact_kind": artifact_kind,
        "expected_artifact_kind": expected_kind,
        "proposal_id": payload.get("proposal_id"),
        "contract_ref": payload.get("contract_ref"),
        "review_state": review_state,
        "readiness_ready": readiness.get("ready"),
        "pre_sib_ready": pre_sib_readiness.get("ready"),
    }
    return status, payload, diagnostics


def graph_repository_operation(
    *,
    name: str,
    status: str,
    reason: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "evidence": evidence or [],
    }


def graph_repository_required_summary_count(
    payload: dict[str, Any],
    *,
    artifact_key: str,
    key: str,
) -> tuple[int, list[Diagnostic]]:
    summary = nested_mapping(payload, "summary")
    subject = f"{artifact_key}.summary.{key}"
    if key not in summary:
        return 0, [
            Diagnostic(
                level="ERROR",
                code="graph_repository_required_summary_count_missing",
                subject=subject,
                message="required SpecGraph run artifact summary count is missing",
            )
        ]

    value = summary.get(key)
    if type(value) is not int or value < 0:
        return 0, [
            Diagnostic(
                level="ERROR",
                code="graph_repository_required_summary_count_invalid",
                subject=subject,
                message="required SpecGraph run artifact summary count must be a non-negative integer",
            )
        ]
    return value, []


def repair_session_readiness_flag(
    repair_session: dict[str, Any],
    key: str,
) -> bool | None:
    readiness_impact = nested_mapping(repair_session, "readiness_impact")
    summary = nested_mapping(repair_session, "summary")
    value = readiness_impact.get(key)
    if isinstance(value, bool):
        return value
    value = summary.get(key)
    return value if isinstance(value, bool) else None


def graph_repository_repair_session_diagnostics(
    repair_session: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    subject = "runs.idea_to_spec_repair_session.json"

    contract_ref = repair_session.get("contract_ref")
    if contract_ref != GRAPH_REPOSITORY_REPAIR_SESSION_CONTRACT_REF:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repair_session_contract_mismatch",
                subject=f"{subject}.contract_ref",
                message=(
                    "expected repair session journal contract "
                    f"`{GRAPH_REPOSITORY_REPAIR_SESSION_CONTRACT_REF}`"
                ),
            )
        )

    authority_boundary = repair_session.get("authority_boundary")
    if not isinstance(authority_boundary, dict):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repair_session_authority_missing",
                subject=f"{subject}.authority_boundary",
                message="repair session journal must declare an authority boundary",
            )
        )
    else:
        for flag in GRAPH_REPOSITORY_REPAIR_SESSION_AUTHORITY_FLAGS:
            if authority_boundary.get(flag) is not False:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="graph_repository_repair_session_authority_expanded",
                        subject=f"{subject}.authority_boundary.{flag}",
                        message=f"{flag} must be false before Git Service handoff",
                    )
                )

    privacy_boundary = repair_session.get("privacy_boundary")
    if not isinstance(privacy_boundary, dict):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repair_session_privacy_missing",
                subject=f"{subject}.privacy_boundary",
                message="repair session journal must declare a privacy boundary",
            )
        )
    else:
        for flag in GRAPH_REPOSITORY_REPAIR_SESSION_PRIVATE_FLAGS:
            if privacy_boundary.get(flag) is not False:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="graph_repository_repair_session_privacy_expanded",
                        subject=f"{subject}.privacy_boundary.{flag}",
                        message=f"{flag} must be false in public-safe handoff state",
                    )
                )
        if privacy_boundary.get("static_flags_are_asserted_invariants") is not True:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_repair_session_privacy_invariant_missing",
                    subject=(
                        f"{subject}.privacy_boundary."
                        "static_flags_are_asserted_invariants"
                    ),
                    message="repair session journal must assert privacy invariants",
                )
            )

    source_artifacts = repair_session.get("source_artifacts")
    if not isinstance(source_artifacts, dict):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repair_session_source_refs_missing",
                subject=f"{subject}.source_artifacts",
                message="repair session journal must include source artifact refs",
            )
        )
    else:
        for key, expected_ref in GRAPH_REPOSITORY_REPAIR_SESSION_SOURCE_REFS.items():
            source_entry = source_artifacts.get(key)
            if not isinstance(source_entry, dict):
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="graph_repository_repair_session_source_ref_missing",
                        subject=f"{subject}.source_artifacts.{key}",
                        message=f"missing repair session source ref `{key}`",
                    )
                )
                continue
            source_ref = source_entry.get("source_ref")
            if source_ref != expected_ref:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="graph_repository_repair_session_source_ref_stale",
                        subject=f"{subject}.source_artifacts.{key}.source_ref",
                        message=(
                            f"expected `{expected_ref}` but found "
                            f"`{source_ref if source_ref is not None else 'missing'}`"
                        ),
                    )
                )

    session = nested_mapping(repair_session, "session")
    summary = nested_mapping(repair_session, "summary")
    session_candidate = session.get("candidate_id")
    summary_candidate = summary.get("candidate_id")
    if not isinstance(session_candidate, str) or not session_candidate:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repair_session_candidate_missing",
                subject=f"{subject}.session.candidate_id",
                message="repair session journal must identify the candidate id",
            )
        )
    elif summary_candidate != session_candidate:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repair_session_candidate_mismatch",
                subject=f"{subject}.summary.candidate_id",
                message="repair session summary must match session candidate id",
            )
        )

    if session.get("workflow_lane") != "product_idea_to_spec":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repair_session_workflow_mismatch",
                subject=f"{subject}.session.workflow_lane",
                message="repair session journal must belong to product_idea_to_spec",
            )
        )
    if summary.get("workflow_lane") != "product_idea_to_spec":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repair_session_workflow_mismatch",
                subject=f"{subject}.summary.workflow_lane",
                message="repair session summary must belong to product_idea_to_spec",
            )
        )
    if session.get("target_repository_role") != "product_spec_workspace":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repair_session_repository_role_mismatch",
                subject=f"{subject}.session.target_repository_role",
                message=(
                    "repair session journal must target product_spec_workspace "
                    "before Git Service handoff"
                ),
            )
        )

    for key in (
        "intermediate_artifacts_ready",
        "ready_for_candidate_approval",
        "ready_for_platform_promotion",
    ):
        if repair_session_readiness_flag(repair_session, key) is None:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_repair_session_readiness_flag_missing",
                    subject=f"{subject}.readiness_impact.{key}",
                    message=f"repair session journal must report `{key}` as a boolean",
                )
            )

    return diagnostics


def build_graph_repository_execution_plan(
    *,
    contract_path: Path,
    contract: dict[str, Any],
    runs_dir: Path,
) -> tuple[dict[str, Any], list[Diagnostic]]:
    diagnostics = [
        *validate_graph_repository_contract_schema(contract),
        *graph_repository_contract_semantic_diagnostics(contract),
    ]
    source_artifacts: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    for artifact_key, (
        filename,
        expected_kind,
    ) in GRAPH_REPOSITORY_REQUIRED_RUN_ARTIFACTS.items():
        status, payload, artifact_diagnostics = graph_repository_run_artifact_status(
            runs_dir=runs_dir,
            artifact_key=artifact_key,
            filename=filename,
            expected_kind=expected_kind,
        )
        source_artifacts.append(status)
        if payload is not None:
            payloads[artifact_key] = payload
        diagnostics.extend(artifact_diagnostics)

    repair_session = payloads.get("idea_to_spec_repair_session")
    if repair_session is not None:
        diagnostics.extend(graph_repository_repair_session_diagnostics(repair_session))

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    operations: list[dict[str, Any]]
    ready_for_branch = False
    if error_count:
        operations = [
            graph_repository_operation(
                name="create_candidate_workspace",
                status="blocked",
                reason="contract_or_required_run_artifacts_invalid",
            ),
            graph_repository_operation(
                name="validate_candidate_graph",
                status="blocked",
                reason="contract_or_required_run_artifacts_invalid",
            ),
            graph_repository_operation(
                name="prepare_branch",
                status="blocked",
                reason="contract_or_required_run_artifacts_invalid",
            ),
            graph_repository_operation(
                name="create_commit",
                status="blocked",
                reason="prepare_branch_not_ready",
            ),
            graph_repository_operation(
                name="open_review",
                status="blocked",
                reason="create_commit_not_ready",
            ),
            graph_repository_operation(
                name="publish_read_model",
                status="blocked",
                reason="review_not_opened",
            ),
        ]
    else:
        candidate = payloads["candidate_spec_graph"]
        pre_sib = payloads["pre_sib_coherence_report"]
        repair = payloads["candidate_repair_loop_report"]
        clarification_answers = payloads["idea_to_spec_clarification_answers"]
        ontology_decisions = payloads["product_ontology_gap_review_decisions"]
        rerun_input = payloads["idea_to_spec_answer_rerun_input"]
        rerun_preview = payloads["idea_to_spec_rerun_preview"]
        rerun_materialization = payloads["idea_to_spec_rerun_materialization"]
        repair_session = payloads["idea_to_spec_repair_session"]
        candidate_readiness = nested_mapping(candidate, "pre_sib_readiness")
        pre_sib_readiness = nested_mapping(pre_sib, "readiness")
        repair_readiness = nested_mapping(repair, "readiness")
        clarification_answers_readiness = nested_mapping(
            clarification_answers,
            "readiness",
        )
        ontology_decisions_readiness = nested_mapping(
            ontology_decisions,
            "readiness",
        )
        rerun_input_readiness = nested_mapping(rerun_input, "readiness")
        rerun_preview_readiness = nested_mapping(rerun_preview, "readiness")
        rerun_materialization_readiness = nested_mapping(
            rerun_materialization,
            "readiness",
        )
        repair_session_readiness = nested_mapping(repair_session, "readiness")
        repair_session_impact = nested_mapping(repair_session, "readiness_impact")
        repair_summary = nested_mapping(repair, "summary")
        context_required_count = repair_summary.get("context_required_count", 0)
        if not isinstance(context_required_count, int):
            context_required_count = 0
        rerun_preview_unresolved_gap_count, rerun_preview_count_diagnostics = (
            graph_repository_required_summary_count(
                rerun_preview,
                artifact_key="idea_to_spec_rerun_preview",
                key="unresolved_ontology_gap_count",
            )
        )
        diagnostics.extend(rerun_preview_count_diagnostics)
        (
            rerun_materialization_unresolved_gap_count,
            rerun_materialization_count_diagnostics,
        ) = graph_repository_required_summary_count(
            rerun_materialization,
            artifact_key="idea_to_spec_rerun_materialization",
            key="unresolved_ontology_gap_count",
        )
        diagnostics.extend(rerun_materialization_count_diagnostics)
        rerun_preview_unresolved_gap_count_invalid = bool(
            rerun_preview_count_diagnostics
        )
        rerun_materialization_unresolved_gap_count_invalid = bool(
            rerun_materialization_count_diagnostics
        )
        repair_session_unresolved_gap_count, repair_session_count_diagnostics = (
            graph_repository_required_summary_count(
                repair_session,
                artifact_key="idea_to_spec_repair_session",
                key="unresolved_ontology_gap_count",
            )
        )
        diagnostics.extend(repair_session_count_diagnostics)
        repair_session_unresolved_gap_count_invalid = bool(
            repair_session_count_diagnostics
        )

        prepare_blockers: list[str] = []
        if candidate_readiness.get("ready") is not True:
            add_blocker(prepare_blockers, "candidate_not_ready")
        if candidate_readiness.get("review_state") == "context_required":
            add_blocker(prepare_blockers, "candidate_context_required")
        if pre_sib_readiness.get("ready") is not True:
            add_blocker(prepare_blockers, "pre_sib_not_ready")
        if repair_readiness.get("ready") is not True:
            add_blocker(prepare_blockers, "repair_loop_not_ready")
        if context_required_count > 0:
            add_blocker(prepare_blockers, "repair_context_required")
        if clarification_answers_readiness.get("ready") is not True:
            add_blocker(prepare_blockers, "clarification_answers_not_ready")
        if ontology_decisions_readiness.get("ready") is not True:
            add_blocker(prepare_blockers, "ontology_gap_decisions_not_ready")
        if rerun_input_readiness.get("ready") is not True:
            add_blocker(prepare_blockers, "rerun_input_not_ready")
        if rerun_preview_readiness.get("ready") is not True:
            add_blocker(prepare_blockers, "rerun_preview_not_ready")
        if rerun_materialization_readiness.get("ready") is not True:
            add_blocker(prepare_blockers, "rerun_materialization_not_ready")
        if rerun_preview_unresolved_gap_count_invalid:
            add_blocker(
                prepare_blockers,
                "rerun_preview_unresolved_gap_count_invalid",
            )
        if rerun_materialization_unresolved_gap_count_invalid:
            add_blocker(
                prepare_blockers,
                "rerun_materialization_unresolved_gap_count_invalid",
            )
        if repair_session_unresolved_gap_count_invalid:
            add_blocker(
                prepare_blockers,
                "repair_session_unresolved_gap_count_invalid",
            )
        if rerun_preview_unresolved_gap_count > 0:
            add_blocker(prepare_blockers, "rerun_preview_unresolved_ontology_gaps")
        if rerun_materialization_unresolved_gap_count > 0:
            add_blocker(
                prepare_blockers,
                "rerun_materialization_unresolved_ontology_gaps",
            )
        if repair_session_unresolved_gap_count > 0:
            add_blocker(prepare_blockers, "repair_session_unresolved_ontology_gaps")
        if repair_session_readiness.get("ready") is not True:
            add_blocker(prepare_blockers, "repair_session_not_ready")
        if (
            repair_session_readiness_flag(
                repair_session,
                "intermediate_artifacts_ready",
            )
            is not True
        ):
            add_blocker(
                prepare_blockers,
                "repair_session_intermediate_artifacts_not_ready",
            )
        if (
            repair_session_readiness_flag(
                repair_session,
                "ready_for_candidate_approval",
            )
            is not True
        ):
            impact_blockers = string_list(repair_session_impact.get("blocked_by"))
            if impact_blockers:
                for blocker in impact_blockers:
                    add_blocker(prepare_blockers, blocker)
            else:
                add_blocker(
                    prepare_blockers,
                    "repair_session_not_ready_for_candidate_approval",
                )

        ready_for_branch = not prepare_blockers
        operations = [
            graph_repository_operation(
                name="create_candidate_workspace",
                status="ready",
                reason="required read-only run artifacts are available",
                evidence=[
                    "idea_event_storming_intake",
                    "candidate_spec_graph",
                    "idea_to_spec_clarification_requests",
                    "idea_to_spec_repair_session",
                ],
            ),
            graph_repository_operation(
                name="validate_candidate_graph",
                status="ready" if ready_for_branch else "blocked",
                reason="candidate graph, pre-SIB, repair chain, and ontology gaps ready"
                if ready_for_branch
                else ",".join(prepare_blockers),
                evidence=[
                    "candidate_spec_graph",
                    "pre_sib_coherence_report",
                    "idea_to_spec_rerun_preview",
                    "idea_to_spec_rerun_materialization",
                    "idea_to_spec_repair_session",
                ],
            ),
            graph_repository_operation(
                name="prepare_branch",
                status="ready" if ready_for_branch else "blocked",
                reason="pre_sib_repair_loop_and_rerun_materialization_ready"
                if ready_for_branch
                else ",".join(prepare_blockers),
                evidence=[
                    "pre_sib_coherence_report",
                    "candidate_repair_loop_report",
                    "idea_to_spec_clarification_answers",
                    "product_ontology_gap_review_decisions",
                    "idea_to_spec_answer_rerun_input",
                    "idea_to_spec_rerun_preview",
                    "idea_to_spec_rerun_materialization",
                    "idea_to_spec_repair_session",
                ],
            ),
            graph_repository_operation(
                name="create_commit",
                status="blocked_until_prepare_branch",
                reason="report-only plan does not execute git commit",
            ),
            graph_repository_operation(
                name="open_review",
                status="blocked_until_create_commit",
                reason="report-only plan does not open pull requests",
            ),
            graph_repository_operation(
                name="publish_read_model",
                status="blocked_until_review_or_policy",
                reason="report-only plan does not publish read models",
            ),
        ]

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    plan = {
        "schema_version": 1,
        "artifact_kind": "platform_graph_repository_execution_plan",
        "contract_ref": str(contract_path),
        "runs_dir": str(runs_dir),
        "ok": error_count == 0,
        "ready_for_branch": ready_for_branch,
        "read_only": True,
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "write_actions_executed": [],
        "authority_boundary": {
            "executes_git_commands": False,
            "opens_pull_requests": False,
            "merges_pull_requests": False,
            "writes_ontology_packages": False,
            "mutates_canonical_specs": False,
            "publishes_private_artifacts": False,
        },
        "source_artifacts": source_artifacts,
        "operations": operations,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "source_artifact_count": len(source_artifacts),
            "ready_operation_count": sum(
                1 for operation in operations if operation["status"] == "ready"
            ),
            "blocked_operation_count": sum(
                1 for operation in operations if operation["status"] != "ready"
            ),
        },
    }
    return plan, diagnostics


def graph_repository_plan(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract)
    runs_dir = Path(args.runs_dir)
    contract = load_json_mapping(contract_path, label="graph repository contract")
    plan, diagnostics = build_graph_repository_execution_plan(
        contract_path=contract_path,
        contract=contract,
        runs_dir=runs_dir,
    )
    error_count = plan["summary"]["error_count"]

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(plan, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        rows = [
            {
                "operation": operation["name"],
                "status": operation["status"],
                "reason": operation["reason"],
            }
            for operation in plan["operations"]
        ]
        print(
            render_rows(
                rows,
                [
                    ("operation", "OPERATION"),
                    ("status", "STATUS"),
                    ("reason", "REASON"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def load_product_repair_artifact(
    path: Path,
    *,
    label: str,
    expected_kind: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[Diagnostic]]:
    subject = label.replace(" ", "_")
    if not path.is_file():
        return (
            None,
            {
                "key": subject,
                "path": str(path),
                "available": False,
                "expected_artifact_kind": expected_kind,
            },
            [
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_artifact_missing",
                    subject=subject,
                    message=f"{label} artifact is required before rerun execution",
                )
            ],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return (
            None,
            {
                "key": subject,
                "path": str(path),
                "available": False,
                "expected_artifact_kind": expected_kind,
            },
            [
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_artifact_json_invalid",
                    subject=subject,
                    message=f"{label} artifact is not valid JSON: {exc}",
                )
            ],
        )
    if not isinstance(payload, dict):
        return (
            None,
            {
                "key": subject,
                "path": str(path),
                "available": False,
                "expected_artifact_kind": expected_kind,
            },
            [
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_artifact_shape_invalid",
                    subject=subject,
                    message=f"{label} artifact must be a JSON object",
                )
            ],
        )

    diagnostics: list[Diagnostic] = []
    artifact_kind = payload.get("artifact_kind")
    if artifact_kind != expected_kind:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_artifact_kind_mismatch",
                subject=f"{subject}.artifact_kind",
                message=f"expected {expected_kind}, found {artifact_kind}",
            )
        )
    status = {
        "key": subject,
        "path": str(path),
        "available": True,
        "artifact_kind": artifact_kind,
        "expected_artifact_kind": expected_kind,
        "contract_ref": payload.get("contract_ref"),
        "sha256": file_sha256(path),
    }
    return payload, status, diagnostics


def product_repair_false_field_diagnostics(
    payload: dict[str, Any],
    *,
    fields: tuple[str, ...],
    subject: str,
    code: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for field in fields:
        if field in payload and payload.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code=code,
                    subject=f"{subject}.{field}",
                    message=f"{field} must remain false for product repair rerun handoff",
                )
            )
    return diagnostics


def product_repair_boundary_diagnostics(
    payload: dict[str, Any],
    *,
    section: str,
    subject: str,
) -> list[Diagnostic]:
    value = payload.get(section)
    if not isinstance(value, dict):
        return [
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_boundary_missing",
                subject=f"{subject}.{section}",
                message=f"{section} is required for product repair rerun handoff",
            )
        ]
    return product_repair_false_field_diagnostics(
        value,
        fields=PRODUCT_REPAIR_RERUN_BOUNDARY_FALSE_FIELDS,
        subject=f"{subject}.{section}",
        code="product_repair_rerun_authority_expanded",
    )


def product_repair_deployment_profile_diagnostics(
    profile: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics = [
        *validate_deployment_profile_schema(profile),
        *deployment_profile_semantic_diagnostics(profile),
    ]
    if profile.get("profile_id") != "product_idea_to_spec_workbench":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_profile_unsupported",
                subject="deployment_profile.profile_id",
                message=(
                    "product repair rerun execution requires the "
                    "product_idea_to_spec_workbench deployment profile"
                ),
            )
        )
    if profile.get("workflow_lane") != "product_idea_to_spec":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_workflow_lane_unsupported",
                subject="deployment_profile.workflow_lane",
                message="product repair rerun execution requires product_idea_to_spec",
            )
        )
    return diagnostics


def product_repair_specgraph_checkout_diagnostics(
    specgraph_dir: Path,
    *,
    code_prefix: str,
    subject: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not specgraph_dir.is_dir():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code=f"{code_prefix}_specgraph_dir_missing",
                subject=subject,
                message="SpecGraph directory must exist before product repair rerun",
            )
        )
    elif not (specgraph_dir / "Makefile").is_file():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code=f"{code_prefix}_specgraph_makefile_missing",
                subject=subject,
                message="SpecGraph directory must contain a Makefile",
            )
        )
    return diagnostics


def product_repair_import_preview_diagnostics(
    import_preview: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if import_preview.get("contract_ref") != PRODUCT_REPAIR_RERUN_IMPORT_PREVIEW_CONTRACT_REF:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_import_preview_contract_mismatch",
                subject="import_preview.contract_ref",
                message=(
                    "expected import preview contract "
                    f"{PRODUCT_REPAIR_RERUN_IMPORT_PREVIEW_CONTRACT_REF}"
                ),
            )
        )
    diagnostics.extend(
        product_repair_false_field_diagnostics(
            import_preview,
            fields=PRODUCT_REPAIR_RERUN_FALSE_TOP_LEVEL_FIELDS,
            subject="import_preview",
            code="product_repair_rerun_import_preview_authority_expanded",
        )
    )
    diagnostics.extend(
        product_repair_boundary_diagnostics(
            import_preview,
            section="authority_boundary",
            subject="import_preview",
        )
    )
    readiness = nested_mapping(import_preview, "readiness")
    if readiness.get("ready") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_import_preview_not_ready",
                subject="import_preview.readiness.ready",
                message="import preview must be ready before Platform rerun execution",
            )
        )
    accepted_count = nested_mapping(import_preview, "summary").get(
        "accepted_for_rerun_count"
    )
    if not isinstance(accepted_count, int) or accepted_count <= 0:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_import_preview_no_accepted_drafts",
                subject="import_preview.summary.accepted_for_rerun_count",
                message="import preview must contain at least one accepted draft",
            )
        )
    return diagnostics


def product_repair_request_state_diagnostics(
    request_state: dict[str, Any],
    *,
    selected_request_id: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if request_state.get("state_owner") != "SpecSpace":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_request_state_owner_invalid",
                subject="request_state.state_owner",
                message="repair rerun request state must be owned by SpecSpace",
            )
        )
    diagnostics.extend(
        product_repair_false_field_diagnostics(
            request_state,
            fields=PRODUCT_REPAIR_RERUN_FALSE_TOP_LEVEL_FIELDS,
            subject="request_state",
            code="product_repair_rerun_request_state_authority_expanded",
        )
    )
    diagnostics.extend(
        product_repair_boundary_diagnostics(
            request_state,
            section="consumer_boundary",
            subject="request_state",
        )
    )
    diagnostics.extend(
        product_repair_boundary_diagnostics(
            request_state,
            section="authority_boundary",
            subject="request_state",
        )
    )
    requests = [
        item for item in request_state.get("requests", []) if isinstance(item, dict)
    ]
    selected = next(
        (item for item in requests if item.get("id") == selected_request_id),
        None,
    )
    if selected is None:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_request_missing",
                subject="request_state.requests",
                message="request state must include the request selected by SpecGraph gate",
            )
        )
        return diagnostics
    if selected.get("requested_action") != "prepare_repair_draft_rerun":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_request_action_unsupported",
                subject="request_state.requests[].requested_action",
                message="selected request must ask to prepare_repair_draft_rerun",
            )
        )
    if selected.get("status") != "requested":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_request_status_unsupported",
                subject="request_state.requests[].status",
                message="selected request must still be in requested state",
            )
        )
    diagnostics.extend(
        product_repair_false_field_diagnostics(
            selected,
            fields=PRODUCT_REPAIR_RERUN_REQUEST_FALSE_FIELDS,
            subject="request_state.requests[]",
            code="product_repair_rerun_request_authority_expanded",
        )
    )
    return diagnostics


def product_repair_request_gate_diagnostics(
    gate: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if gate.get("contract_ref") != PRODUCT_REPAIR_RERUN_GATE_CONTRACT_REF:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_gate_contract_mismatch",
                subject="request_gate.contract_ref",
                message=f"expected request gate contract {PRODUCT_REPAIR_RERUN_GATE_CONTRACT_REF}",
            )
        )
    diagnostics.extend(
        product_repair_false_field_diagnostics(
            gate,
            fields=PRODUCT_REPAIR_RERUN_FALSE_TOP_LEVEL_FIELDS,
            subject="request_gate",
            code="product_repair_rerun_gate_authority_expanded",
        )
    )
    diagnostics.extend(
        product_repair_boundary_diagnostics(
            gate,
            section="authority_boundary",
            subject="request_gate",
        )
    )
    readiness = nested_mapping(gate, "readiness")
    if readiness.get("ready") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_gate_not_ready",
                subject="request_gate.readiness.ready",
                message="SpecGraph repair rerun request gate must be ready",
            )
        )
    recommended = nested_mapping(gate, "recommended_invocation")
    if recommended.get("make_target") != PRODUCT_REPAIR_RERUN_MAKE_TARGET:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_gate_make_target_mismatch",
                subject="request_gate.recommended_invocation.make_target",
                message=f"expected {PRODUCT_REPAIR_RERUN_MAKE_TARGET}",
            )
        )
    return diagnostics


def product_repair_identity_diagnostics(
    *,
    gate: dict[str, Any],
    import_preview: dict[str, Any],
    repair_session: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    gate_summary = nested_mapping(gate, "summary")
    gate_inputs = nested_mapping(gate, "resolved_inputs")
    preview_session = nested_mapping(import_preview, "session")
    repair_session_session = nested_mapping(repair_session, "session")
    expected = {
        "workspace_id": gate_summary.get("workspace_id")
        or gate_inputs.get("workspace_id"),
        "candidate_id": gate_summary.get("candidate_id")
        or gate_inputs.get("candidate_id"),
    }
    for field, expected_value in expected.items():
        if not isinstance(expected_value, str) or not expected_value:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_identity_missing",
                    subject=f"request_gate.summary.{field}",
                    message=f"request gate must identify {field}",
                )
            )
            continue
        for artifact_name, source in (
            ("import_preview", preview_session),
            ("repair_session", repair_session_session),
        ):
            actual = source.get(field)
            if actual and actual != expected_value:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="product_repair_rerun_identity_mismatch",
                        subject=f"{artifact_name}.session.{field}",
                        message=(
                            f"{artifact_name} {field} must match request gate "
                            f"({expected_value})"
                        ),
                    )
                )
    if repair_session_session.get("workflow_lane") != "product_idea_to_spec":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_repair_session_lane_mismatch",
                subject="repair_session.session.workflow_lane",
                message="repair session must belong to product_idea_to_spec",
            )
        )
    if repair_session_session.get("target_repository_role") != "product_spec_workspace":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_repair_session_repository_role_mismatch",
                subject="repair_session.session.target_repository_role",
                message="repair session must target product_spec_workspace",
            )
        )
    return diagnostics


def product_repair_operation(
    *,
    name: str,
    status: str,
    reason: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "evidence": evidence or [],
    }


def build_product_repair_rerun_execution_plan(
    *,
    deployment_profile_path: Path,
    deployment_profile: dict[str, Any],
    specgraph_dir: Path,
    request_state_path: Path,
    request_state: dict[str, Any] | None,
    import_preview_path: Path,
    import_preview: dict[str, Any] | None,
    repair_session_path: Path,
    repair_session: dict[str, Any] | None,
    request_gate_path: Path,
    request_gate: dict[str, Any] | None,
    source_artifacts: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[Diagnostic]]:
    deployment_profile_diagnostics = product_repair_deployment_profile_diagnostics(
        deployment_profile
    )
    diagnostics = [*deployment_profile_diagnostics]
    diagnostics.extend(
        product_repair_specgraph_checkout_diagnostics(
            specgraph_dir,
            code_prefix="product_repair_rerun",
            subject="specgraph_dir",
        )
    )

    selected_request_id = ""
    if request_gate is not None:
        diagnostics.extend(product_repair_request_gate_diagnostics(request_gate))
        selected_request_id = str(
            nested_mapping(request_gate, "summary").get("selected_request_id") or ""
        )
    if request_state is not None:
        diagnostics.extend(
            product_repair_request_state_diagnostics(
                request_state,
                selected_request_id=selected_request_id,
            )
        )
    if import_preview is not None:
        diagnostics.extend(product_repair_import_preview_diagnostics(import_preview))
    if repair_session is not None:
        diagnostics.extend(graph_repository_repair_session_diagnostics(repair_session))
        if nested_mapping(repair_session, "readiness").get("ready") is not True:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_repair_session_not_ready",
                    subject="repair_session.readiness.ready",
                    message="repair session journal must be ready before rerun execution",
                )
            )
    if (
        request_gate is not None
        and import_preview is not None
        and repair_session is not None
    ):
        diagnostics.extend(
            product_repair_identity_diagnostics(
                gate=request_gate,
                import_preview=import_preview,
                repair_session=repair_session,
            )
        )

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    ready_to_execute = error_count == 0
    operations = [
        product_repair_operation(
            name="validate_deployment_profile",
            status="ready" if not deployment_profile_diagnostics else "blocked",
            reason=(
                "product idea-to-spec deployment profile allows controlled rerun execution"
                if not deployment_profile_diagnostics
                else "deployment_profile_invalid"
            ),
            evidence=["deployment_profile"],
        ),
        product_repair_operation(
            name="validate_specspace_rerun_request",
            status="ready" if ready_to_execute else "blocked",
            reason="request, import preview, gate, and repair session are coherent"
            if ready_to_execute
            else "request_or_gate_not_ready",
            evidence=[
                "idea_to_spec_repair_rerun_requests",
                "specspace_repair_draft_import_preview",
                "specspace_repair_rerun_request_gate",
                "idea_to_spec_repair_session",
            ],
        ),
        product_repair_operation(
            name="execute_specgraph_requested_rerun",
            status="ready" if ready_to_execute else "blocked",
            reason="SpecGraph requested repair rerun target can be invoked"
            if ready_to_execute
            else "preflight_not_ready",
            evidence=[PRODUCT_REPAIR_RERUN_MAKE_TARGET],
        ),
        product_repair_operation(
            name="publish_public_safe_bundle",
            status="blocked_until_execution",
            reason="publication is a separate post-execution step",
            evidence=["make publish-bundle"],
        ),
    ]
    output_refs = {
        key: str(specgraph_dir / value)
        for key, value in PRODUCT_REPAIR_RERUN_DEFAULT_OUTPUTS.items()
    }
    plan = {
        "schema_version": 1,
        "artifact_kind": PRODUCT_REPAIR_RERUN_PLAN_KIND,
        "generated_at": utc_now_iso(),
        "deployment_profile_ref": str(deployment_profile_path),
        "specgraph_dir": str(specgraph_dir),
        "ok": error_count == 0,
        "ready_to_execute": ready_to_execute,
        "read_only": False,
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "target_make": {
            "target": PRODUCT_REPAIR_RERUN_MAKE_TARGET,
            "cwd": str(specgraph_dir),
            "variables": {
                "SPECSPACE_REPAIR_RERUN_REQUEST_STATE": str(request_state_path),
                "SPECSPACE_REPAIR_RERUN_REQUEST_IMPORT_PREVIEW": str(import_preview_path),
                "SPECSPACE_REPAIR_RERUN_REQUEST_REPAIR_SESSION": str(repair_session_path),
                "SPECSPACE_REPAIR_RERUN_REQUEST_OUTPUT": str(request_gate_path),
            },
        },
        "source_artifacts": source_artifacts,
        "expected_outputs": output_refs,
        "operations": operations,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "authority_boundary": {
            "executes_specgraph_make_target": True,
            "executes_git_commands": False,
            "opens_pull_requests": False,
            "merges_pull_requests": False,
            "writes_ontology_packages": False,
            "accepts_ontology_terms": False,
            "mutates_canonical_specs": False,
            "publishes_private_artifacts": False,
        },
        "summary": {
            "status": "ready_to_execute" if ready_to_execute else "blocked",
            "error_count": error_count,
            "source_artifact_count": len(source_artifacts),
            "expected_output_count": len(output_refs),
            "workspace_id": (
                nested_mapping(request_gate or {}, "summary").get("workspace_id")
            ),
            "candidate_id": (
                nested_mapping(request_gate or {}, "summary").get("candidate_id")
            ),
            "selected_request_id": (
                nested_mapping(request_gate or {}, "summary").get(
                    "selected_request_id"
                )
            ),
        },
    }
    return plan, diagnostics


def product_repair_rerun_plan(args: argparse.Namespace) -> int:
    deployment_profile_path = Path(args.deployment_profile)
    specgraph_dir = Path(args.specgraph_dir).resolve()
    request_state_path = path_arg_or_default(
        args.rerun_request,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_REPAIR_RERUN_DEFAULT_INPUTS["rerun_request"],
    )
    import_preview_path = path_arg_or_default(
        args.import_preview,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_REPAIR_RERUN_DEFAULT_INPUTS["import_preview"],
    )
    repair_session_path = path_arg_or_default(
        args.repair_session,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_REPAIR_RERUN_DEFAULT_INPUTS["repair_session"],
    )
    request_gate_path = path_arg_or_default(
        args.request_gate,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_REPAIR_RERUN_DEFAULT_INPUTS["request_gate"],
    )
    deployment_profile = load_json_mapping(
        deployment_profile_path,
        label="deployment profile",
    )
    source_artifacts: list[dict[str, Any]] = []
    request_state, request_status, request_diagnostics = load_product_repair_artifact(
        request_state_path,
        label="idea_to_spec_repair_rerun_requests",
        expected_kind=PRODUCT_REPAIR_RERUN_REQUEST_KIND,
    )
    source_artifacts.append(request_status)
    import_preview, import_status, import_diagnostics = load_product_repair_artifact(
        import_preview_path,
        label="specspace_repair_draft_import_preview",
        expected_kind=PRODUCT_REPAIR_RERUN_IMPORT_PREVIEW_KIND,
    )
    source_artifacts.append(import_status)
    repair_session, repair_status, repair_diagnostics = load_product_repair_artifact(
        repair_session_path,
        label="idea_to_spec_repair_session",
        expected_kind="idea_to_spec_repair_session_journal",
    )
    source_artifacts.append(repair_status)
    request_gate, gate_status, gate_diagnostics = load_product_repair_artifact(
        request_gate_path,
        label="specspace_repair_rerun_request_gate",
        expected_kind=PRODUCT_REPAIR_RERUN_GATE_KIND,
    )
    source_artifacts.append(gate_status)
    plan, diagnostics = build_product_repair_rerun_execution_plan(
        deployment_profile_path=deployment_profile_path,
        deployment_profile=deployment_profile,
        specgraph_dir=specgraph_dir,
        request_state_path=request_state_path,
        request_state=request_state,
        import_preview_path=import_preview_path,
        import_preview=import_preview,
        repair_session_path=repair_session_path,
        repair_session=repair_session,
        request_gate_path=request_gate_path,
        request_gate=request_gate,
        source_artifacts=source_artifacts,
    )
    diagnostics = [
        *request_diagnostics,
        *import_diagnostics,
        *repair_diagnostics,
        *gate_diagnostics,
        *diagnostics,
    ]
    if diagnostics:
        plan["diagnostics"] = [asdict(diagnostic) for diagnostic in diagnostics]
        error_count = sum(
            1 for diagnostic in diagnostics if diagnostic.level == "ERROR"
        )
        plan["ok"] = error_count == 0
        plan["ready_to_execute"] = error_count == 0 and plan["ready_to_execute"]
        plan["summary"]["error_count"] = error_count
        plan["summary"]["status"] = (
            "ready_to_execute" if plan["ready_to_execute"] else "blocked"
        )
    else:
        error_count = 0

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(plan, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "operation": operation["name"],
                        "status": operation["status"],
                        "reason": operation["reason"],
                    }
                    for operation in plan["operations"]
                ],
                [
                    ("operation", "OPERATION"),
                    ("status", "STATUS"),
                    ("reason", "REASON"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def product_repair_plan_diagnostics(plan: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if plan.get("artifact_kind") != PRODUCT_REPAIR_RERUN_PLAN_KIND:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_plan_kind_mismatch",
                subject="artifact_kind",
                message=f"expected {PRODUCT_REPAIR_RERUN_PLAN_KIND}",
            )
        )
    if plan.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_plan_not_ok",
                subject="ok",
                message="execution plan must be ok before rerun execution",
            )
        )
    if plan.get("ready_to_execute") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_plan_not_ready",
                subject="ready_to_execute",
                message="execution plan must be ready_to_execute",
            )
        )
    target_make = nested_mapping(plan, "target_make")
    if target_make.get("target") != PRODUCT_REPAIR_RERUN_MAKE_TARGET:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_plan_make_target_unsupported",
                subject="target_make.target",
                message=f"expected {PRODUCT_REPAIR_RERUN_MAKE_TARGET}",
            )
        )
    specgraph_dir = Path(str(plan.get("specgraph_dir") or ".")).resolve()
    target_cwd = target_make.get("cwd")
    if not isinstance(target_cwd, str) or Path(target_cwd).resolve() != specgraph_dir:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_plan_cwd_mismatch",
                subject="target_make.cwd",
                message="target_make.cwd must match plan specgraph_dir",
            )
        )
    diagnostics.extend(
        product_repair_specgraph_checkout_diagnostics(
            specgraph_dir,
            code_prefix="product_repair_rerun_plan",
            subject="specgraph_dir",
        )
    )
    authority = nested_mapping(plan, "authority_boundary")
    for field in (
        "executes_git_commands",
        "opens_pull_requests",
        "merges_pull_requests",
        "writes_ontology_packages",
        "accepts_ontology_terms",
        "mutates_canonical_specs",
        "publishes_private_artifacts",
    ):
        if authority.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_plan_authority_expanded",
                    subject=f"authority_boundary.{field}",
                    message=f"{field} must remain false",
                )
            )
    return diagnostics


def product_repair_make_command(
    plan: dict[str, Any],
    *,
    python: str | None = None,
) -> list[str]:
    target_make = nested_mapping(plan, "target_make")
    command = ["make", PRODUCT_REPAIR_RERUN_MAKE_TARGET]
    variables = nested_mapping(target_make, "variables")
    for key in sorted(variables):
        value = variables.get(key)
        if isinstance(value, str) and value:
            command.append(f"{key}={value}")
    if python:
        command.append(f"PYTHON={python}")
    return command


def product_repair_output_record(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if path.is_file():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    return {
        "path": str(path),
        "present": path.is_file(),
        "artifact_kind": payload.get("artifact_kind"),
        "contract_ref": payload.get("contract_ref"),
        "ready": nested_mapping(payload, "readiness").get("ready"),
        "status": nested_mapping(payload, "summary").get("status")
        or nested_mapping(payload, "readiness").get("review_state"),
        "sha256": file_sha256(path),
    }


def product_repair_output_diagnostics(
    output_records: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    rerun_report = output_records.get("rerun_report", {})
    if rerun_report.get("present") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_report_missing",
                subject="outputs.rerun_report",
                message="SpecGraph requested rerun must produce a rerun report",
            )
        )
    elif rerun_report.get("artifact_kind") != PRODUCT_REPAIR_RERUN_REPORT_KIND:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_report_kind_mismatch",
                subject="outputs.rerun_report.artifact_kind",
                message=f"expected {PRODUCT_REPAIR_RERUN_REPORT_KIND}",
            )
        )
    elif rerun_report.get("contract_ref") != PRODUCT_REPAIR_RERUN_REPORT_CONTRACT_REF:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_report_contract_mismatch",
                subject="outputs.rerun_report.contract_ref",
                message=f"expected {PRODUCT_REPAIR_RERUN_REPORT_CONTRACT_REF}",
            )
        )
    elif rerun_report.get("ready") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_report_not_ready",
                subject="outputs.rerun_report.readiness.ready",
                message="SpecGraph requested rerun report must be ready",
            )
        )
    repair_session = output_records.get("repair_session", {})
    if repair_session.get("present") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_repair_session_missing",
                subject="outputs.repair_session",
                message="SpecGraph requested rerun must refresh the repair session journal",
            )
        )
    return diagnostics


def product_repair_rerun_execute(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    plan = load_json_mapping(plan_path, label="product repair rerun execution plan")
    diagnostics = product_repair_plan_diagnostics(plan)
    specgraph_dir = Path(plan.get("specgraph_dir") or ".").resolve()
    output_path = (
        Path(args.output)
        if args.output
        else specgraph_dir / "runs" / "platform_product_repair_rerun_execution_report.json"
    )
    command = product_repair_make_command(plan, python=args.python)
    command_result: dict[str, Any] | None = None
    execution_started_at = utc_now_iso()
    if not diagnostics and not args.dry_run:
        completed = subprocess.run(
            command,
            cwd=specgraph_dir,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        command_result = {
            "command": command,
            "cwd": str(specgraph_dir),
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
        if completed.returncode != 0:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_make_failed",
                    subject=PRODUCT_REPAIR_RERUN_MAKE_TARGET,
                    message=(
                        "SpecGraph requested repair rerun target failed with exit "
                        f"code {completed.returncode}"
                    ),
                )
            )
    elif args.dry_run:
        command_result = {
            "command": command,
            "cwd": str(specgraph_dir),
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "dry_run": True,
        }

    expected_outputs = nested_mapping(plan, "expected_outputs")
    output_records = {
        key: product_repair_output_record(Path(value))
        for key, value in expected_outputs.items()
        if isinstance(value, str)
    }
    if not diagnostics and not args.dry_run:
        diagnostics.extend(product_repair_output_diagnostics(output_records))
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    ok = error_count == 0 and (args.dry_run or command_result is not None)
    operations = [
        product_repair_operation(
            name="execute_specgraph_requested_rerun",
            status="dry_run" if args.dry_run else "succeeded" if ok else "failed",
            reason="SpecGraph requested rerun target executed"
            if ok and not args.dry_run
            else "dry_run"
            if args.dry_run
            else "execution_failed",
            evidence=[PRODUCT_REPAIR_RERUN_MAKE_TARGET],
        ),
        product_repair_operation(
            name="publish_public_safe_bundle",
            status="blocked_until_publication",
            reason="run product-repair-rerun publish after successful execution",
            evidence=["make publish-bundle"],
        ),
    ]
    report = {
        "schema_version": 1,
        "artifact_kind": PRODUCT_REPAIR_RERUN_EXECUTION_REPORT_KIND,
        "generated_at": utc_now_iso(),
        "started_at": execution_started_at,
        "plan_ref": str(plan_path),
        "specgraph_dir": str(specgraph_dir),
        "ok": ok,
        "dry_run": args.dry_run,
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "authority_boundary": {
            "executes_specgraph_make_target": not args.dry_run,
            "executes_git_commands": False,
            "opens_pull_requests": False,
            "merges_pull_requests": False,
            "writes_ontology_packages": False,
            "accepts_ontology_terms": False,
            "mutates_canonical_specs": False,
            "publishes_private_artifacts": False,
        },
        "command": command,
        "command_result": command_result,
        "operations": operations,
        "output_artifacts": output_records,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "status": "completed" if ok and not args.dry_run else "dry_run" if args.dry_run else "failed",
            "error_count": error_count,
            "output_artifact_count": len(output_records),
            "rerun_report_digest": nested_mapping(output_records, "rerun_report").get(
                "sha256"
            ),
            "repair_session_digest": nested_mapping(
                output_records,
                "repair_session",
            ).get("sha256"),
        },
    }
    if not args.no_write_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "status": report["summary"]["status"],
                        "outputs": str(len(output_records)),
                    }
                ],
                [("status", "STATUS"), ("outputs", "OUTPUTS")],
            )
        )
    return 0 if ok else 1


def product_repair_execution_report_diagnostics(
    report: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if report.get("artifact_kind") != PRODUCT_REPAIR_RERUN_EXECUTION_REPORT_KIND:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_execution_report_kind_mismatch",
                subject="artifact_kind",
                message=f"expected {PRODUCT_REPAIR_RERUN_EXECUTION_REPORT_KIND}",
            )
        )
    if report.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_execution_report_not_ok",
                subject="ok",
                message="publication requires a successful repair rerun execution report",
            )
        )
    if report.get("dry_run") is True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_execution_report_dry_run",
                subject="dry_run",
                message="publication requires a non-dry-run repair rerun execution report",
            )
        )
    authority = nested_mapping(report, "authority_boundary")
    for field in (
        "executes_git_commands",
        "opens_pull_requests",
        "merges_pull_requests",
        "writes_ontology_packages",
        "accepts_ontology_terms",
        "mutates_canonical_specs",
        "publishes_private_artifacts",
    ):
        if authority.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_execution_authority_expanded",
                    subject=f"authority_boundary.{field}",
                    message=f"{field} must remain false before publication",
                )
            )
    return diagnostics


def product_repair_rerun_publish(args: argparse.Namespace) -> int:
    execution_report_path = Path(args.execution_report)
    execution_report = load_json_mapping(
        execution_report_path,
        label="product repair rerun execution report",
    )
    diagnostics = product_repair_execution_report_diagnostics(execution_report)
    specgraph_dir = Path(
        args.specgraph_dir or execution_report.get("specgraph_dir") or "."
    ).resolve()
    diagnostics.extend(
        product_repair_specgraph_checkout_diagnostics(
            specgraph_dir,
            code_prefix="product_repair_rerun_publish",
            subject="specgraph_dir",
        )
    )
    output_path = (
        Path(args.output)
        if args.output
        else specgraph_dir
        / "runs"
        / "platform_product_repair_rerun_publication_report.json"
    )
    command = ["make", "publish-bundle"]
    if args.python:
        command.append(f"PYTHON={args.python}")
    command_result: dict[str, Any] | None = None
    if not diagnostics and not args.dry_run:
        completed = subprocess.run(
            command,
            cwd=specgraph_dir,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        command_result = {
            "command": command,
            "cwd": str(specgraph_dir),
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
        if completed.returncode != 0:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_publish_bundle_failed",
                    subject="make publish-bundle",
                    message=f"publish-bundle failed with exit code {completed.returncode}",
                )
            )
    elif args.dry_run:
        command_result = {
            "command": command,
            "cwd": str(specgraph_dir),
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "dry_run": True,
        }

    manifest_path = specgraph_dir / "dist" / "specgraph-public" / "artifact_manifest.json"
    manifest_present = manifest_path.is_file()
    if not args.dry_run and not manifest_present:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_public_manifest_missing",
                subject="dist/specgraph-public/artifact_manifest.json",
                message="publish-bundle must produce a public artifact manifest",
            )
        )
    public_paths = [
        "runs/idea_to_spec_repair_session.json",
        "runs/specspace_repair_draft_rerun_report.json",
        "runs/idea_to_spec_rerun_preview.json",
        "runs/idea_to_spec_rerun_materialization.json",
    ]
    present_public_paths = []
    missing_public_paths = []
    for rel_path in public_paths:
        if (specgraph_dir / "dist" / "specgraph-public" / rel_path).is_file():
            present_public_paths.append(rel_path)
        else:
            missing_public_paths.append(rel_path)
    if not args.dry_run and missing_public_paths:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_public_artifacts_missing",
                subject="dist/specgraph-public/runs",
                message=(
                    "publish-bundle did not publish expected repair rerun artifacts: "
                    + ", ".join(missing_public_paths)
                ),
            )
        )
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    ok = error_count == 0
    report = {
        "schema_version": 1,
        "artifact_kind": PRODUCT_REPAIR_RERUN_PUBLICATION_REPORT_KIND,
        "generated_at": utc_now_iso(),
        "execution_report_ref": str(execution_report_path),
        "specgraph_dir": str(specgraph_dir),
        "ok": ok,
        "dry_run": args.dry_run,
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "authority_boundary": {
            "executes_specgraph_make_target": not args.dry_run,
            "executes_git_commands": False,
            "opens_pull_requests": False,
            "merges_pull_requests": False,
            "writes_ontology_packages": False,
            "accepts_ontology_terms": False,
            "mutates_canonical_specs": False,
            "publishes_private_artifacts": False,
        },
        "command": command,
        "command_result": command_result,
        "manifest": {
            "path": str(manifest_path),
            "present": manifest_present,
            "sha256": file_sha256(manifest_path),
        },
        "published_artifacts": present_public_paths,
        "missing_artifacts": missing_public_paths,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "status": "published" if ok and not args.dry_run else "dry_run" if args.dry_run else "failed",
            "error_count": error_count,
            "published_artifact_count": len(present_public_paths),
            "missing_artifact_count": len(missing_public_paths),
        },
    }
    if not args.no_write_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "status": report["summary"]["status"],
                        "published": str(len(present_public_paths)),
                    }
                ],
                [("status", "STATUS"), ("published", "PUBLISHED")],
            )
        )
    return 0 if ok else 1


def load_product_candidate_approval_artifact(
    path: Path,
    *,
    label: str,
    expected_kind: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[Diagnostic]]:
    subject = label.replace(" ", "_")
    if not path.is_file():
        return (
            None,
            {
                "key": subject,
                "path": str(path),
                "available": False,
                "expected_artifact_kind": expected_kind,
            },
            [
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_approval_artifact_missing",
                    subject=subject,
                    message=f"{label} artifact is required before candidate approval",
                )
            ],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return (
            None,
            {
                "key": subject,
                "path": str(path),
                "available": False,
                "expected_artifact_kind": expected_kind,
            },
            [
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_approval_artifact_json_invalid",
                    subject=subject,
                    message=f"{label} artifact is not valid JSON: {exc}",
                )
            ],
        )
    if not isinstance(payload, dict):
        return (
            None,
            {
                "key": subject,
                "path": str(path),
                "available": False,
                "expected_artifact_kind": expected_kind,
            },
            [
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_approval_artifact_shape_invalid",
                    subject=subject,
                    message=f"{label} artifact must be a JSON object",
                )
            ],
        )

    diagnostics: list[Diagnostic] = []
    artifact_kind = payload.get("artifact_kind")
    if artifact_kind != expected_kind:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_artifact_kind_mismatch",
                subject=f"{subject}.artifact_kind",
                message=f"expected {expected_kind}, found {artifact_kind}",
            )
        )
    status = {
        "key": subject,
        "path": str(path),
        "available": True,
        "artifact_kind": artifact_kind,
        "expected_artifact_kind": expected_kind,
        "contract_ref": payload.get("contract_ref"),
        "sha256": file_sha256(path),
    }
    return payload, status, diagnostics


def product_candidate_approval_false_field_diagnostics(
    payload: dict[str, Any],
    *,
    fields: tuple[str, ...],
    subject: str,
    code: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for field in fields:
        if field in payload and payload.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code=code,
                    subject=f"{subject}.{field}",
                    message=f"{field} must remain false for candidate approval handoff",
                )
            )
    return diagnostics


def product_candidate_approval_boundary_diagnostics(
    payload: dict[str, Any],
    *,
    section: str,
    subject: str,
    fields: tuple[str, ...],
) -> list[Diagnostic]:
    value = payload.get(section)
    if not isinstance(value, dict):
        return [
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_boundary_missing",
                subject=f"{subject}.{section}",
                message=f"{section} is required for candidate approval handoff",
            )
        ]
    return product_candidate_approval_false_field_diagnostics(
        value,
        fields=fields,
        subject=f"{subject}.{section}",
        code="product_candidate_approval_authority_expanded",
    )


def product_candidate_approval_deployment_profile_diagnostics(
    profile: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics = [
        *validate_deployment_profile_schema(profile),
        *deployment_profile_semantic_diagnostics(profile),
    ]
    if profile.get("profile_id") != "product_idea_to_spec_workbench":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_profile_unsupported",
                subject="deployment_profile.profile_id",
                message=(
                    "candidate approval requires the product_idea_to_spec_workbench "
                    "deployment profile"
                ),
            )
        )
    if profile.get("workflow_lane") != "product_idea_to_spec":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_workflow_lane_unsupported",
                subject="deployment_profile.workflow_lane",
                message="candidate approval requires product_idea_to_spec",
            )
        )
    return diagnostics


def product_candidate_approval_latest_intent(
    intent_state: dict[str, Any],
    *,
    workspace_id: str | None,
) -> dict[str, Any] | None:
    intents = [
        item
        for item in intent_state.get("intents", [])
        if isinstance(item, dict)
        and item.get("status") == "requested"
        and item.get("requested_action") == PRODUCT_CANDIDATE_APPROVAL_INTENT_ACTION
        and (workspace_id is None or item.get("workspace_id") == workspace_id)
    ]
    if not intents:
        return None
    return sorted(
        intents,
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("updated_at") or ""),
            str(item.get("id") or ""),
        ),
    )[-1]


def product_candidate_approval_expected_refs(
    *,
    raw_arg: str | None,
    resolved_path: Path,
    default_rel: str,
    specgraph_dir: Path,
) -> tuple[str, ...]:
    refs = {default_rel}
    if raw_arg:
        refs.add(raw_arg)
        refs.add(str(resolved_path))
    try:
        refs.add(resolved_path.relative_to(specgraph_dir).as_posix())
    except ValueError:
        pass
    return tuple(sorted(ref for ref in refs if ref))


def product_candidate_approval_intent_state_diagnostics(
    intent_state: dict[str, Any],
    *,
    selected_intent: dict[str, Any] | None,
    workspace_id: str | None,
    expected_repair_session_refs: tuple[str, ...],
    expected_promotion_gate_refs: tuple[str, ...],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if intent_state.get("state_owner") != "SpecSpace":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_state_owner_invalid",
                subject="approval_intents.state_owner",
                message="candidate approval intent state must be owned by SpecSpace",
            )
        )
    if intent_state.get("schema_version") != 1:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_schema_unsupported",
                subject="approval_intents.schema_version",
                message="candidate approval intent state schema_version must be 1",
            )
        )
    diagnostics.extend(
        product_candidate_approval_false_field_diagnostics(
            intent_state,
            fields=PRODUCT_CANDIDATE_APPROVAL_FALSE_TOP_LEVEL_FIELDS,
            subject="approval_intents",
            code="product_candidate_approval_intent_state_authority_expanded",
        )
    )
    diagnostics.extend(
        product_candidate_approval_boundary_diagnostics(
            intent_state,
            section="consumer_boundary",
            subject="approval_intents",
            fields=PRODUCT_CANDIDATE_APPROVAL_CONSUMER_FALSE_FIELDS,
        )
    )
    diagnostics.extend(
        product_candidate_approval_boundary_diagnostics(
            intent_state,
            section="authority_boundary",
            subject="approval_intents",
            fields=PRODUCT_CANDIDATE_APPROVAL_AUTHORITY_FALSE_FIELDS,
        )
    )
    if selected_intent is None:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_missing",
                subject="approval_intents.intents",
                message=(
                    "candidate approval requires an active requested SpecSpace intent"
                ),
            )
        )
        return diagnostics

    if workspace_id and selected_intent.get("workspace_id") != workspace_id:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_workspace_mismatch",
                subject="approval_intents.intents[].workspace_id",
                message="selected intent must match the requested workspace",
            )
        )
    for field in ("id", "workspace_id", "candidate_id", "created_at", "requested_by"):
        if not isinstance(selected_intent.get(field), str) or not selected_intent.get(
            field
        ):
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_approval_intent_field_missing",
                    subject=f"approval_intents.intents[].{field}",
                    message=f"selected intent must include `{field}`",
                )
            )
    if selected_intent.get("status") != "requested":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_status_unsupported",
                subject="approval_intents.intents[].status",
                message="selected candidate approval intent must still be requested",
            )
        )
    if (
        selected_intent.get("requested_action")
        != PRODUCT_CANDIDATE_APPROVAL_INTENT_ACTION
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_action_unsupported",
                subject="approval_intents.intents[].requested_action",
                message=(
                    "selected intent must request approve_candidate_for_promotion_review"
                ),
            )
        )
    if selected_intent.get("ready_for_candidate_approval") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_not_ready",
                subject="approval_intents.intents[].ready_for_candidate_approval",
                message="selected intent must be recorded from an approval-ready session",
            )
        )
    if selected_intent.get("ready_for_platform_promotion") is True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_platform_promotion_premature",
                subject="approval_intents.intents[].ready_for_platform_promotion",
                message=(
                    "SpecSpace intent must not claim final Platform promotion readiness"
                ),
            )
        )
    if string_list(selected_intent.get("blocked_by")):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_blocked",
                subject="approval_intents.intents[].blocked_by",
                message="selected intent must not carry unresolved blockers",
            )
        )
    if selected_intent.get("repair_session_ref") not in expected_repair_session_refs:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_repair_session_ref_stale",
                subject="approval_intents.intents[].repair_session_ref",
                message=(
                    "selected intent must reference the repair session input for "
                    "this invocation"
                ),
            )
        )
    if selected_intent.get("promotion_gate_ref") not in expected_promotion_gate_refs:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_intent_promotion_gate_ref_stale",
                subject="approval_intents.intents[].promotion_gate_ref",
                message=(
                    "selected intent must reference the promotion gate input for "
                    "this invocation"
                ),
            )
        )
    diagnostics.extend(
        product_candidate_approval_false_field_diagnostics(
            selected_intent,
            fields=PRODUCT_CANDIDATE_APPROVAL_INTENT_FALSE_FIELDS,
            subject="approval_intents.intents[]",
            code="product_candidate_approval_intent_authority_expanded",
        )
    )
    return diagnostics


def product_candidate_approval_repair_session_diagnostics(
    repair_session: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics = [*graph_repository_repair_session_diagnostics(repair_session)]
    if nested_mapping(repair_session, "readiness").get("ready") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_repair_session_not_ready",
                subject="repair_session.readiness.ready",
                message="repair session journal must be ready before approval",
            )
        )
    if (
        repair_session_readiness_flag(repair_session, "ready_for_candidate_approval")
        is not True
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code=(
                    "product_candidate_approval_repair_session_not_ready_for_candidate_approval"
                ),
                subject="repair_session.readiness_impact.ready_for_candidate_approval",
                message="repair session must be ready for candidate approval",
            )
        )
    if repair_session_readiness_flag(repair_session, "ready_for_platform_promotion"):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_repair_session_platform_promotion_premature",
                subject="repair_session.readiness_impact.ready_for_platform_promotion",
                message=(
                    "repair session must not claim Platform promotion readiness before "
                    "candidate approval decision materialization"
                ),
            )
        )
    blockers = string_list(nested_mapping(repair_session, "readiness_impact").get("blocked_by"))
    if blockers:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_repair_session_blocked",
                subject="repair_session.readiness_impact.blocked_by",
                message="repair session blockers must be resolved before approval",
            )
        )
    return diagnostics


def product_candidate_approval_promotion_gate_diagnostics(
    promotion_gate: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    diagnostics.extend(
        product_candidate_approval_false_field_diagnostics(
            promotion_gate,
            fields=PRODUCT_CANDIDATE_APPROVAL_FALSE_TOP_LEVEL_FIELDS,
            subject="promotion_gate",
            code="product_candidate_approval_promotion_gate_authority_expanded",
        )
    )
    authority_boundary = promotion_gate.get("authority_boundary")
    if isinstance(authority_boundary, dict):
        for key, value in sorted(authority_boundary.items()):
            if value is not False:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="product_candidate_approval_promotion_gate_authority_expanded",
                        subject=f"promotion_gate.authority_boundary.{key}",
                        message="promotion gate must not expand write authority",
                    )
                )
    return diagnostics


def product_candidate_approval_publication_report_diagnostics(
    report: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if report.get("artifact_kind") != PRODUCT_REPAIR_RERUN_PUBLICATION_REPORT_KIND:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_publication_report_kind_mismatch",
                subject="repair_publication.artifact_kind",
                message=f"expected {PRODUCT_REPAIR_RERUN_PUBLICATION_REPORT_KIND}",
            )
        )
    if report.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_publication_report_not_ok",
                subject="repair_publication.ok",
                message="candidate approval requires successful public-safe publication",
            )
        )
    if report.get("dry_run") is True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_publication_report_dry_run",
                subject="repair_publication.dry_run",
                message="candidate approval requires non-dry-run publication",
            )
        )
    diagnostics.extend(
        product_candidate_approval_false_field_diagnostics(
            report,
            fields=PRODUCT_CANDIDATE_APPROVAL_FALSE_TOP_LEVEL_FIELDS,
            subject="repair_publication",
            code="product_candidate_approval_publication_authority_expanded",
        )
    )
    authority = nested_mapping(report, "authority_boundary")
    for field in PRODUCT_CANDIDATE_APPROVAL_REPORT_AUTHORITY_FALSE_FIELDS:
        if field == "executes_specgraph_make_target":
            continue
        if authority.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_approval_publication_authority_expanded",
                    subject=f"repair_publication.authority_boundary.{field}",
                    message=f"{field} must remain false before candidate approval",
                )
            )
    if nested_mapping(report, "manifest").get("present") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_publication_manifest_missing",
                subject="repair_publication.manifest.present",
                message="publication report must prove a public-safe manifest",
            )
        )
    if nested_mapping(report, "summary").get("missing_artifact_count", 0) != 0:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_publication_artifacts_missing",
                subject="repair_publication.summary.missing_artifact_count",
                message="publication report must not have missing public artifacts",
            )
        )
    return diagnostics


def product_candidate_approval_identity_diagnostics(
    *,
    selected_intent: dict[str, Any],
    repair_session: dict[str, Any],
    promotion_gate: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    candidate_id = selected_intent.get("candidate_id")
    workspace_id = selected_intent.get("workspace_id")
    repair_session_session = nested_mapping(repair_session, "session")
    repair_session_summary = nested_mapping(repair_session, "summary")
    promotion_summary = nested_mapping(promotion_gate, "summary")
    for artifact_name, source in (
        ("repair_session.session", repair_session_session),
        ("repair_session.summary", repair_session_summary),
        ("promotion_gate.summary", promotion_summary),
    ):
        actual_candidate = source.get("candidate_id")
        if actual_candidate and actual_candidate != candidate_id:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_approval_candidate_mismatch",
                    subject=f"{artifact_name}.candidate_id",
                    message="all approval handoff artifacts must reference the same candidate",
                )
            )
        actual_workspace = source.get("workspace_id")
        if actual_workspace and actual_workspace != workspace_id:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_approval_workspace_mismatch",
                    subject=f"{artifact_name}.workspace_id",
                    message="all approval handoff artifacts must reference the same workspace",
                )
            )
    intent_session_id = selected_intent.get("repair_session_id")
    repair_session_id = repair_session_session.get("session_id")
    if intent_session_id and repair_session_id and intent_session_id != repair_session_id:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_repair_session_mismatch",
                subject="approval_intents.intents[].repair_session_id",
                message="selected intent must reference the current repair session",
            )
        )
    return diagnostics


def product_candidate_approval_path_diagnostics(paths: list[str]) -> list[Diagnostic]:
    diagnostics = [*graph_repository_relative_paths_diagnostics(paths)]
    if not paths:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_paths_missing",
                subject="path",
                message="candidate approval materialization requires approved paths",
            )
        )
    for index, raw_path in enumerate(paths):
        if Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
            continue
        if graph_repository_promotion_path_allowed(raw_path):
            continue
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_path_not_allowed",
                subject=f"path[{index}]",
                message=(
                    "candidate approval paths must be under specs/, docs/proposals/, "
                    "or runs/"
                ),
            )
        )
    return diagnostics


def build_product_candidate_approval_gate_report(
    *,
    deployment_profile_path: Path,
    deployment_profile: dict[str, Any],
    specgraph_dir: Path,
    intent_state: dict[str, Any] | None,
    repair_session: dict[str, Any] | None,
    promotion_gate: dict[str, Any] | None,
    repair_execution: dict[str, Any] | None,
    repair_publication: dict[str, Any] | None,
    selected_intent: dict[str, Any] | None,
    source_artifacts: list[dict[str, Any]],
    paths: list[str],
    expected_repair_session_refs: tuple[str, ...],
    expected_promotion_gate_refs: tuple[str, ...],
    extra_diagnostics: list[Diagnostic],
) -> tuple[dict[str, Any], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = [
        *extra_diagnostics,
        *product_candidate_approval_deployment_profile_diagnostics(
            deployment_profile
        ),
        *product_repair_specgraph_checkout_diagnostics(
            specgraph_dir,
            code_prefix="product_candidate_approval",
            subject="specgraph_dir",
        ),
        *product_candidate_approval_path_diagnostics(paths),
    ]
    if intent_state is not None:
        diagnostics.extend(
            product_candidate_approval_intent_state_diagnostics(
                intent_state,
                selected_intent=selected_intent,
                workspace_id=(
                    str(selected_intent.get("workspace_id"))
                    if selected_intent is not None
                    and isinstance(selected_intent.get("workspace_id"), str)
                    else None
                ),
                expected_repair_session_refs=expected_repair_session_refs,
                expected_promotion_gate_refs=expected_promotion_gate_refs,
            )
        )
    if repair_session is not None:
        diagnostics.extend(
            product_candidate_approval_repair_session_diagnostics(repair_session)
        )
    if promotion_gate is not None:
        diagnostics.extend(
            product_candidate_approval_promotion_gate_diagnostics(promotion_gate)
        )
    if repair_execution is not None:
        diagnostics.extend(product_repair_execution_report_diagnostics(repair_execution))
        diagnostics.extend(
            product_candidate_approval_false_field_diagnostics(
                repair_execution,
                fields=PRODUCT_CANDIDATE_APPROVAL_FALSE_TOP_LEVEL_FIELDS,
                subject="repair_execution",
                code="product_candidate_approval_execution_authority_expanded",
            )
        )
    if repair_publication is not None:
        diagnostics.extend(
            product_candidate_approval_publication_report_diagnostics(
                repair_publication
            )
        )
    if (
        selected_intent is not None
        and repair_session is not None
        and promotion_gate is not None
    ):
        diagnostics.extend(
            product_candidate_approval_identity_diagnostics(
                selected_intent=selected_intent,
                repair_session=repair_session,
                promotion_gate=promotion_gate,
            )
        )

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    ready_to_materialize = error_count == 0
    selected_summary = (
        {
            "id": selected_intent.get("id"),
            "workspace_id": selected_intent.get("workspace_id"),
            "candidate_id": selected_intent.get("candidate_id"),
            "repair_session_id": selected_intent.get("repair_session_id"),
            "repair_session_ref": selected_intent.get("repair_session_ref"),
            "promotion_gate_ref": selected_intent.get("promotion_gate_ref"),
            "requested_by": selected_intent.get("requested_by"),
            "reason": selected_intent.get("reason"),
            "created_at": selected_intent.get("created_at"),
        }
        if selected_intent is not None
        else None
    )
    operations = [
        product_repair_operation(
            name="validate_specspace_candidate_approval_intent",
            status="ready" if ready_to_materialize else "blocked",
            reason="SpecSpace intent is coherent"
            if ready_to_materialize
            else "intent_or_sources_not_ready",
            evidence=["idea_to_spec_candidate_approval_intents"],
        ),
        product_repair_operation(
            name="validate_repair_session_journal",
            status="ready" if ready_to_materialize else "blocked",
            reason="repair session is candidate-approval ready"
            if ready_to_materialize
            else "repair_session_not_ready",
            evidence=["idea_to_spec_repair_session"],
        ),
        product_repair_operation(
            name="validate_platform_rerun_publication",
            status="ready" if ready_to_materialize else "blocked",
            reason="repair rerun execution and publication are complete"
            if ready_to_materialize
            else "repair_rerun_reports_not_ready",
            evidence=[
                "platform_product_repair_rerun_execution_report",
                "platform_product_repair_rerun_publication_report",
            ],
        ),
        product_repair_operation(
            name="materialize_candidate_approval_decision",
            status="ready" if ready_to_materialize else "blocked",
            reason="candidate approval decision can be materialized"
            if ready_to_materialize
            else "approval_gate_not_ready",
            evidence=["candidate_approval_decision"],
        ),
    ]
    report = {
        "schema_version": 1,
        "artifact_kind": PRODUCT_CANDIDATE_APPROVAL_GATE_REPORT_KIND,
        "generated_at": utc_now_iso(),
        "deployment_profile_ref": str(deployment_profile_path),
        "specgraph_dir": str(specgraph_dir),
        "ok": error_count == 0,
        "ready_to_materialize": ready_to_materialize,
        "canonical_mutations_allowed": False,
        "ontology_writes_allowed": False,
        "tracked_artifacts_written": False,
        "source_artifacts": source_artifacts,
        "selected_intent": selected_summary,
        "approved_paths": paths if ready_to_materialize else [],
        "operations": operations,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "authority_boundary": PRODUCT_CANDIDATE_APPROVAL_BOUNDARY,
        "recommended_next_action": {
            "command": "product-candidate-approval materialize",
            "requires_git_service_execution": False,
            "next_downstream_gate": "graph-repository promotion-request",
        },
        "summary": {
            "status": "ready_to_materialize" if ready_to_materialize else "blocked",
            "error_count": error_count,
            "source_artifact_count": len(source_artifacts),
            "approved_path_count": len(paths) if ready_to_materialize else 0,
            "workspace_id": selected_summary.get("workspace_id")
            if selected_summary
            else None,
            "candidate_id": selected_summary.get("candidate_id")
            if selected_summary
            else None,
            "selected_intent_id": selected_summary.get("id")
            if selected_summary
            else None,
        },
    }
    return report, diagnostics


def product_candidate_approval_gate(args: argparse.Namespace) -> int:
    deployment_profile_path = Path(args.deployment_profile)
    specgraph_dir = Path(args.specgraph_dir).resolve()
    approval_intents_path = path_arg_or_default(
        args.approval_intents,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["approval_intents"],
    )
    repair_session_path = path_arg_or_default(
        args.repair_session,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["repair_session"],
    )
    promotion_gate_path = path_arg_or_default(
        args.promotion_gate,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["promotion_gate"],
    )
    repair_execution_path = path_arg_or_default(
        args.repair_execution,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["repair_execution"],
    )
    repair_publication_path = path_arg_or_default(
        args.repair_publication,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["repair_publication"],
    )
    output_path = path_arg_or_default(
        args.output,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_CANDIDATE_APPROVAL_DEFAULT_OUTPUTS["gate"],
    )

    deployment_profile = load_json_mapping(
        deployment_profile_path,
        label="deployment profile",
    )
    source_artifacts: list[dict[str, Any]] = []
    intent_state, intent_status, intent_diagnostics = (
        load_product_candidate_approval_artifact(
            approval_intents_path,
            label="idea_to_spec_candidate_approval_intents",
            expected_kind=PRODUCT_CANDIDATE_APPROVAL_INTENT_STATE_KIND,
        )
    )
    source_artifacts.append(intent_status)
    repair_session, repair_status, repair_diagnostics = (
        load_product_candidate_approval_artifact(
            repair_session_path,
            label="idea_to_spec_repair_session",
            expected_kind="idea_to_spec_repair_session_journal",
        )
    )
    source_artifacts.append(repair_status)
    promotion_gate, promotion_status, promotion_diagnostics = (
        load_product_candidate_approval_artifact(
            promotion_gate_path,
            label="idea_to_spec_promotion_gate",
            expected_kind="idea_to_spec_promotion_gate",
        )
    )
    source_artifacts.append(promotion_status)
    repair_execution, execution_status, execution_diagnostics = (
        load_product_candidate_approval_artifact(
            repair_execution_path,
            label="platform_product_repair_rerun_execution_report",
            expected_kind=PRODUCT_REPAIR_RERUN_EXECUTION_REPORT_KIND,
        )
    )
    source_artifacts.append(execution_status)
    repair_publication, publication_status, publication_diagnostics = (
        load_product_candidate_approval_artifact(
            repair_publication_path,
            label="platform_product_repair_rerun_publication_report",
            expected_kind=PRODUCT_REPAIR_RERUN_PUBLICATION_REPORT_KIND,
        )
    )
    source_artifacts.append(publication_status)

    selected_intent = (
        product_candidate_approval_latest_intent(
            intent_state,
            workspace_id=args.workspace_id,
        )
        if intent_state is not None
        else None
    )
    report, diagnostics = build_product_candidate_approval_gate_report(
        deployment_profile_path=deployment_profile_path,
        deployment_profile=deployment_profile,
        specgraph_dir=specgraph_dir,
        intent_state=intent_state,
        repair_session=repair_session,
        promotion_gate=promotion_gate,
        repair_execution=repair_execution,
        repair_publication=repair_publication,
        selected_intent=selected_intent,
        source_artifacts=source_artifacts,
        paths=list(args.path or []),
        expected_repair_session_refs=product_candidate_approval_expected_refs(
            raw_arg=args.repair_session,
            resolved_path=repair_session_path,
            default_rel=PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["repair_session"],
            specgraph_dir=specgraph_dir,
        ),
        expected_promotion_gate_refs=product_candidate_approval_expected_refs(
            raw_arg=args.promotion_gate,
            resolved_path=promotion_gate_path,
            default_rel=PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["promotion_gate"],
            specgraph_dir=specgraph_dir,
        ),
        extra_diagnostics=[
            *intent_diagnostics,
            *repair_diagnostics,
            *promotion_diagnostics,
            *execution_diagnostics,
            *publication_diagnostics,
        ],
    )
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    if not args.no_write_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "status": report["summary"]["status"],
                        "candidate": str(report["summary"]["candidate_id"]),
                        "paths": str(report["summary"]["approved_path_count"]),
                    }
                ],
                [
                    ("status", "STATUS"),
                    ("candidate", "CANDIDATE"),
                    ("paths", "PATHS"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def product_candidate_approval_gate_report_diagnostics(
    report: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if report.get("artifact_kind") != PRODUCT_CANDIDATE_APPROVAL_GATE_REPORT_KIND:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_gate_report_kind_mismatch",
                subject="gate_report.artifact_kind",
                message=f"expected {PRODUCT_CANDIDATE_APPROVAL_GATE_REPORT_KIND}",
            )
        )
    if report.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_gate_report_not_ok",
                subject="gate_report.ok",
                message="candidate approval gate report must be ok",
            )
        )
    if report.get("ready_to_materialize") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_gate_not_ready",
                subject="gate_report.ready_to_materialize",
                message="candidate approval gate must be ready to materialize",
            )
        )
    diagnostics.extend(
        product_candidate_approval_false_field_diagnostics(
            report,
            fields=PRODUCT_CANDIDATE_APPROVAL_FALSE_TOP_LEVEL_FIELDS,
            subject="gate_report",
            code="product_candidate_approval_gate_authority_expanded",
        )
    )
    authority = nested_mapping(report, "authority_boundary")
    for key, value in sorted(authority.items()):
        if value is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_approval_gate_authority_expanded",
                    subject=f"gate_report.authority_boundary.{key}",
                    message="candidate approval gate must not execute write actions",
                )
            )
    if not string_list(report.get("approved_paths")):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_gate_paths_missing",
                subject="gate_report.approved_paths",
                message="ready gate report must include approved promotion paths",
            )
        )
    if not isinstance(report.get("selected_intent"), dict):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_approval_gate_intent_missing",
                subject="gate_report.selected_intent",
                message="ready gate report must include selected intent metadata",
            )
        )
    return diagnostics


def build_candidate_approval_decision(
    *,
    gate_report_path: Path,
    gate_report: dict[str, Any],
) -> dict[str, Any]:
    selected_intent = nested_mapping(gate_report, "selected_intent")
    summary = nested_mapping(gate_report, "summary")
    candidate_id = str(
        selected_intent.get("candidate_id") or summary.get("candidate_id") or ""
    )
    workspace_id = str(
        selected_intent.get("workspace_id") or summary.get("workspace_id") or candidate_id
    )
    paths = string_list(gate_report.get("approved_paths"))
    return {
        "artifact_kind": PRODUCT_CANDIDATE_APPROVAL_DECISION_KIND,
        "schema_version": 1,
        "contract_ref": PRODUCT_CANDIDATE_APPROVAL_DECISION_CONTRACT_REF,
        "generated_at": utc_now_iso(),
        "gate_report_ref": str(gate_report_path),
        "canonical_mutations_allowed": False,
        "ontology_writes_allowed": False,
        "tracked_artifacts_written": False,
        "workspace": {
            "workspace_id": workspace_id,
            "mode": "product_idea_to_spec",
            "repository_role": "product_spec_workspace",
            "public_route": f"/{workspace_id}",
        },
        "candidate": {
            "candidate_id": candidate_id,
            "display_name": workspace_id.replace("-", " ").title(),
            "active_candidate_ref": "runs/active_idea_to_spec_candidate.json",
            "promotion_gate_ref": selected_intent.get("promotion_gate_ref")
            or PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["promotion_gate"],
        },
        "decision": {
            "requested_state": "approved",
            "state": "approved",
            "operator_ref": selected_intent.get("requested_by"),
            "reason": selected_intent.get("reason")
            or "Approve review-ready candidate promotion.",
            "conditions": [],
        },
        "readiness": {
            "ready": True,
            "review_state": "candidate_approval_ready",
            "blocked_by": [],
        },
        "promotion_request": {
            "platform_artifact_kind": "platform_graph_repository_promotion_request",
            "paths": paths,
            "requires_git_service_execution": True,
        },
        "source_artifacts": {
            "candidate_approval_gate": str(gate_report_path),
            "candidate_approval_intent": selected_intent.get("id"),
            "repair_session": selected_intent.get("repair_session_ref")
            or PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["repair_session"],
            "promotion_gate": selected_intent.get("promotion_gate_ref")
            or PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["promotion_gate"],
            "platform_repair_execution": (
                PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["repair_execution"]
            ),
            "platform_repair_publication": (
                PRODUCT_CANDIDATE_APPROVAL_DEFAULT_INPUTS["repair_publication"]
            ),
        },
        "authority_boundary": {
            "may_execute_prompt_agent": False,
            "may_mutate_candidate_source_artifacts": False,
            "may_mutate_canonical_specs": False,
            "may_write_ontology_package": False,
            "may_write_ontology_lockfile": False,
            "may_mark_candidate_graph_accepted": False,
            "may_create_branch_or_commit": False,
            "may_open_pull_request": False,
            "may_publish_read_model": False,
            "may_execute_git_service_operation": False,
        },
    }


def product_candidate_approval_materialize(args: argparse.Namespace) -> int:
    gate_report_path = Path(args.gate_report)
    gate_report = load_json_mapping(
        gate_report_path,
        label="candidate approval gate report",
    )
    diagnostics = product_candidate_approval_gate_report_diagnostics(gate_report)
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    decision = (
        build_candidate_approval_decision(
            gate_report_path=gate_report_path,
            gate_report=gate_report,
        )
        if error_count == 0
        else {
            "artifact_kind": PRODUCT_CANDIDATE_APPROVAL_DECISION_KIND,
            "schema_version": 1,
            "contract_ref": PRODUCT_CANDIDATE_APPROVAL_DECISION_CONTRACT_REF,
            "generated_at": utc_now_iso(),
            "gate_report_ref": str(gate_report_path),
            "canonical_mutations_allowed": False,
            "ontology_writes_allowed": False,
            "tracked_artifacts_written": False,
            "readiness": {
                "ready": False,
                "review_state": "candidate_approval_blocked",
                "blocked_by": [
                    diagnostic.code
                    for diagnostic in diagnostics
                    if diagnostic.level == "ERROR"
                ],
            },
            "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
            "authority_boundary": PRODUCT_CANDIDATE_APPROVAL_BOUNDARY,
        }
    )
    output_path = (
        Path(args.output)
        if args.output
        else gate_report_path.parent / "candidate_approval_decision.json"
    )
    if error_count == 0 or not args.no_write_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(decision, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.format == "json":
        print(json.dumps(decision, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "status": decision["readiness"]["review_state"],
                        "candidate": nested_mapping(decision, "candidate").get(
                            "candidate_id",
                            "",
                        ),
                        "paths": str(
                            len(
                                string_list(
                                    nested_mapping(
                                        decision,
                                        "promotion_request",
                                    ).get("paths")
                                )
                            )
                        ),
                    }
                ],
                [
                    ("status", "STATUS"),
                    ("candidate", "CANDIDATE"),
                    ("paths", "PATHS"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def run_platform_json_subcommand(command_args: list[str]) -> tuple[
    subprocess.CompletedProcess[str],
    dict[str, Any] | None,
    Diagnostic | None,
]:
    command = [sys.executable, str(Path(__file__).resolve()), *command_args]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    except json.JSONDecodeError as exc:
        return (
            completed,
            None,
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_smoke_output_json_invalid",
                subject="stdout",
                message=f"product repair rerun subcommand did not emit JSON: {exc}",
            ),
        )
    if payload is not None and not isinstance(payload, dict):
        return (
            completed,
            None,
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_smoke_output_shape_invalid",
                subject="stdout",
                message="product repair rerun subcommand JSON output must be an object",
            ),
        )
    return completed, payload, None


def product_repair_smoke_phase(
    *,
    name: str,
    command_args: list[str],
    output_path: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[Diagnostic]]:
    completed, payload, parse_diagnostic = run_platform_json_subcommand(command_args)
    diagnostics: list[Diagnostic] = []
    if parse_diagnostic is not None:
        diagnostics.append(parse_diagnostic)
    if payload is None and parse_diagnostic is None:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_smoke_output_missing",
                subject=name,
                message="product repair rerun subcommand did not emit a JSON report",
            )
        )
    report_ok = bool(payload and payload.get("ok") is True)
    phase_ok = completed.returncode == 0 and report_ok and not diagnostics
    if completed.returncode != 0 and not diagnostics:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_smoke_phase_failed",
                subject=name,
                message=f"{name} exited with status {completed.returncode}",
            )
        )
    operation = {
        "name": name,
        "status": "succeeded" if phase_ok else "failed",
        "reason": "phase completed" if phase_ok else "phase_failed",
        "report_ref": str(output_path),
        "report_present": output_path.is_file(),
        "report_sha256": file_sha256(output_path),
        "command": [sys.executable, str(Path(__file__).resolve()), *command_args],
        "returncode": completed.returncode,
        "stderr_tail": completed.stderr[-2000:],
    }
    return operation, payload, diagnostics


def product_repair_smoke_authority_diagnostics(
    payload: dict[str, Any],
    *,
    subject: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if payload.get("canonical_mutations_allowed") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_smoke_authority_expanded",
                subject=f"{subject}.canonical_mutations_allowed",
                message="smoke phase must not allow canonical mutations",
            )
        )
    if payload.get("tracked_artifacts_written") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_smoke_authority_expanded",
                subject=f"{subject}.tracked_artifacts_written",
                message="smoke phase must not claim tracked artifact writes",
            )
        )
    authority = nested_mapping(payload, "authority_boundary")
    for field in (
        "executes_git_commands",
        "opens_pull_requests",
        "merges_pull_requests",
        "writes_ontology_packages",
        "accepts_ontology_terms",
        "mutates_canonical_specs",
        "publishes_private_artifacts",
    ):
        if authority.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_repair_rerun_smoke_authority_expanded",
                    subject=f"{subject}.authority_boundary.{field}",
                    message=f"{field} must remain false during repair rerun smoke",
                )
            )
    return diagnostics


def product_repair_smoke_report_ref(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if path.is_file():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    return {
        "path": str(path),
        "present": path.is_file(),
        "artifact_kind": payload.get("artifact_kind"),
        "ok": payload.get("ok"),
        "dry_run": payload.get("dry_run"),
        "sha256": file_sha256(path),
        "summary": nested_mapping(payload, "summary"),
    }


def product_repair_rerun_smoke(args: argparse.Namespace) -> int:
    specgraph_dir = Path(args.specgraph_dir).resolve()
    deployment_profile_path = Path(args.deployment_profile).resolve()
    plan_path = path_arg_or_default(
        args.plan_output,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_REPAIR_RERUN_DEFAULT_REPORTS["plan"],
    )
    execution_report_path = path_arg_or_default(
        args.execution_output,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_REPAIR_RERUN_DEFAULT_REPORTS["execution"],
    )
    publication_report_path = path_arg_or_default(
        args.publication_output,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_REPAIR_RERUN_DEFAULT_REPORTS["publication"],
    )
    output_path = path_arg_or_default(
        args.output,
        base_dir=specgraph_dir,
        default_rel=PRODUCT_REPAIR_RERUN_DEFAULT_REPORTS["smoke"],
    )

    operations: list[dict[str, Any]] = []
    diagnostics: list[Diagnostic] = []
    phase_payloads: dict[str, dict[str, Any]] = {}

    plan_command = [
        "product-repair-rerun",
        "plan",
        "--deployment-profile",
        str(deployment_profile_path),
        "--specgraph-dir",
        str(specgraph_dir),
        "--output",
        str(plan_path),
        "--format",
        "json",
    ]
    optional_plan_inputs = (
        ("--rerun-request", resolve_optional_path_arg(args.rerun_request)),
        ("--import-preview", resolve_optional_path_arg(args.import_preview)),
        ("--repair-session", resolve_optional_path_arg(args.repair_session)),
        ("--request-gate", resolve_optional_path_arg(args.request_gate)),
    )
    for flag, value in optional_plan_inputs:
        if value:
            plan_command.extend([flag, value])

    operation, payload, phase_diagnostics = product_repair_smoke_phase(
        name="plan_product_repair_rerun",
        command_args=plan_command,
        output_path=plan_path,
    )
    operations.append(operation)
    diagnostics.extend(phase_diagnostics)
    if payload is not None:
        phase_payloads["plan"] = payload
        diagnostics.extend(
            product_repair_smoke_authority_diagnostics(payload, subject="plan")
        )

    executes_specgraph_make_target = False
    if not diagnostics and payload and payload.get("ready_to_execute") is True:
        execute_command = [
            "product-repair-rerun",
            "execute",
            "--plan",
            str(plan_path),
            "--output",
            str(execution_report_path),
            "--format",
            "json",
        ]
        if args.python:
            execute_command.extend(["--python", args.python])
        operation, payload, phase_diagnostics = product_repair_smoke_phase(
            name="execute_specgraph_requested_rerun",
            command_args=execute_command,
            output_path=execution_report_path,
        )
        operations.append(operation)
        diagnostics.extend(phase_diagnostics)
        if payload is not None:
            phase_payloads["execution"] = payload
            executes_specgraph_make_target = (
                nested_mapping(payload, "authority_boundary").get(
                    "executes_specgraph_make_target"
                )
                is True
            )
            diagnostics.extend(
                product_repair_smoke_authority_diagnostics(
                    payload,
                    subject="execution",
                )
            )
            if payload.get("dry_run") is True:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="product_repair_rerun_smoke_execution_dry_run",
                        subject="execution.dry_run",
                        message="end-to-end repair rerun smoke requires real execution",
                    )
                )
    else:
        operations.append(
            product_repair_operation(
                name="execute_specgraph_requested_rerun",
                status="skipped",
                reason="plan_not_ready",
                evidence=[str(plan_path)],
            )
        )

    execution_payload = phase_payloads.get("execution")
    if not diagnostics and execution_payload and execution_payload.get("ok") is True:
        publish_command = [
            "product-repair-rerun",
            "publish",
            "--execution-report",
            str(execution_report_path),
            "--specgraph-dir",
            str(specgraph_dir),
            "--output",
            str(publication_report_path),
            "--format",
            "json",
        ]
        if args.python:
            publish_command.extend(["--python", args.python])
        operation, payload, phase_diagnostics = product_repair_smoke_phase(
            name="publish_public_safe_bundle",
            command_args=publish_command,
            output_path=publication_report_path,
        )
        operations.append(operation)
        diagnostics.extend(phase_diagnostics)
        if payload is not None:
            phase_payloads["publication"] = payload
            diagnostics.extend(
                product_repair_smoke_authority_diagnostics(
                    payload,
                    subject="publication",
                )
            )
            if payload.get("dry_run") is True:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="product_repair_rerun_smoke_publication_dry_run",
                        subject="publication.dry_run",
                        message="end-to-end repair rerun smoke requires real publication",
                    )
                )
    else:
        operations.append(
            product_repair_operation(
                name="publish_public_safe_bundle",
                status="skipped",
                reason="execution_not_ready",
                evidence=[str(execution_report_path)],
            )
        )

    execution_summary = nested_mapping(phase_payloads.get("execution") or {}, "summary")
    publication_summary = nested_mapping(
        phase_payloads.get("publication") or {},
        "summary",
    )
    if phase_payloads.get("execution") and not execution_summary.get(
        "rerun_report_digest"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_smoke_rerun_digest_missing",
                subject="execution.summary.rerun_report_digest",
                message="smoke execution must capture rerun report digest",
            )
        )
    if phase_payloads.get("execution") and not execution_summary.get(
        "repair_session_digest"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_smoke_session_digest_missing",
                subject="execution.summary.repair_session_digest",
                message="smoke execution must capture refreshed repair session digest",
            )
        )
    if phase_payloads.get("publication") and publication_summary.get(
        "published_artifact_count"
    ) != 4:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_repair_rerun_smoke_public_artifact_count_mismatch",
                subject="publication.summary.published_artifact_count",
                message="smoke publication must verify four public repair rerun artifacts",
            )
        )

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    ok = error_count == 0 and all(
        phase_payloads.get(key, {}).get("ok") is True
        for key in ("plan", "execution", "publication")
    )
    report = {
        "schema_version": 1,
        "artifact_kind": PRODUCT_REPAIR_RERUN_SMOKE_REPORT_KIND,
        "generated_at": utc_now_iso(),
        "ok": ok,
        "specgraph_dir": str(specgraph_dir),
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "authority_boundary": {
            "executes_specgraph_make_target": executes_specgraph_make_target,
            "executes_git_commands": False,
            "opens_pull_requests": False,
            "merges_pull_requests": False,
            "writes_ontology_packages": False,
            "accepts_ontology_terms": False,
            "mutates_canonical_specs": False,
            "publishes_private_artifacts": False,
            "candidate_approval_performed": False,
            "git_service_promotion_started": False,
        },
        "phase_reports": {
            "plan": product_repair_smoke_report_ref(plan_path),
            "execution": product_repair_smoke_report_ref(execution_report_path),
            "publication": product_repair_smoke_report_ref(publication_report_path),
        },
        "operations": operations,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "status": "passed" if ok else "failed",
            "error_count": error_count,
            "plan_ok": phase_payloads.get("plan", {}).get("ok") is True,
            "execution_ok": phase_payloads.get("execution", {}).get("ok") is True,
            "publication_ok": phase_payloads.get("publication", {}).get("ok") is True,
            "rerun_report_digest": execution_summary.get("rerun_report_digest"),
            "repair_session_digest": execution_summary.get("repair_session_digest"),
            "manifest_digest": nested_mapping(
                phase_payloads.get("publication") or {},
                "manifest",
            ).get("sha256"),
            "published_artifact_count": publication_summary.get(
                "published_artifact_count",
                0,
            ),
        },
    }
    if not args.no_write_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "status": report["summary"]["status"],
                        "published": str(report["summary"]["published_artifact_count"]),
                    }
                ],
                [("status", "STATUS"), ("published", "PUBLISHED")],
            )
        )
    return 0 if ok else 1


def graph_repository_prepare_plan_diagnostics(
    plan: dict[str, Any],
    *,
    candidate_id: str,
    workspace_dir: Path,
    dry_run: bool,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if plan.get("artifact_kind") != "platform_graph_repository_execution_plan":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_plan_kind_mismatch",
                subject="artifact_kind",
                message="expected platform_graph_repository_execution_plan",
            )
        )
    if plan.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_plan_not_ok",
                subject="ok",
                message="execution plan must be ok before local preparation",
            )
        )
    if plan.get("ready_for_branch") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_plan_not_ready",
                subject="ready_for_branch",
                message="execution plan is not ready for branch preparation",
            )
        )
    if plan.get("canonical_mutations_allowed") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_plan_authority_expanded",
                subject="canonical_mutations_allowed",
                message="plan must not allow canonical mutations",
            )
        )
    if plan.get("tracked_artifacts_written") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_plan_authority_expanded",
                subject="tracked_artifacts_written",
                message="plan must not have written tracked artifacts",
            )
        )
    for key, value in sorted(nested_mapping(plan, "authority_boundary").items()):
        if value is True:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_plan_authority_expanded",
                    subject=f"authority_boundary.{key}",
                    message="report-only plan authority boundary must remain false",
                )
            )

    prepare_branch = None
    operations = plan.get("operations")
    if isinstance(operations, list):
        for operation in operations:
            if isinstance(operation, dict) and operation.get("name") == "prepare_branch":
                prepare_branch = operation
                break
    if not isinstance(prepare_branch, dict) or prepare_branch.get("status") != "ready":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_prepare_branch_not_ready",
                subject="operations.prepare_branch.status",
                message="prepare_branch operation must be ready",
            )
        )

    if not PROJECT_ID_RE.fullmatch(candidate_id):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_candidate_id_invalid",
                subject="candidate_id",
                message=(
                    "candidate id must start with a lowercase letter or digit and "
                    "contain only lowercase letters, digits, '.', '_' or '-'"
                ),
            )
        )

    if not dry_run:
        if workspace_dir.exists() and not workspace_dir.is_dir():
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_workspace_not_directory",
                    subject="workspace_dir",
                    message="workspace path exists but is not a directory",
                )
            )
        elif workspace_dir.exists() and any(workspace_dir.iterdir()):
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_workspace_not_empty",
                    subject="workspace_dir",
                    message="workspace directory must be empty for local preparation",
                )
            )
    return diagnostics


def graph_repository_candidate_branch(contract: dict[str, Any], candidate_id: str) -> str:
    repository_binding = nested_mapping(contract, "repository_binding")
    prefix = repository_binding.get("candidate_branch_prefix")
    if not isinstance(prefix, str) or not prefix:
        prefix = "graph-candidate/"
    return f"{prefix}{candidate_id}"


def graph_repository_branch_name_diagnostics(branch_name: str) -> list[Diagnostic]:
    try:
        completed = subprocess.run(
            ["git", "check-ref-format", "--branch", branch_name],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return [
            Diagnostic(
                level="ERROR",
                code="graph_repository_git_unavailable",
                subject="candidate_branch",
                message=f"cannot validate candidate branch name: {exc}",
            )
        ]
    if completed.returncode == 0:
        return []
    return [
        Diagnostic(
            level="ERROR",
            code="graph_repository_candidate_branch_invalid",
            subject="candidate_branch",
            message=(
                f"candidate branch `{branch_name}` is not a valid Git branch name"
            ),
        )
    ]


def graph_repository_prepare_local(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    workspace_dir = Path(args.workspace_dir)
    candidate_id = args.candidate_id
    plan = load_json_mapping(plan_path, label="graph repository execution plan")
    contract_ref = plan.get("contract_ref")
    contract_path = Path(contract_ref) if isinstance(contract_ref, str) else None
    contract = (
        load_json_mapping(contract_path, label="graph repository contract")
        if contract_path is not None and contract_path.is_file()
        else {}
    )
    branch_name = graph_repository_candidate_branch(contract, candidate_id)
    diagnostics = graph_repository_prepare_plan_diagnostics(
        plan,
        candidate_id=candidate_id,
        workspace_dir=workspace_dir,
        dry_run=args.dry_run,
    )
    diagnostics.extend(graph_repository_branch_name_diagnostics(branch_name))
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    local_files = [
        str(workspace_dir / "candidate_workspace_manifest.json"),
        str(workspace_dir / "graph_repository_local_prepare_report.json"),
    ]
    repository_binding = nested_mapping(contract, "repository_binding")
    default_branch = repository_binding.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        default_branch = "main"

    report = {
        "schema_version": 1,
        "artifact_kind": "platform_graph_repository_local_prepare_report",
        "plan_ref": str(plan_path),
        "ok": error_count == 0,
        "dry_run": args.dry_run,
        "candidate_id": candidate_id,
        "candidate_branch": branch_name,
        "workspace_dir": str(workspace_dir),
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "git_commands_executed": [],
        "pull_requests_opened": [],
        "local_files_written": [] if args.dry_run or error_count else local_files,
        "planned_git_commands": [
            f"git fetch origin {default_branch}",
            f"git worktree add {workspace_dir} -b {branch_name} origin/{default_branch}",
        ],
        "source_artifacts": plan.get("source_artifacts", []),
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "will_write_local_workspace": not args.dry_run and error_count == 0,
        },
    }

    if error_count == 0 and not args.dry_run:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1,
            "artifact_kind": "platform_graph_repository_candidate_workspace_manifest",
            "candidate_id": candidate_id,
            "candidate_branch": branch_name,
            "plan_ref": str(plan_path),
            "source_artifacts": plan.get("source_artifacts", []),
            "authority_boundary": {
                "git_commands_executed": False,
                "pull_requests_opened": False,
                "canonical_specs_mutated": False,
                "ontology_packages_written": False,
            },
        }
        (workspace_dir / "candidate_workspace_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (workspace_dir / "graph_repository_local_prepare_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "candidate_id": candidate_id,
                        "branch": branch_name,
                        "workspace": str(workspace_dir),
                    }
                ],
                [
                    ("candidate_id", "CANDIDATE"),
                    ("branch", "BRANCH"),
                    ("workspace", "WORKSPACE"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def product_candidate_promotion_decision_diagnostics(
    approval_decision: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if approval_decision.get("artifact_kind") != PRODUCT_CANDIDATE_APPROVAL_DECISION_KIND:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_approval_kind_mismatch",
                subject="approval_decision.artifact_kind",
                message="expected candidate_approval_decision",
            )
        )
    if approval_decision.get("contract_ref") != (
        PRODUCT_CANDIDATE_APPROVAL_DECISION_CONTRACT_REF
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_approval_contract_mismatch",
                subject="approval_decision.contract_ref",
                message="expected candidate approval decision contract v0.1",
            )
        )
    for field in (
        "canonical_mutations_allowed",
        "ontology_writes_allowed",
        "tracked_artifacts_written",
    ):
        if approval_decision.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_promotion_approval_authority_expanded",
                    subject=f"approval_decision.{field}",
                    message=f"{field} must be exactly false before promotion handoff",
                )
            )
    authority_boundary = approval_decision.get("authority_boundary")
    if not isinstance(authority_boundary, dict):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_approval_authority_missing",
                subject="approval_decision.authority_boundary",
                message="candidate approval decision must declare authority boundary",
            )
        )
    else:
        for field in PRODUCT_CANDIDATE_PROMOTION_AUTHORITY_FALSE_FIELDS:
            if authority_boundary.get(field) is not False:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code=(
                            "product_candidate_promotion_approval_authority_expanded"
                        ),
                        subject=f"approval_decision.authority_boundary.{field}",
                        message=(
                            f"{field} must be exactly false before promotion handoff"
                        ),
                    )
                )

    decision = nested_mapping(approval_decision, "decision")
    if decision.get("state") != "approved":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_approval_not_approved",
                subject="approval_decision.decision.state",
                message="promotion request handoff requires approved candidate decision",
            )
        )
    readiness = nested_mapping(approval_decision, "readiness")
    if readiness.get("ready") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_approval_not_ready",
                subject="approval_decision.readiness.ready",
                message="promotion request handoff requires ready candidate decision",
            )
        )
    workspace = nested_mapping(approval_decision, "workspace")
    if workspace.get("mode") != "product_idea_to_spec":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_workflow_mismatch",
                subject="approval_decision.workspace.mode",
                message="promotion request handoff requires product_idea_to_spec",
            )
        )
    if workspace.get("repository_role") != "product_spec_workspace":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_repository_role_mismatch",
                subject="approval_decision.workspace.repository_role",
                message="promotion request handoff requires product_spec_workspace",
            )
        )
    candidate = nested_mapping(approval_decision, "candidate")
    if not isinstance(candidate.get("candidate_id"), str) or not candidate.get(
        "candidate_id"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_candidate_missing",
                subject="approval_decision.candidate.candidate_id",
                message="candidate approval decision must include candidate id",
            )
        )
    promotion_request = nested_mapping(approval_decision, "promotion_request")
    if promotion_request.get("platform_artifact_kind") != (
        "platform_graph_repository_promotion_request"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_request_kind_mismatch",
                subject="approval_decision.promotion_request.platform_artifact_kind",
                message=(
                    "candidate approval must target "
                    "platform_graph_repository_promotion_request"
                ),
            )
        )
    if promotion_request.get("requires_git_service_execution") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_git_service_requirement_missing",
                subject="approval_decision.promotion_request.requires_git_service_execution",
                message="candidate approval must explicitly require later Git Service execution",
            )
        )
    if not string_list(promotion_request.get("paths")):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_paths_missing",
                subject="approval_decision.promotion_request.paths",
                message="candidate approval must include approved promotion paths",
            )
        )
    return diagnostics


def product_candidate_promotion_request_execution_diagnostics(
    promotion_request: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if promotion_request.get("artifact_kind") != (
        "platform_graph_repository_promotion_request"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_request_kind_mismatch",
                subject="promotion_request.artifact_kind",
                message="expected platform_graph_repository_promotion_request",
            )
        )
    if promotion_request.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_request_not_ok",
                subject="promotion_request.ok",
                message="promotion request must be ok before product execution",
            )
        )
    if promotion_request.get("workflow_lane") != "product_idea_to_spec":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_request_workflow_mismatch",
                subject="promotion_request.workflow_lane",
                message="product promotion execution requires product_idea_to_spec",
            )
        )
    if promotion_request.get("target_repository_role") != "product_spec_workspace":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_request_repository_role_mismatch",
                subject="promotion_request.target_repository_role",
                message="product promotion execution requires product_spec_workspace",
            )
        )
    if promotion_request.get("authority_profile") != "workspace_owner_controlled":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_request_authority_profile_mismatch",
                subject="promotion_request.authority_profile",
                message="product promotion execution requires workspace_owner_controlled",
            )
        )
    for field in ("canonical_mutations_allowed", "tracked_artifacts_written"):
        if promotion_request.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_promotion_request_authority_expanded",
                    subject=f"promotion_request.{field}",
                    message=f"{field} must be exactly false before execution",
                )
            )
    authority_boundary = promotion_request.get("authority_boundary")
    if not isinstance(authority_boundary, dict):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_request_authority_missing",
                subject="promotion_request.authority_boundary",
                message="promotion request must declare authority boundary",
            )
        )
        return diagnostics
    for field in PRODUCT_CANDIDATE_PROMOTION_REQUEST_AUTHORITY_FALSE_FIELDS:
        if authority_boundary.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_promotion_request_authority_expanded",
                    subject=f"promotion_request.authority_boundary.{field}",
                    message=f"{field} must be exactly false before execution",
                )
            )
    return diagnostics


def product_candidate_promotion_plan_runs_dir(
    *,
    plan_path: Path,
    plan: dict[str, Any],
) -> Path | None:
    raw_runs_dir = plan.get("runs_dir")
    if not isinstance(raw_runs_dir, str) or not raw_runs_dir.strip():
        return None
    runs_dir = Path(raw_runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = plan_path.parent / runs_dir
    return runs_dir.resolve()


def product_candidate_promotion_approval_ref_path(
    *,
    approval_decision_path: Path,
    raw_ref: Any,
) -> Path | None:
    if not isinstance(raw_ref, str) or not raw_ref.strip():
        return None
    ref_path = Path(raw_ref)
    if ref_path.is_absolute():
        return ref_path.resolve()
    decision_dir = approval_decision_path.parent.resolve()
    workspace_root = decision_dir.parent if decision_dir.name == "runs" else decision_dir
    if ref_path.parts and ref_path.parts[0] == "runs":
        return (workspace_root / ref_path).resolve()
    return (decision_dir / ref_path).resolve()


def product_candidate_promotion_plan_source_diagnostics(
    *,
    plan_path: Path,
    plan: dict[str, Any],
    approval_decision_path: Path,
    approval_decision: dict[str, Any],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    plan_runs_dir = product_candidate_promotion_plan_runs_dir(
        plan_path=plan_path,
        plan=plan,
    )
    if plan_runs_dir is None:
        return [
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_plan_runs_dir_missing",
                subject="plan.runs_dir",
                message="execution plan must identify the validated runs directory",
            )
        ]

    refs: list[tuple[str, Any]] = []
    candidate = nested_mapping(approval_decision, "candidate")
    refs.extend(
        [
            (
                "approval_decision.candidate.active_candidate_ref",
                candidate.get("active_candidate_ref"),
            ),
            (
                "approval_decision.candidate.promotion_gate_ref",
                candidate.get("promotion_gate_ref"),
            ),
        ]
    )
    source_artifacts = nested_mapping(approval_decision, "source_artifacts")
    for key in (
        "candidate_approval_gate",
        "repair_session",
        "promotion_gate",
        "platform_repair_execution",
        "platform_repair_publication",
    ):
        refs.append(
            (
                f"approval_decision.source_artifacts.{key}",
                source_artifacts.get(key),
            )
        )

    for subject, raw_ref in refs:
        ref_path = product_candidate_promotion_approval_ref_path(
            approval_decision_path=approval_decision_path,
            raw_ref=raw_ref,
        )
        if ref_path is None:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_promotion_source_ref_missing",
                    subject=subject,
                    message="candidate approval decision must include promotion source refs",
                )
            )
            continue
        if not ref_path.is_relative_to(plan_runs_dir):
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_promotion_source_plan_mismatch",
                    subject=subject,
                    message=(
                        "candidate approval source refs must resolve inside the "
                        "execution plan runs_dir"
                    ),
                )
            )
    return diagnostics


def build_graph_repository_promotion_request_payload(
    *,
    plan_path: Path,
    plan: dict[str, Any],
    contract: dict[str, Any],
    candidate_id: str,
    paths: list[str],
    title: str,
    body: str,
    base: str,
    workflow_lane: str,
    deployment_profile_id: str,
    target_repository_role: str,
    authority_profile: str,
    output_path: Path | None,
    dry_run: bool,
    diagnostics: list[Diagnostic],
) -> dict[str, Any]:
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    branch_name = graph_repository_candidate_branch(contract, candidate_id)
    local_files_written = (
        [str(output_path)]
        if output_path is not None and error_count == 0 and not dry_run
        else []
    )
    return {
        "schema_version": 1,
        "artifact_kind": "platform_graph_repository_promotion_request",
        "generated_at": utc_now_iso(),
        "plan_ref": str(plan_path),
        "ok": error_count == 0,
        "dry_run": dry_run,
        "workflow_lane": workflow_lane,
        "deployment_profile_id": deployment_profile_id,
        "target_repository_role": target_repository_role,
        "authority_profile": authority_profile,
        "candidate_id": candidate_id,
        "candidate_branch": branch_name,
        "commit_paths": paths if error_count == 0 else [],
        "review": {
            "title": title.strip(),
            "body": body.strip(),
            "base_branch": base,
        },
        "requested_operations": [
            "prepare_branch",
            "create_commit",
            "open_review",
        ],
        "source_artifacts": plan.get("source_artifacts", []),
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "write_actions_executed": [],
        "git_commands_executed": [],
        "pull_requests_opened": [],
        "merges_performed": [],
        "read_models_published": [],
        "local_files_written": local_files_written,
        "authority_boundary": {
            "executes_git_commands": False,
            "creates_commits": False,
            "opens_pull_requests": False,
            "merges_pull_requests": False,
            "writes_ontology_packages": False,
            "mutates_canonical_specs": False,
            "publishes_read_models": False,
        },
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "commit_path_count": len(paths) if error_count == 0 else 0,
            "promotion_ready": error_count == 0,
        },
    }


def product_candidate_promotion_request(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    approval_decision_path = Path(args.approval_decision)
    plan = load_json_mapping(plan_path, label="graph repository execution plan")
    approval_decision = load_json_mapping(
        approval_decision_path,
        label="candidate approval decision",
    )
    contract_ref = plan.get("contract_ref")
    contract_path = Path(contract_ref) if isinstance(contract_ref, str) else None
    contract = (
        load_json_mapping(contract_path, label="graph repository contract")
        if contract_path is not None and contract_path.is_file()
        else {}
    )
    candidate = nested_mapping(approval_decision, "candidate")
    workspace = nested_mapping(approval_decision, "workspace")
    decision = nested_mapping(approval_decision, "decision")
    promotion_request = nested_mapping(approval_decision, "promotion_request")
    candidate_id = str(candidate.get("candidate_id") or "")
    paths = string_list(promotion_request.get("paths"))
    branch_name = graph_repository_candidate_branch(contract, candidate_id)
    display_name = str(candidate.get("display_name") or candidate_id).strip()
    title = (
        args.title
        if args.title is not None
        else f"Promote {display_name or candidate_id} candidate spec graph"
    )
    body = (
        args.body
        if args.body is not None
        else (
            str(decision.get("reason") or "").strip()
            or "Review materialized candidate graph from the idea-to-spec flow."
        )
    )
    workflow_lane = str(workspace.get("mode") or "product_idea_to_spec")
    target_repository_role = str(
        workspace.get("repository_role") or "product_spec_workspace"
    )
    deployment_profile_id = args.deployment_profile_id
    authority_profile = args.authority_profile
    diagnostics = [
        *product_candidate_promotion_decision_diagnostics(approval_decision),
        *product_candidate_promotion_plan_source_diagnostics(
            plan_path=plan_path,
            plan=plan,
            approval_decision_path=approval_decision_path,
            approval_decision=approval_decision,
        ),
        *graph_repository_promotion_request_diagnostics(
            plan,
            candidate_id=candidate_id,
            candidate_branch=branch_name,
            paths=paths,
            title=title,
            body=body,
        ),
    ]
    provisional_request = build_graph_repository_promotion_request_payload(
        plan_path=plan_path,
        plan=plan,
        contract=contract,
        candidate_id=candidate_id,
        paths=paths,
        title=title,
        body=body,
        base=args.base,
        workflow_lane=workflow_lane,
        deployment_profile_id=deployment_profile_id,
        target_repository_role=target_repository_role,
        authority_profile=authority_profile,
        output_path=None,
        dry_run=True,
        diagnostics=[],
    )
    diagnostics.extend(
        git_service_candidate_approval_diagnostics(
            approval_decision=approval_decision,
            promotion_request=provisional_request,
        )
    )
    output_path = (
        Path(args.output)
        if args.output
        else plan_path.parent / Path(PRODUCT_CANDIDATE_PROMOTION_DEFAULT_OUTPUTS["request"]).name
    )
    request = build_graph_repository_promotion_request_payload(
        plan_path=plan_path,
        plan=plan,
        contract=contract,
        candidate_id=candidate_id,
        paths=paths,
        title=title,
        body=body,
        base=args.base,
        workflow_lane=workflow_lane,
        deployment_profile_id=deployment_profile_id,
        target_repository_role=target_repository_role,
        authority_profile=authority_profile,
        output_path=output_path,
        dry_run=args.dry_run,
        diagnostics=diagnostics,
    )
    error_count = request["summary"]["error_count"]
    if error_count == 0 and not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(request, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "candidate_id": candidate_id,
                        "branch": request["candidate_branch"],
                        "paths": str(len(paths)),
                    }
                ],
                [
                    ("candidate_id", "CANDIDATE"),
                    ("branch", "BRANCH"),
                    ("paths", "PATHS"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def product_candidate_promotion_materialized_source_dir(
    *,
    explicit: str | None,
    plan_path: Path | None,
    plan: dict[str, Any],
) -> Path | None:
    if explicit:
        return Path(explicit).resolve()
    if plan_path is None:
        return None
    runs_dir = product_candidate_promotion_plan_runs_dir(
        plan_path=plan_path,
        plan=plan,
    )
    if runs_dir is None:
        return None
    return runs_dir / "materialized_candidate_specs"


def product_candidate_promotion_operation(
    *,
    name: str,
    status: str,
    reason: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "evidence": evidence or [],
    }


def product_candidate_promotion_child_report_path(
    child_payload: dict[str, Any] | None,
    *,
    base_dir: Path,
    fallback: Path,
) -> Path:
    if isinstance(child_payload, dict):
        local_files = string_list(child_payload.get("local_files_written"))
        if local_files:
            resolved = resolve_artifact_path(local_files[0], base_dir=base_dir)
            if resolved is not None:
                return resolved
    return fallback


def product_candidate_promotion_execute(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract).resolve()
    promotion_request_path = Path(args.promotion_request).resolve()
    approval_decision_path = Path(args.approval_decision).resolve()
    deployment_profile_path = Path(args.deployment_profile).resolve()
    repository_dir = Path(args.repository_dir).resolve()
    workspace_dir = Path(args.workspace_dir).resolve()
    contract = load_json_mapping(contract_path, label="git service contract")
    promotion_request = load_json_mapping(
        promotion_request_path,
        label="graph repository promotion request",
    )
    approval_decision = load_json_mapping(
        approval_decision_path,
        label="candidate approval decision",
    )
    deployment_profile = load_json_mapping(
        deployment_profile_path,
        label="deployment profile",
    )
    plan_path = resolve_artifact_path(
        promotion_request.get("plan_ref"),
        base_dir=promotion_request_path.parent,
    )
    plan: dict[str, Any] = {}
    if plan_path is not None and plan_path.is_file():
        plan = load_json_mapping(plan_path, label="graph repository execution plan")
    materialized_source_dir = product_candidate_promotion_materialized_source_dir(
        explicit=args.materialized_source_dir,
        plan_path=plan_path,
        plan=plan,
    )
    diagnostics = [
        *product_candidate_promotion_request_execution_diagnostics(
            promotion_request,
        ),
        *product_candidate_promotion_decision_diagnostics(approval_decision),
        *git_service_promotion_request_diagnostics(
            contract=contract,
            promotion_request=promotion_request,
        ),
        *git_service_candidate_approval_diagnostics(
            approval_decision=approval_decision,
            promotion_request=promotion_request,
        ),
        *git_service_deployment_profile_diagnostics(
            profile=deployment_profile,
            promotion_request=promotion_request,
            dry_run=args.dry_run,
        ),
    ]
    if plan_path is None or not plan_path.is_file():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_plan_missing",
                subject="promotion_request.plan_ref",
                message="promotion request plan_ref must point at an execution plan",
            )
        )
    else:
        diagnostics.extend(
            product_candidate_promotion_plan_source_diagnostics(
                plan_path=plan_path,
                plan=plan,
                approval_decision_path=approval_decision_path,
                approval_decision=approval_decision,
            )
        )

    output_path = (
        Path(args.output).resolve()
        if args.output
        else promotion_request_path.parent
        / Path(PRODUCT_CANDIDATE_PROMOTION_DEFAULT_OUTPUTS["execution"]).name
    )
    git_service_output_path = (
        Path(args.git_service_output).resolve()
        if args.git_service_output
        else output_path.parent / "git_service_promotion_execution_report.json"
        if args.dry_run
        else workspace_dir / ".platform" / "git_service_promotion_execution_report.json"
    )
    candidate_id = str(promotion_request.get("candidate_id") or "")
    child_payload: dict[str, Any] | None = None
    child_result: dict[str, Any] | None = None
    child_diagnostic: Diagnostic | None = None
    preflight_error_count = sum(
        1 for diagnostic in diagnostics if diagnostic.level == "ERROR"
    )
    git_service_command = [
        "git-service",
        "execute-promotion",
        "--contract",
        str(contract_path),
        "--promotion-request",
        str(promotion_request_path),
        "--approval-decision",
        str(approval_decision_path),
        "--deployment-profile",
        str(deployment_profile_path),
        "--repository-dir",
        str(repository_dir),
        "--workspace-dir",
        str(workspace_dir),
        "--output",
        str(git_service_output_path),
        "--format",
        "json",
    ]
    if materialized_source_dir is not None:
        git_service_command.extend(
            ["--materialized-source-dir", str(materialized_source_dir)]
        )
    if args.message:
        git_service_command.extend(["--message", args.message])
    if args.repo:
        git_service_command.extend(["--repo", args.repo])
    if args.gh_bin:
        git_service_command.extend(["--gh-bin", args.gh_bin])
    if args.open_review_dry_run:
        git_service_command.append("--open-review-dry-run")
    if args.dry_run:
        git_service_command.append("--dry-run")

    if preflight_error_count == 0:
        child_payload, child_result, child_diagnostic = run_platform_json_command(
            git_service_command
        )
        if child_diagnostic is not None:
            diagnostics.append(child_diagnostic)

    child_ok = child_payload is not None and child_payload.get("ok") is True
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    ok = error_count == 0 and child_ok
    child_operations = []
    if isinstance(child_payload, dict) and isinstance(child_payload.get("operations"), list):
        child_operations = [
            operation
            for operation in child_payload.get("operations", [])
            if isinstance(operation, dict)
        ]
    statuses = {
        str(operation.get("name")): str(operation.get("status"))
        for operation in child_operations
    }
    worktree_prepared = statuses.get("prepare_worktree") in {"succeeded", "dry_run"}
    commit_created = statuses.get("commit_candidate") == "succeeded"
    review_opened = statuses.get("open_review") == "succeeded"
    operations = [
        product_candidate_promotion_operation(
            name="validate_product_promotion_handoff",
            status="ready" if preflight_error_count == 0 else "blocked",
            reason=(
                "promotion request and candidate approval decision are valid"
                if preflight_error_count == 0
                else "promotion handoff validation failed"
            ),
            evidence=[
                str(promotion_request_path),
                str(approval_decision_path),
            ],
        ),
        product_candidate_promotion_operation(
            name="execute_git_service_promotion",
            status=(
                "dry_run"
                if child_ok and args.dry_run
                else "succeeded"
                if child_ok
                else "skipped_preflight_failed"
                if preflight_error_count > 0
                else "failed"
            ),
            reason=(
                "Git Service promotion executor completed"
                if child_ok and not args.dry_run
                else "dry_run"
                if child_ok and args.dry_run
                else "validation failed before Git Service execution"
                if preflight_error_count > 0
                else "Git Service promotion executor failed"
            ),
            evidence=["git-service execute-promotion"],
        ),
        product_candidate_promotion_operation(
            name="publish_read_model",
            status="blocked_until_review_merge",
            reason=(
                "read model publication is a separate post-review step after PR merge"
            ),
            evidence=["git-service finalize-promotion"],
        ),
    ]
    report = {
        "schema_version": 1,
        "artifact_kind": PRODUCT_CANDIDATE_PROMOTION_EXECUTION_REPORT_KIND,
        "generated_at": utc_now_iso(),
        "promotion_request_ref": str(promotion_request_path),
        "approval_decision_ref": str(approval_decision_path),
        "deployment_profile_ref": str(deployment_profile_path),
        "contract_ref": str(contract_path),
        "graph_repository_plan_ref": None if plan_path is None else str(plan_path),
        "git_service_execution_report_ref": str(git_service_output_path),
        "ok": ok,
        "dry_run": args.dry_run,
        "open_review_dry_run": args.open_review_dry_run,
        "workflow_lane": promotion_request.get("workflow_lane"),
        "candidate_id": candidate_id,
        "candidate_branch": promotion_request.get("candidate_branch"),
        "repository_dir": str(repository_dir),
        "workspace_dir": str(workspace_dir),
        "materialized_source_dir": (
            None if materialized_source_dir is None else str(materialized_source_dir)
        ),
        "git_service_command": git_service_command,
        "git_service_command_result": child_result,
        "git_service_execution": {
            "artifact_kind": child_payload.get("artifact_kind")
            if isinstance(child_payload, dict)
            else None,
            "ok": child_payload.get("ok") if isinstance(child_payload, dict) else None,
            "dry_run": child_payload.get("dry_run")
            if isinstance(child_payload, dict)
            else None,
            "open_review_dry_run": child_payload.get("open_review_dry_run")
            if isinstance(child_payload, dict)
            else None,
            "candidate_ref": child_payload.get("candidate_ref")
            if isinstance(child_payload, dict)
            else None,
            "report_refs": child_payload.get("report_refs")
            if isinstance(child_payload, dict)
            else {},
            "operations": child_operations,
            "copied_materialized_files": child_payload.get("copied_materialized_files")
            if isinstance(child_payload, dict)
            else [],
        },
        "operations": operations,
        "authority_boundary": {
            "specspace_direct_git_write": False,
            "controlled_git_service_execution": not args.dry_run and child_ok,
            "creates_candidate_worktree_or_branch": (
                not args.dry_run and worktree_prepared
            ),
            "creates_candidate_commit": not args.dry_run and commit_created,
            "opens_pull_requests": (
                not args.dry_run and not args.open_review_dry_run and review_opened
            ),
            "merges_pull_requests": False,
            "publishes_read_models": False,
            "canonical_spec_mutation_without_review": False,
            "ontology_package_write": False,
            "ontology_term_acceptance": False,
            "private_artifact_publication": False,
        },
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "status": "completed"
            if ok and not args.dry_run
            else "dry_run"
            if ok and args.dry_run
            else "failed",
            "error_count": error_count,
            "child_operation_count": len(child_operations),
            "worktree_prepared": worktree_prepared,
            "commit_created": commit_created,
            "review_opened": review_opened,
            "read_model_published": False,
        },
    }
    if not args.no_write_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "candidate_id": candidate_id,
                        "status": report["summary"]["status"],
                        "branch": str(promotion_request.get("candidate_branch") or ""),
                    }
                ],
                [
                    ("candidate_id", "CANDIDATE"),
                    ("status", "STATUS"),
                    ("branch", "BRANCH"),
                ],
            )
        )
    return 0 if ok else 1


def product_candidate_promotion_execution_report_diagnostics(
    execution_report: dict[str, Any],
    *,
    base_dir: Path,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if execution_report.get("artifact_kind") != (
        PRODUCT_CANDIDATE_PROMOTION_EXECUTION_REPORT_KIND
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_execution_kind_mismatch",
                subject="execution_report.artifact_kind",
                message=(
                    "expected "
                    f"{PRODUCT_CANDIDATE_PROMOTION_EXECUTION_REPORT_KIND}"
                ),
            )
        )
    if execution_report.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_execution_not_ok",
                subject="execution_report.ok",
                message="product promotion execution must be ok before review status",
            )
        )
    if execution_report.get("dry_run") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_execution_dry_run",
                subject="execution_report.dry_run",
                message="post-review status requires non-dry-run promotion execution",
            )
        )
    if execution_report.get("open_review_dry_run") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_open_review_dry_run",
                subject="execution_report.open_review_dry_run",
                message="post-review status requires a real opened review",
            )
        )
    if execution_report.get("workflow_lane") != "product_idea_to_spec":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_execution_workflow_mismatch",
                subject="execution_report.workflow_lane",
                message="post-review publication requires product_idea_to_spec",
            )
        )
    summary = nested_mapping(execution_report, "summary")
    if summary.get("review_opened") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_review_not_opened",
                subject="execution_report.summary.review_opened",
                message="review status requires a previously opened review",
            )
        )
    workspace_dir = execution_report.get("workspace_dir")
    if not isinstance(workspace_dir, str) or not workspace_dir.strip():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_workspace_missing",
                subject="execution_report.workspace_dir",
                message="execution report must include candidate workspace_dir",
            )
        )
    elif not Path(workspace_dir).is_dir():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_workspace_missing",
                subject="execution_report.workspace_dir",
                message="candidate workspace_dir must exist for review status output",
            )
        )
    git_service_execution = nested_mapping(execution_report, "git_service_execution")
    report_refs = nested_mapping(git_service_execution, "report_refs")
    open_review_ref = report_refs.get("open_review")
    if not isinstance(open_review_ref, str) or not open_review_ref.strip():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_open_review_ref_missing",
                subject="execution_report.git_service_execution.report_refs.open_review",
                message="execution report must reference the open review report",
            )
        )
    else:
        open_review_path = resolve_artifact_path(open_review_ref, base_dir=base_dir)
        if open_review_path is None or not open_review_path.is_file():
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_promotion_open_review_report_missing",
                    subject="execution_report.git_service_execution.report_refs.open_review",
                    message="open review report ref must point at an existing file",
                )
            )
    authority_boundary = execution_report.get("authority_boundary")
    if not isinstance(authority_boundary, dict):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_execution_authority_missing",
                subject="execution_report.authority_boundary",
                message="execution report must declare authority boundary",
            )
        )
        return diagnostics
    for field in PRODUCT_CANDIDATE_PROMOTION_EXECUTION_AUTHORITY_FALSE_FIELDS:
        if authority_boundary.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_promotion_execution_authority_expanded",
                    subject=f"execution_report.authority_boundary.{field}",
                    message=f"{field} must be exactly false before review status",
                )
            )
    return diagnostics


def product_candidate_promotion_review_status_report_diagnostics(
    review_status_report: dict[str, Any],
    *,
    base_dir: Path,
    require_merged: bool,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if review_status_report.get("artifact_kind") != (
        PRODUCT_CANDIDATE_PROMOTION_REVIEW_STATUS_REPORT_KIND
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_review_status_kind_mismatch",
                subject="review_status_report.artifact_kind",
                message=(
                    "expected "
                    f"{PRODUCT_CANDIDATE_PROMOTION_REVIEW_STATUS_REPORT_KIND}"
                ),
            )
        )
    if review_status_report.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_review_status_not_ok",
                subject="review_status_report.ok",
                message="product review status must be ok before read-model publish",
            )
        )
    if review_status_report.get("workflow_lane") != "product_idea_to_spec":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_review_status_workflow_mismatch",
                subject="review_status_report.workflow_lane",
                message="read-model publication requires product_idea_to_spec",
            )
        )
    if require_merged and review_status_report.get("review_state") != "merged":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_review_not_merged",
                subject="review_status_report.review_state",
                message="read-model publication requires a merged product review",
            )
        )
    graph_report_ref = review_status_report.get("graph_repository_review_status_report_ref")
    if not isinstance(graph_report_ref, str) or not graph_report_ref.strip():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_graph_review_status_ref_missing",
                subject="review_status_report.graph_repository_review_status_report_ref",
                message="product review status must reference the generic review status report",
            )
        )
    else:
        graph_report_path = resolve_artifact_path(graph_report_ref, base_dir=base_dir)
        if graph_report_path is None or not graph_report_path.is_file():
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_promotion_graph_review_status_report_missing",
                    subject="review_status_report.graph_repository_review_status_report_ref",
                    message="generic graph repository review status report must exist",
                )
            )
    authority_boundary = review_status_report.get("authority_boundary")
    if not isinstance(authority_boundary, dict):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="product_candidate_promotion_review_authority_missing",
                subject="review_status_report.authority_boundary",
                message="product review status must declare authority boundary",
            )
        )
        return diagnostics
    for field in PRODUCT_CANDIDATE_PROMOTION_REVIEW_AUTHORITY_FALSE_FIELDS:
        if authority_boundary.get(field) is not False:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="product_candidate_promotion_review_authority_expanded",
                    subject=f"review_status_report.authority_boundary.{field}",
                    message=f"{field} must be exactly false before read-model publish",
                )
            )
    return diagnostics


def product_candidate_promotion_review_status(args: argparse.Namespace) -> int:
    execution_report_path = Path(args.execution_report).resolve()
    execution_report = load_json_mapping(
        execution_report_path,
        label="product candidate promotion execution report",
    )
    diagnostics = product_candidate_promotion_execution_report_diagnostics(
        execution_report,
        base_dir=execution_report_path.parent,
    )
    preflight_error_count = sum(
        1 for diagnostic in diagnostics if diagnostic.level == "ERROR"
    )
    git_service_execution = nested_mapping(execution_report, "git_service_execution")
    report_refs = nested_mapping(git_service_execution, "report_refs")
    open_review_report_path = resolve_artifact_path(
        report_refs.get("open_review"),
        base_dir=execution_report_path.parent,
    )
    workspace_dir = Path(str(execution_report.get("workspace_dir") or "")).resolve()
    output_path = (
        Path(args.output).resolve()
        if args.output
        else execution_report_path.parent
        / Path(PRODUCT_CANDIDATE_PROMOTION_DEFAULT_OUTPUTS["review_status"]).name
    )
    graph_repository_report_path = (
        workspace_dir
        / ".platform"
        / "graph_repository_review_status_report.json"
    )
    child_payload: dict[str, Any] | None = None
    child_result: dict[str, Any] | None = None
    child_diagnostic: Diagnostic | None = None
    command: list[str] = []
    if preflight_error_count == 0 and open_review_report_path is not None:
        command = [
            "graph-repository",
            "review-status",
            "--open-review-report",
            str(open_review_report_path),
            "--worktree-dir",
            str(workspace_dir),
            "--gh-bin",
            args.gh_bin,
            "--format",
            "json",
        ]
        if args.repo:
            command.extend(["--repo", args.repo])
        child_payload, child_result, child_diagnostic = run_platform_json_command(
            command
        )
        if child_diagnostic is not None:
            diagnostics.append(child_diagnostic)

    child_ok = child_payload is not None and child_payload.get("ok") is True
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    ok = error_count == 0 and child_ok
    review_state = (
        child_payload.get("review_state")
        if isinstance(child_payload, dict)
        else "unknown"
    )
    graph_repository_report_path = product_candidate_promotion_child_report_path(
        child_payload,
        base_dir=workspace_dir,
        fallback=graph_repository_report_path,
    )
    review_merged = review_state == "merged"
    operations = [
        product_candidate_promotion_operation(
            name="validate_product_promotion_execution",
            status="ready" if preflight_error_count == 0 else "blocked",
            reason=(
                "product promotion execution is ready for review status"
                if preflight_error_count == 0
                else "product promotion execution validation failed"
            ),
            evidence=[str(execution_report_path)],
        ),
        product_candidate_promotion_operation(
            name="inspect_review_status",
            status=(
                "succeeded"
                if child_ok
                else "skipped_preflight_failed"
                if preflight_error_count > 0
                else "failed"
            ),
            reason=(
                "graph repository review status inspected"
                if child_ok
                else "validation failed before review status inspection"
                if preflight_error_count > 0
                else "graph repository review status inspection failed"
            ),
            evidence=command or ["graph-repository review-status"],
        ),
        product_candidate_promotion_operation(
            name="publish_read_model",
            status="ready" if review_merged else "blocked_until_review_merge",
            reason=(
                "review is merged and read-model publication may be requested"
                if review_merged
                else "read-model publication waits for merged review"
            ),
            evidence=[str(graph_repository_report_path)],
        ),
    ]
    report = {
        "schema_version": 1,
        "artifact_kind": PRODUCT_CANDIDATE_PROMOTION_REVIEW_STATUS_REPORT_KIND,
        "generated_at": utc_now_iso(),
        "promotion_execution_report_ref": str(execution_report_path),
        "graph_repository_review_status_report_ref": str(
            graph_repository_report_path
        ),
        "ok": ok,
        "workflow_lane": execution_report.get("workflow_lane"),
        "candidate_id": execution_report.get("candidate_id"),
        "candidate_branch": execution_report.get("candidate_branch"),
        "workspace_dir": str(workspace_dir),
        "review_state": review_state,
        "review_decision": child_payload.get("review_decision")
        if isinstance(child_payload, dict)
        else None,
        "pull_request": child_payload.get("pull_request")
        if isinstance(child_payload, dict)
        else {},
        "graph_repository_command": command,
        "graph_repository_command_result": child_result,
        "graph_repository_review_status": {
            "artifact_kind": child_payload.get("artifact_kind")
            if isinstance(child_payload, dict)
            else None,
            "ok": child_payload.get("ok") if isinstance(child_payload, dict) else None,
            "review_url": child_payload.get("review_url")
            if isinstance(child_payload, dict)
            else None,
            "review_state": review_state,
            "summary": child_payload.get("summary")
            if isinstance(child_payload, dict)
            else {},
        },
        "operations": operations,
        "authority_boundary": {
            "specspace_direct_git_write": False,
            "executes_git_commands": False,
            "opens_pull_requests": False,
            "merges_pull_requests": False,
            "publishes_read_models": False,
            "canonical_spec_mutation_without_review": False,
            "ontology_package_write": False,
            "ontology_term_acceptance": False,
            "private_artifact_publication": False,
        },
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "status": "ready_for_read_model_publication"
            if ok and review_merged
            else "waiting_for_review_merge"
            if ok
            else "failed",
            "error_count": error_count,
            "review_merged": review_merged,
            "read_model_published": False,
        },
    }
    if not args.no_write_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "candidate_id": str(report["candidate_id"] or ""),
                        "review_state": str(review_state),
                        "status": str(report["summary"]["status"]),
                    }
                ],
                [
                    ("candidate_id", "CANDIDATE"),
                    ("review_state", "REVIEW"),
                    ("status", "STATUS"),
                ],
            )
        )
    return 0 if ok else 1


def product_candidate_promotion_publish_read_model(
    args: argparse.Namespace,
) -> int:
    review_status_report_path = Path(args.review_status_report).resolve()
    review_status_report = load_json_mapping(
        review_status_report_path,
        label="product candidate promotion review status report",
    )
    diagnostics = product_candidate_promotion_review_status_report_diagnostics(
        review_status_report,
        base_dir=review_status_report_path.parent,
        require_merged=True,
    )
    preflight_error_count = sum(
        1 for diagnostic in diagnostics if diagnostic.level == "ERROR"
    )
    graph_repository_report_path = resolve_artifact_path(
        review_status_report.get("graph_repository_review_status_report_ref"),
        base_dir=review_status_report_path.parent,
    )
    bundle_dir = Path(args.bundle_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_path = (
        Path(args.output).resolve()
        if args.output
        else review_status_report_path.parent
        / Path(
            PRODUCT_CANDIDATE_PROMOTION_DEFAULT_OUTPUTS[
                "read_model_publication"
            ]
        ).name
    )
    graph_repository_publish_report_path = (
        output_dir
        / ".platform"
        / "graph_repository_publish_read_model_report.json"
    )
    child_payload: dict[str, Any] | None = None
    child_result: dict[str, Any] | None = None
    child_diagnostic: Diagnostic | None = None
    command: list[str] = []
    if preflight_error_count == 0 and graph_repository_report_path is not None:
        command = [
            "graph-repository",
            "publish-read-model",
            "--review-status-report",
            str(graph_repository_report_path),
            "--bundle-dir",
            str(bundle_dir),
            "--output-dir",
            str(output_dir),
            "--manifest-name",
            args.manifest_name,
            "--format",
            "json",
        ]
        if args.dry_run:
            command.append("--dry-run")
        child_payload, child_result, child_diagnostic = run_platform_json_command(
            command
        )
        if child_diagnostic is not None:
            diagnostics.append(child_diagnostic)

    child_ok = child_payload is not None and child_payload.get("ok") is True
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    published = (
        child_ok
        and not args.dry_run
        and nested_mapping(child_payload, "summary").get("published") is True
    )
    graph_repository_publish_report_path = product_candidate_promotion_child_report_path(
        child_payload,
        base_dir=output_dir,
        fallback=graph_repository_publish_report_path,
    )
    ok = error_count == 0 and child_ok
    operations = [
        product_candidate_promotion_operation(
            name="validate_product_review_status",
            status="ready" if preflight_error_count == 0 else "blocked",
            reason=(
                "product review is merged and ready for read-model publication"
                if preflight_error_count == 0
                else "product review status validation failed"
            ),
            evidence=[str(review_status_report_path)],
        ),
        product_candidate_promotion_operation(
            name="publish_read_model",
            status=(
                "dry_run"
                if child_ok and args.dry_run
                else "succeeded"
                if published
                else "skipped_preflight_failed"
                if preflight_error_count > 0
                else "failed"
            ),
            reason=(
                "public-safe read model published"
                if published
                else "dry_run"
                if child_ok and args.dry_run
                else "validation failed before read-model publication"
                if preflight_error_count > 0
                else "read-model publication failed"
            ),
            evidence=command or ["graph-repository publish-read-model"],
        ),
    ]
    report = {
        "schema_version": 1,
        "artifact_kind": PRODUCT_CANDIDATE_PROMOTION_READ_MODEL_PUBLICATION_REPORT_KIND,
        "generated_at": utc_now_iso(),
        "product_review_status_report_ref": str(review_status_report_path),
        "graph_repository_review_status_report_ref": None
        if graph_repository_report_path is None
        else str(graph_repository_report_path),
        "graph_repository_publish_read_model_report_ref": str(
            graph_repository_publish_report_path
        ),
        "ok": ok,
        "dry_run": args.dry_run,
        "workflow_lane": review_status_report.get("workflow_lane"),
        "candidate_id": review_status_report.get("candidate_id"),
        "candidate_branch": review_status_report.get("candidate_branch"),
        "review_state": review_status_report.get("review_state"),
        "bundle_dir": str(bundle_dir),
        "output_dir": str(output_dir),
        "manifest_name": args.manifest_name,
        "graph_repository_command": command,
        "graph_repository_command_result": child_result,
        "graph_repository_publish_read_model": {
            "artifact_kind": child_payload.get("artifact_kind")
            if isinstance(child_payload, dict)
            else None,
            "ok": child_payload.get("ok") if isinstance(child_payload, dict) else None,
            "dry_run": child_payload.get("dry_run")
            if isinstance(child_payload, dict)
            else None,
            "review_state": child_payload.get("review_state")
            if isinstance(child_payload, dict)
            else review_status_report.get("review_state"),
            "read_models_published": child_payload.get("read_models_published")
            if isinstance(child_payload, dict)
            else [],
            "summary": child_payload.get("summary")
            if isinstance(child_payload, dict)
            else {},
        },
        "operations": operations,
        "authority_boundary": {
            "specspace_direct_git_write": False,
            "executes_git_commands": False,
            "opens_pull_requests": False,
            "merges_pull_requests": False,
            "publishes_read_models": published,
            "canonical_spec_mutation_without_review": False,
            "ontology_package_write": False,
            "ontology_term_acceptance": False,
            "private_artifact_publication": False,
        },
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "status": "published"
            if published
            else "dry_run"
            if ok and args.dry_run
            else "failed",
            "error_count": error_count,
            "review_merged": review_status_report.get("review_state") == "merged",
            "read_model_published": published,
            "published_manifest": (
                str(output_dir / args.manifest_name) if published else None
            ),
        },
    }
    if not args.no_write_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "candidate_id": str(report["candidate_id"] or ""),
                        "status": str(report["summary"]["status"]),
                        "manifest": str(report["summary"]["published_manifest"] or ""),
                    }
                ],
                [
                    ("candidate_id", "CANDIDATE"),
                    ("status", "STATUS"),
                    ("manifest", "MANIFEST"),
                ],
            )
        )
    return 0 if ok else 1


def graph_repository_promotion_path_allowed(raw_path: str) -> bool:
    normalized = raw_path.replace("\\", "/")
    return any(
        normalized.startswith(prefix)
        for prefix in GRAPH_REPOSITORY_PROMOTION_PATH_PREFIXES
    )


def graph_repository_promotion_request_diagnostics(
    plan: dict[str, Any],
    *,
    candidate_id: str,
    candidate_branch: str,
    paths: list[str],
    title: str,
    body: str,
) -> list[Diagnostic]:
    diagnostics = [
        *graph_repository_prepare_plan_diagnostics(
            plan,
            candidate_id=candidate_id,
            workspace_dir=Path("."),
            dry_run=True,
        ),
        *graph_repository_branch_name_diagnostics(candidate_branch),
        *graph_repository_relative_paths_diagnostics(paths),
    ]
    for index, raw_path in enumerate(paths):
        if Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
            continue
        if graph_repository_promotion_path_allowed(raw_path):
            continue
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_promotion_path_not_allowed",
                subject=f"path[{index}]",
                message=(
                    "promotion request paths must be under specs/, "
                    "docs/proposals/, or runs/"
                ),
            )
        )
    if not title.strip():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_promotion_title_missing",
                subject="title",
                message="promotion request must include a review title",
            )
        )
    if not body.strip():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_promotion_body_missing",
                subject="body",
                message="promotion request must include a review body",
            )
        )
    return diagnostics


def graph_repository_promotion_request(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    plan = load_json_mapping(plan_path, label="graph repository execution plan")
    contract_ref = plan.get("contract_ref")
    contract_path = Path(contract_ref) if isinstance(contract_ref, str) else None
    contract = (
        load_json_mapping(contract_path, label="graph repository contract")
        if contract_path is not None and contract_path.is_file()
        else {}
    )
    candidate_id = args.candidate_id
    branch_name = graph_repository_candidate_branch(contract, candidate_id)
    paths = list(args.path or [])
    diagnostics = graph_repository_promotion_request_diagnostics(
        plan,
        candidate_id=candidate_id,
        candidate_branch=branch_name,
        paths=paths,
        title=args.title,
        body=args.body,
    )
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    output_path = Path(args.output) if args.output else None
    local_files_written = (
        [str(output_path)]
        if output_path is not None and error_count == 0 and not args.dry_run
        else []
    )
    request = {
        "schema_version": 1,
        "artifact_kind": "platform_graph_repository_promotion_request",
        "generated_at": utc_now_iso(),
        "plan_ref": str(plan_path),
        "ok": error_count == 0,
        "dry_run": args.dry_run,
        "workflow_lane": args.workflow_lane,
        "deployment_profile_id": args.deployment_profile_id,
        "target_repository_role": args.target_repository_role,
        "authority_profile": args.authority_profile,
        "candidate_id": candidate_id,
        "candidate_branch": branch_name,
        "commit_paths": paths if error_count == 0 else [],
        "review": {
            "title": args.title.strip(),
            "body": args.body.strip(),
            "base_branch": args.base,
        },
        "requested_operations": [
            "prepare_branch",
            "create_commit",
            "open_review",
        ],
        "source_artifacts": plan.get("source_artifacts", []),
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "write_actions_executed": [],
        "git_commands_executed": [],
        "pull_requests_opened": [],
        "merges_performed": [],
        "read_models_published": [],
        "local_files_written": local_files_written,
        "authority_boundary": {
            "executes_git_commands": False,
            "creates_commits": False,
            "opens_pull_requests": False,
            "merges_pull_requests": False,
            "writes_ontology_packages": False,
            "mutates_canonical_specs": False,
            "publishes_read_models": False,
        },
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "commit_path_count": len(paths) if error_count == 0 else 0,
            "promotion_ready": error_count == 0,
        },
    }

    if output_path is not None and error_count == 0 and not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(request, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "candidate_id": candidate_id,
                        "branch": branch_name,
                        "paths": str(len(paths)),
                    }
                ],
                [
                    ("candidate_id", "CANDIDATE"),
                    ("branch", "BRANCH"),
                    ("paths", "PATHS"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def graph_repository_repository_diagnostics(repository_dir: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not repository_dir.is_dir():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repository_missing",
                subject="repository_dir",
                message="repository directory must exist before worktree preparation",
            )
        )
    elif not (repository_dir / ".git").exists():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_repository_not_git_checkout",
                subject="repository_dir",
                message="repository directory must be a Git checkout",
            )
        )
    return diagnostics


def run_graph_repository_command(
    command: list[str],
    *,
    cwd: Path | None = None,
) -> tuple[dict[str, Any], Diagnostic | None]:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result = {
        "command": command,
        "cwd": None if cwd is None else str(cwd),
        "returncode": completed.returncode,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }
    if completed.returncode == 0:
        return result, None
    return result, Diagnostic(
        level="ERROR",
        code="graph_repository_git_command_failed",
        subject=command[0],
        message=(
            f"command failed with exit code {completed.returncode}: "
            f"{' '.join(command)}"
        ),
    )


def graph_repository_prepare_worktree(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    repository_dir = Path(args.repository_dir).resolve()
    workspace_dir = Path(args.workspace_dir).resolve()
    candidate_id = args.candidate_id
    plan = load_json_mapping(plan_path, label="graph repository execution plan")
    contract_ref = plan.get("contract_ref")
    contract_path = Path(contract_ref) if isinstance(contract_ref, str) else None
    contract = (
        load_json_mapping(contract_path, label="graph repository contract")
        if contract_path is not None and contract_path.is_file()
        else {}
    )
    repository_binding = nested_mapping(contract, "repository_binding")
    default_branch = repository_binding.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        default_branch = "main"

    branch_name = graph_repository_candidate_branch(contract, candidate_id)
    diagnostics = [
        *graph_repository_prepare_plan_diagnostics(
            plan,
            candidate_id=candidate_id,
            workspace_dir=workspace_dir,
            dry_run=args.dry_run,
        ),
        *graph_repository_repository_diagnostics(repository_dir),
    ]
    git_commands = [
        ["git", "-C", str(repository_dir), "fetch", "origin", default_branch],
        [
            "git",
            "-C",
            str(repository_dir),
            "worktree",
            "add",
            str(workspace_dir),
            "-b",
            branch_name,
            f"origin/{default_branch}",
        ],
    ]
    command_results: list[dict[str, Any]] = []
    preflight_error_count = sum(
        1 for diagnostic in diagnostics if diagnostic.level == "ERROR"
    )

    if preflight_error_count == 0 and not args.dry_run:
        workspace_dir.parent.mkdir(parents=True, exist_ok=True)
        for command in git_commands:
            command_result, diagnostic = run_graph_repository_command(command)
            command_results.append(command_result)
            if diagnostic is not None:
                diagnostics.append(diagnostic)
                break

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    report_path = (
        workspace_dir
        / ".platform"
        / "graph_repository_worktree_prepare_report.json"
    )
    local_files_written: list[str] = []
    if error_count == 0 and not args.dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        local_files_written.append(str(report_path))

    report = {
        "schema_version": 1,
        "artifact_kind": "platform_graph_repository_worktree_prepare_report",
        "plan_ref": str(plan_path),
        "ok": error_count == 0,
        "dry_run": args.dry_run,
        "candidate_id": candidate_id,
        "candidate_branch": branch_name,
        "repository_dir": str(repository_dir),
        "workspace_dir": str(workspace_dir),
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "git_commands_planned": git_commands,
        "git_commands_executed": [] if args.dry_run else command_results,
        "pull_requests_opened": [],
        "commits_created": [],
        "merges_performed": [],
        "local_files_written": local_files_written,
        "source_artifacts": plan.get("source_artifacts", []),
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "git_command_count": len(command_results),
            "worktree_created": (
                not args.dry_run
                and error_count == 0
                and (workspace_dir / ".git").exists()
            ),
        },
    }

    if error_count == 0 and not args.dry_run:
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "candidate_id": candidate_id,
                        "branch": branch_name,
                        "workspace": str(workspace_dir),
                    }
                ],
                [
                    ("candidate_id", "CANDIDATE"),
                    ("branch", "BRANCH"),
                    ("workspace", "WORKTREE"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def graph_repository_relative_paths_diagnostics(paths: list[str]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not paths:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_commit_paths_missing",
                subject="path",
                message="at least one explicit relative path is required",
            )
        )
    for index, raw_path in enumerate(paths):
        path = Path(raw_path)
        if path.is_absolute() or ".." in path.parts:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_commit_path_outside_worktree",
                    subject=f"path[{index}]",
                    message="commit paths must be relative and stay inside the worktree",
                )
            )
    return diagnostics


def graph_repository_commit_preflight_diagnostics(
    prepare_report: dict[str, Any],
    *,
    worktree_dir: Path,
    paths: list[str],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if prepare_report.get("artifact_kind") != (
        "platform_graph_repository_worktree_prepare_report"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_prepare_report_kind_mismatch",
                subject="artifact_kind",
                message="expected platform_graph_repository_worktree_prepare_report",
            )
        )
    if prepare_report.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_prepare_report_not_ok",
                subject="ok",
                message="worktree prepare report must be ok before commit",
            )
        )
    if not worktree_dir.is_dir() or not (worktree_dir / ".git").exists():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_worktree_missing",
                subject="worktree_dir",
                message="worktree directory must be an existing Git worktree",
            )
        )
    for diagnostic in graph_repository_relative_paths_diagnostics(paths):
        diagnostics.append(diagnostic)
    for index, raw_path in enumerate(paths):
        if (worktree_dir / raw_path).exists():
            continue
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_commit_path_missing",
                subject=f"path[{index}]",
                message="commit path must exist inside the worktree",
            )
        )
    return diagnostics


def git_stdout(command: list[str]) -> tuple[str | None, Diagnostic | None]:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode == 0:
        return completed.stdout.strip(), None
    return None, Diagnostic(
        level="ERROR",
        code="graph_repository_git_command_failed",
        subject=command[0],
        message=(
            f"command failed with exit code {completed.returncode}: "
            f"{' '.join(command)}"
        ),
    )


def graph_repository_commit_worktree(args: argparse.Namespace) -> int:
    prepare_report_path = Path(args.prepare_report)
    worktree_dir = Path(args.worktree_dir)
    paths = list(args.path or [])
    prepare_report = load_json_mapping(
        prepare_report_path,
        label="graph repository worktree prepare report",
    )
    diagnostics = graph_repository_commit_preflight_diagnostics(
        prepare_report,
        worktree_dir=worktree_dir,
        paths=paths,
    )
    command_results: list[dict[str, Any]] = []
    candidate_branch = prepare_report.get("candidate_branch")

    preflight_error_count = sum(
        1 for diagnostic in diagnostics if diagnostic.level == "ERROR"
    )
    current_branch: str | None = None
    commit_sha: str | None = None
    if preflight_error_count == 0:
        current_branch, diagnostic = git_stdout(
            ["git", "-C", str(worktree_dir), "rev-parse", "--abbrev-ref", "HEAD"]
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        elif current_branch != candidate_branch:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_worktree_branch_mismatch",
                    subject="worktree_dir",
                    message=(
                        f"expected branch `{candidate_branch}` but found "
                        f"`{current_branch}`"
                    ),
                )
            )

    if not any(diagnostic.level == "ERROR" for diagnostic in diagnostics):
        add_command = ["git", "-C", str(worktree_dir), "add", "--", *paths]
        add_result, diagnostic = run_graph_repository_command(add_command)
        command_results.append(add_result)
        if diagnostic is not None:
            diagnostics.append(diagnostic)

    if not any(diagnostic.level == "ERROR" for diagnostic in diagnostics):
        diff_completed = subprocess.run(
            ["git", "-C", str(worktree_dir), "diff", "--cached", "--quiet"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        command_results.append(
            {
                "command": [
                    "git",
                    "-C",
                    str(worktree_dir),
                    "diff",
                    "--cached",
                    "--quiet",
                ],
                "returncode": diff_completed.returncode,
                "stdout": diff_completed.stdout[-2000:],
                "stderr": diff_completed.stderr[-2000:],
            }
        )
        if diff_completed.returncode == 0:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_no_staged_changes",
                    subject="path",
                    message="explicit paths produced no staged changes",
                )
            )
        elif diff_completed.returncode != 1:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_git_command_failed",
                    subject="git.diff",
                    message="failed to inspect staged changes before commit",
                )
            )

    if not any(diagnostic.level == "ERROR" for diagnostic in diagnostics):
        commit_command = [
            "git",
            "-C",
            str(worktree_dir),
            "-c",
            f"user.name={args.author_name}",
            "-c",
            f"user.email={args.author_email}",
            "commit",
            "-m",
            args.message,
        ]
        commit_result, diagnostic = run_graph_repository_command(commit_command)
        command_results.append(commit_result)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        else:
            commit_sha, diagnostic = git_stdout(
                ["git", "-C", str(worktree_dir), "rev-parse", "HEAD"]
            )
            if diagnostic is not None:
                diagnostics.append(diagnostic)

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    report_path = (
        worktree_dir
        / ".platform"
        / "graph_repository_review_commit_report.json"
    )
    local_files_written: list[str] = []
    if error_count == 0:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        local_files_written.append(str(report_path))

    report = {
        "schema_version": 1,
        "artifact_kind": "platform_graph_repository_review_commit_report",
        "prepare_report_ref": str(prepare_report_path),
        "ok": error_count == 0,
        "candidate_branch": candidate_branch,
        "current_branch": current_branch,
        "worktree_dir": str(worktree_dir),
        "committed_paths": paths if error_count == 0 else [],
        "commit_sha": commit_sha,
        "canonical_mutations_allowed": False,
        "canonical_tracked_artifacts_written": False,
        "candidate_tracked_artifacts_written": error_count == 0,
        "pull_requests_opened": [],
        "merges_performed": [],
        "git_commands_executed": command_results,
        "local_files_written": local_files_written,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "commit_created": commit_sha is not None and error_count == 0,
        },
    }

    if error_count == 0:
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "branch": str(candidate_branch),
                        "commit": str(commit_sha),
                        "paths": str(len(paths)),
                    }
                ],
                [
                    ("branch", "BRANCH"),
                    ("commit", "COMMIT"),
                    ("paths", "PATHS"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def graph_repository_open_review_preflight_diagnostics(
    commit_report: dict[str, Any],
    *,
    worktree_dir: Path,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if commit_report.get("artifact_kind") != (
        "platform_graph_repository_review_commit_report"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_commit_report_kind_mismatch",
                subject="artifact_kind",
                message="expected platform_graph_repository_review_commit_report",
            )
        )
    if commit_report.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_commit_report_not_ok",
                subject="ok",
                message="review commit report must be ok before opening review",
            )
        )
    if not isinstance(commit_report.get("candidate_branch"), str):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_candidate_branch_missing",
                subject="candidate_branch",
                message="commit report must include candidate branch",
            )
        )
    if not isinstance(commit_report.get("commit_sha"), str):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_commit_sha_missing",
                subject="commit_sha",
                message="commit report must include commit sha",
            )
        )
    if commit_report.get("canonical_mutations_allowed") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_commit_report_authority_expanded",
                subject="canonical_mutations_allowed",
                message="review commit report must not allow canonical mutations",
            )
        )
    if commit_report.get("canonical_tracked_artifacts_written") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_commit_report_authority_expanded",
                subject="canonical_tracked_artifacts_written",
                message="review commit report must not write canonical tracked artifacts",
            )
        )
    if not worktree_dir.is_dir() or not (worktree_dir / ".git").exists():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_worktree_missing",
                subject="worktree_dir",
                message="worktree directory must be an existing Git worktree",
            )
        )
    return diagnostics


def graph_repository_open_review(args: argparse.Namespace) -> int:
    commit_report_path = Path(args.commit_report)
    worktree_dir = Path(args.worktree_dir)
    commit_report = load_json_mapping(
        commit_report_path,
        label="graph repository review commit report",
    )
    candidate_branch = commit_report.get("candidate_branch")
    commit_sha = commit_report.get("commit_sha")
    diagnostics = graph_repository_open_review_preflight_diagnostics(
        commit_report,
        worktree_dir=worktree_dir,
    )
    command_results: list[dict[str, Any]] = []
    current_branch: str | None = None
    current_head: str | None = None

    if not any(diagnostic.level == "ERROR" for diagnostic in diagnostics):
        current_branch, diagnostic = git_stdout(
            ["git", "-C", str(worktree_dir), "rev-parse", "--abbrev-ref", "HEAD"]
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        elif current_branch != candidate_branch:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_worktree_branch_mismatch",
                    subject="worktree_dir",
                    message=(
                        f"expected branch `{candidate_branch}` but found "
                        f"`{current_branch}`"
                    ),
                )
            )

    if not any(diagnostic.level == "ERROR" for diagnostic in diagnostics):
        current_head, diagnostic = git_stdout(
            ["git", "-C", str(worktree_dir), "rev-parse", "HEAD"]
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        elif current_head != commit_sha:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_worktree_head_mismatch",
                    subject="worktree_dir",
                    message=(
                        f"expected HEAD `{commit_sha}` but found "
                        f"`{current_head}`"
                    ),
                )
            )

    review_url: str | None = None
    candidate_branch_pushed = False
    git_commands_planned = [
        ["git", "-C", str(worktree_dir), "push", "-u", "origin", str(candidate_branch)]
    ]
    gh_command = [
        args.gh_bin,
        "pr",
        "create",
        "--base",
        args.base,
        "--head",
        str(candidate_branch),
        "--title",
        args.title,
        "--body",
        args.body,
    ]
    if args.repo:
        gh_command.extend(["--repo", args.repo])

    if not any(diagnostic.level == "ERROR" for diagnostic in diagnostics) and not args.dry_run:
        push_result, diagnostic = run_graph_repository_command(git_commands_planned[0])
        command_results.append(push_result)
        candidate_branch_pushed = push_result["returncode"] == 0
        if diagnostic is not None:
            diagnostics.append(diagnostic)

    if not any(diagnostic.level == "ERROR" for diagnostic in diagnostics) and not args.dry_run:
        gh_result, diagnostic = run_graph_repository_command(
            gh_command,
            cwd=worktree_dir,
        )
        command_results.append(gh_result)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        else:
            review_url = gh_result["stdout"].strip().splitlines()[-1]

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    report_path = (
        worktree_dir
        / ".platform"
        / "graph_repository_open_review_report.json"
    )
    local_files_written: list[str] = []
    if error_count == 0 and not args.dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        local_files_written.append(str(report_path))

    report = {
        "schema_version": 1,
        "artifact_kind": "platform_graph_repository_open_review_report",
        "commit_report_ref": str(commit_report_path),
        "ok": error_count == 0,
        "dry_run": args.dry_run,
        "candidate_branch": candidate_branch,
        "commit_sha": commit_sha,
        "current_branch": current_branch,
        "current_head": current_head,
        "base_branch": args.base,
        "worktree_dir": str(worktree_dir),
        "canonical_mutations_allowed": False,
        "canonical_tracked_artifacts_written": False,
        "candidate_branch_pushed": candidate_branch_pushed,
        "pull_requests_opened": [] if review_url is None else [review_url],
        "review_url": review_url,
        "commits_created": [],
        "merges_performed": [],
        "git_commands_planned": git_commands_planned,
        "review_commands_planned": [gh_command],
        "commands_executed": [] if args.dry_run else command_results,
        "local_files_written": local_files_written,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "review_opened": review_url is not None and error_count == 0,
        },
    }

    if error_count == 0 and not args.dry_run:
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "branch": str(candidate_branch),
                        "base": args.base,
                        "review": str(review_url),
                    }
                ],
                [
                    ("branch", "BRANCH"),
                    ("base", "BASE"),
                    ("review", "REVIEW"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def graph_repository_review_status_preflight_diagnostics(
    open_review_report: dict[str, Any],
    *,
    worktree_dir: Path,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if open_review_report.get("artifact_kind") != (
        "platform_graph_repository_open_review_report"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_open_review_report_kind_mismatch",
                subject="artifact_kind",
                message="expected platform_graph_repository_open_review_report",
            )
        )
    if open_review_report.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_open_review_report_not_ok",
                subject="ok",
                message="open review report must be ok before status inspection",
            )
        )
    review_url = open_review_report.get("review_url")
    if not isinstance(review_url, str) or not review_url:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_review_url_missing",
                subject="review_url",
                message="open review report must include review URL",
            )
        )
    if not worktree_dir.is_dir():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_worktree_missing",
                subject="worktree_dir",
                message="worktree directory must exist for status report output",
            )
        )
    return diagnostics


def graph_repository_review_state(pr_payload: dict[str, Any]) -> str:
    state = pr_payload.get("state")
    if pr_payload.get("mergedAt") or state == "MERGED":
        return "merged"
    if state == "CLOSED":
        return "closed"
    if pr_payload.get("isDraft") is True:
        return "draft"
    if state == "OPEN":
        return "open"
    return "unknown"


def graph_repository_review_status(args: argparse.Namespace) -> int:
    open_review_report_path = Path(args.open_review_report)
    worktree_dir = Path(args.worktree_dir)
    open_review_report = load_json_mapping(
        open_review_report_path,
        label="graph repository open review report",
    )
    diagnostics = graph_repository_review_status_preflight_diagnostics(
        open_review_report,
        worktree_dir=worktree_dir,
    )
    review_url = open_review_report.get("review_url")
    gh_command = [
        args.gh_bin,
        "pr",
        "view",
        str(review_url),
        "--json",
        (
            "number,url,state,isDraft,mergedAt,mergeCommit,"
            "headRefName,baseRefName,reviewDecision"
        ),
    ]
    if args.repo:
        gh_command.extend(["--repo", args.repo])

    command_results: list[dict[str, Any]] = []
    pr_payload: dict[str, Any] = {}
    review_state = "unknown"
    if not any(diagnostic.level == "ERROR" for diagnostic in diagnostics):
        gh_result, diagnostic = run_graph_repository_command(gh_command)
        command_results.append(gh_result)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        else:
            try:
                parsed = json.loads(gh_result["stdout"])
            except json.JSONDecodeError as exc:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="graph_repository_review_status_unparseable",
                        subject="gh.pr.view",
                        message=f"cannot parse gh pr view JSON output: {exc}",
                    )
                )
            else:
                if isinstance(parsed, dict):
                    pr_payload = parsed
                    review_state = graph_repository_review_state(pr_payload)
                else:
                    diagnostics.append(
                        Diagnostic(
                            level="ERROR",
                            code="graph_repository_review_status_wrong_type",
                            subject="gh.pr.view",
                            message="gh pr view output must be a JSON object",
                        )
                    )

    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    report_path = (
        worktree_dir
        / ".platform"
        / "graph_repository_review_status_report.json"
    )
    local_files_written: list[str] = []
    if error_count == 0:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        local_files_written.append(str(report_path))

    report = {
        "schema_version": 1,
        "artifact_kind": "platform_graph_repository_review_status_report",
        "open_review_report_ref": str(open_review_report_path),
        "ok": error_count == 0,
        "review_url": review_url,
        "review_state": review_state,
        "review_decision": pr_payload.get("reviewDecision"),
        "pull_request": pr_payload,
        "canonical_mutations_allowed": False,
        "canonical_tracked_artifacts_written": False,
        "merges_performed": [],
        "read_models_published": [],
        "commands_executed": command_results,
        "local_files_written": local_files_written,
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "review_merged": review_state == "merged",
        },
    }

    if error_count == 0:
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "review": str(review_url),
                        "state": review_state,
                        "decision": str(pr_payload.get("reviewDecision")),
                    }
                ],
                [
                    ("review", "REVIEW"),
                    ("state", "STATE"),
                    ("decision", "DECISION"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def graph_repository_path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def graph_repository_publish_preflight_diagnostics(
    review_status_report: dict[str, Any],
    *,
    bundle_dir: Path,
    output_dir: Path,
    manifest_name: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    manifest_path = Path(manifest_name)
    manifest_name_invalid = (
        not manifest_name
        or manifest_path.is_absolute()
        or any(part == ".." for part in manifest_path.parts)
    )
    resolved_bundle_dir = bundle_dir.resolve()
    resolved_manifest_path = (bundle_dir / manifest_path).resolve()
    if review_status_report.get("artifact_kind") != (
        "platform_graph_repository_review_status_report"
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_review_status_report_kind_mismatch",
                subject="artifact_kind",
                message="expected platform_graph_repository_review_status_report",
            )
        )
    if review_status_report.get("ok") is not True:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_review_status_report_not_ok",
                subject="ok",
                message="review status report must be ok before read-model publish",
            )
        )
    if review_status_report.get("review_state") != "merged":
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_review_not_merged",
                subject="review_state",
                message="read-model publish requires a merged review status",
            )
        )
    if review_status_report.get("canonical_mutations_allowed") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_review_status_authority_expanded",
                subject="canonical_mutations_allowed",
                message="review status report must not allow canonical mutations",
            )
        )
    if review_status_report.get("canonical_tracked_artifacts_written") is not False:
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_review_status_authority_expanded",
                subject="canonical_tracked_artifacts_written",
                message="review status report must not write canonical tracked artifacts",
            )
        )
    if manifest_name_invalid or not graph_repository_path_is_within(
        resolved_manifest_path,
        resolved_bundle_dir,
    ):
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_read_model_manifest_name_invalid",
                subject=manifest_name,
                message="manifest name must be a relative path inside the bundle",
            )
        )
    if not bundle_dir.is_dir():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_read_model_bundle_missing",
                subject="bundle_dir",
                message="read-model bundle directory must exist",
            )
        )
    elif not manifest_name_invalid:
        if not (bundle_dir / manifest_path).is_file():
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="graph_repository_read_model_manifest_missing",
                    subject=manifest_name,
                    message="read-model bundle manifest is required",
                )
            )
        else:
            try:
                load_json_mapping(
                    bundle_dir / manifest_path,
                    label="read-model manifest",
                )
            except PlatformError as exc:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="graph_repository_read_model_manifest_invalid",
                        subject=manifest_name,
                        message=str(exc),
                    )
                )
    if output_dir.exists():
        diagnostics.append(
            Diagnostic(
                level="ERROR",
                code="graph_repository_read_model_output_exists",
                subject="output_dir",
                message="output directory must not exist before publish",
            )
        )
    return diagnostics


def graph_repository_publish_read_model(args: argparse.Namespace) -> int:
    review_status_report_path = Path(args.review_status_report)
    bundle_dir = Path(args.bundle_dir)
    output_dir = Path(args.output_dir)
    manifest_name = args.manifest_name
    review_status_report = load_json_mapping(
        review_status_report_path,
        label="graph repository review status report",
    )
    diagnostics = graph_repository_publish_preflight_diagnostics(
        review_status_report,
        bundle_dir=bundle_dir,
        output_dir=output_dir,
        manifest_name=manifest_name,
    )
    error_count = sum(1 for diagnostic in diagnostics if diagnostic.level == "ERROR")
    copied_files: list[str] = []
    report_path = (
        output_dir
        / ".platform"
        / "graph_repository_publish_read_model_report.json"
    )

    if error_count == 0 and not args.dry_run:
        shutil.copytree(bundle_dir, output_dir)
        copied_files = [
            str(path.relative_to(output_dir))
            for path in sorted(output_dir.rglob("*"))
            if path.is_file()
        ]
        report_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "schema_version": 1,
        "artifact_kind": "platform_graph_repository_publish_read_model_report",
        "review_status_report_ref": str(review_status_report_path),
        "ok": error_count == 0,
        "dry_run": args.dry_run,
        "review_url": review_status_report.get("review_url"),
        "review_state": review_status_report.get("review_state"),
        "bundle_dir": str(bundle_dir),
        "output_dir": str(output_dir),
        "manifest": str(output_dir / manifest_name),
        "canonical_mutations_allowed": False,
        "canonical_tracked_artifacts_written": False,
        "ontology_packages_written": False,
        "merges_performed": [],
        "read_models_published": []
        if args.dry_run or error_count
        else [str(output_dir / manifest_name)],
        "files_published": copied_files,
        "local_files_written": []
        if args.dry_run or error_count
        else [str(report_path)],
        "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        "summary": {
            "error_count": error_count,
            "file_count": len(copied_files),
            "published": not args.dry_run and error_count == 0,
        },
    }

    if error_count == 0 and not args.dry_run:
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print(
            render_rows(
                [
                    {
                        "manifest": str(output_dir / manifest_name),
                        "files": str(len(copied_files)),
                        "published": str(not args.dry_run and error_count == 0),
                    }
                ],
                [
                    ("manifest", "MANIFEST"),
                    ("files", "FILES"),
                    ("published", "PUBLISHED"),
                ],
            )
        )
    return 0 if error_count == 0 else 1


def expected_profile(kind: Any) -> str | None:
    if kind == "core_repository":
        return "self_hosted_bootstrap"
    if kind == "product_workspace":
        return "product_workspace"
    return None


def resolve_org_root(catalog: dict[str, Any]) -> tuple[Path | None, Diagnostic | None]:
    raw_root = catalog.get("organization_root")
    if raw_root == "${ORG_ROOT}":
        env_root = os.environ.get("ORG_ROOT")
        if not env_root:
            return None, Diagnostic(
                level="WARN",
                code="org_root_unresolved",
                subject="organization_root",
                message="ORG_ROOT is not set; skipping placeholder path existence checks",
            )
        return Path(env_root), None

    if isinstance(raw_root, str) and raw_root.startswith("/"):
        return Path(raw_root), None

    return None, None


def resolve_workspace_path(
    path_value: Any,
    *,
    org_root: Path | None,
    workspace_subject: str,
) -> tuple[Path | None, Diagnostic | None]:
    if not isinstance(path_value, str):
        return None, None

    if path_value.startswith("/"):
        return Path(path_value), None

    org_root_prefix = "${ORG_ROOT}/"
    if path_value.startswith(org_root_prefix):
        if org_root is None:
            return None, Diagnostic(
                level="WARN",
                code="workspace_path_unresolved",
                subject=f"{workspace_subject}.path",
                message="path uses ${ORG_ROOT}, but ORG_ROOT is not available",
            )
        return org_root / path_value.removeprefix(org_root_prefix), None

    return None, None


def missing_path_level(workspace: dict[str, Any]) -> str:
    if workspace.get("status") == "active":
        return "ERROR"
    return "WARN"


def check_existing_path(
    path: Path,
    *,
    subject: str,
    code: str,
    missing_level: str,
    expect_dir: bool,
) -> list[Diagnostic]:
    if not path.exists():
        return [
            Diagnostic(
                level=missing_level,
                code=code,
                subject=subject,
                message=f"path does not exist: {path}",
            )
        ]

    if expect_dir and not path.is_dir():
        return [
            Diagnostic(
                level="ERROR",
                code="path_not_directory",
                subject=subject,
                message=f"path is not a directory: {path}",
            )
        ]

    if not expect_dir and not path.is_file():
        if path.is_dir():
            return [
                Diagnostic(
                    level="ERROR",
                    code="path_wrong_type",
                    subject=subject,
                    message=f"expected file but found directory: {path}",
                )
            ]
        return [
            Diagnostic(
                level=missing_level,
                code=code,
                subject=subject,
                message=f"file does not exist: {path}",
            )
        ]
    return []


def provider_root_fields(provider: Any) -> list[str]:
    if not isinstance(provider, dict):
        return []
    return [
        field
        for field in ("specs_root", "runs_root", "proposals_root")
        if isinstance(provider.get(field), str)
    ]


def semantic_diagnostics(catalog: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    workspaces = catalog_workspace_mappings(catalog)
    registries = catalog_registries(catalog)
    known_registry_ids = {
        registry.get("registry_id")
        for registry in registries
        if isinstance(registry.get("registry_id"), str)
    }

    diagnostics.extend(
        duplicate_id_diagnostics(
            workspaces,
            field="project_id",
            code="duplicate_project_id",
            collection_name="workspaces",
        )
    )
    diagnostics.extend(
        duplicate_id_diagnostics(
            registries,
            field="registry_id",
            code="duplicate_registry_id",
            collection_name="registries",
        )
    )

    org_root, org_root_diagnostic = resolve_org_root(catalog)
    if org_root_diagnostic is not None:
        diagnostics.append(org_root_diagnostic)

    for index, workspace in enumerate(workspaces):
        subject = f"workspaces[{index}]"
        project_id = workspace.get("project_id")
        if isinstance(project_id, str) and project_id:
            subject = f"workspace:{project_id}"

        profile = workspace.get("governance_profile")
        expected = expected_profile(workspace.get("kind"))
        if expected is not None and profile != expected:
            diagnostics.append(
                Diagnostic(
                    level="ERROR",
                    code="workspace_profile_mismatch",
                    subject=f"{subject}.governance_profile",
                    message=f"expected `{expected}` for kind `{workspace.get('kind')}`",
                )
            )

        registry = workspace.get("registry")
        if isinstance(registry, dict):
            registry_id = registry.get("registry_id")
            if isinstance(registry_id, str) and registry_id not in known_registry_ids:
                diagnostics.append(
                    Diagnostic(
                        level="ERROR",
                        code="unknown_registry_id",
                        subject=f"{subject}.registry.registry_id",
                        message=f"registry `{registry_id}` is not defined in top-level registries",
                    )
                )

        resolved_path, path_diagnostic = resolve_workspace_path(
            workspace.get("path"),
            org_root=org_root,
            workspace_subject=subject,
        )
        if path_diagnostic is not None:
            diagnostics.append(path_diagnostic)
        if resolved_path is None:
            continue

        missing_level = missing_path_level(workspace)
        diagnostics.extend(
            check_existing_path(
                resolved_path,
                subject=f"{subject}.path",
                code="workspace_path_missing",
                missing_level=missing_level,
                expect_dir=True,
            )
        )
        if not resolved_path.is_dir():
            continue

        config_path = workspace.get("specgraph_config")
        if isinstance(config_path, str):
            diagnostics.extend(
                check_existing_path(
                    resolved_path / config_path,
                    subject=f"{subject}.specgraph_config",
                    code="specgraph_config_missing",
                    missing_level=missing_level,
                    expect_dir=False,
                )
            )

        provider = workspace.get("provider")
        if isinstance(provider, dict):
            for field in provider_root_fields(provider):
                diagnostics.extend(
                    check_existing_path(
                        resolved_path / str(provider[field]),
                        subject=f"{subject}.provider.{field}",
                        code="provider_root_missing",
                        missing_level="WARN",
                        expect_dir=True,
                    )
                )

    return diagnostics


def workspace_list(args: argparse.Namespace) -> int:
    catalog_path = Path(args.catalog) if args.catalog else default_catalog_path()
    catalog = load_yaml(catalog_path)
    rows = [workspace_row(workspace) for workspace in catalog_workspaces(catalog)]
    rows = filter_rows(rows, kind=args.kind, status=args.status)

    if args.format == "json":
        payload = {
            "catalog": str(catalog_path),
            "workspaces": rows,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if rows:
        print(render_workspace_table(rows))
    return 0


def workspace_doctor(args: argparse.Namespace) -> int:
    catalog_path = Path(args.catalog) if args.catalog else default_catalog_path()
    catalog = load_yaml(catalog_path)
    diagnostics = [
        *validate_catalog_schema(catalog),
        *semantic_diagnostics(catalog),
    ]
    has_errors = any(diagnostic.level == "ERROR" for diagnostic in diagnostics)

    if args.format == "json":
        payload = {
            "catalog": str(catalog_path),
            "ok": not has_errors,
            "diagnostics": [asdict(diagnostic) for diagnostic in diagnostics],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1 if has_errors else 0

    if diagnostics:
        print(render_diagnostic_table(diagnostics))
    else:
        print("OK: no workspace catalog diagnostics")
    return 1 if has_errors else 0


def dump_yaml(data: dict[str, Any], path: Path) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise PlatformError(
            "PyYAML is required to write workspace catalogs. "
            "Install it with `python3 -m pip install PyYAML`."
        ) from exc

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(
                data,
                handle,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
            )
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def resolve_specgraph_supervisor() -> Path:
    env_home = os.environ.get("SPECGRAPH_HOME")
    if env_home:
        candidate = Path(env_home) / SPECGRAPH_SUPERVISOR_REL
        if candidate.is_file():
            return candidate
        raise PlatformError(
            f"SPECGRAPH_HOME is set but no supervisor at {candidate}"
        )

    tried: list[Path] = []

    org_root = os.environ.get("ORG_ROOT")
    if org_root:
        candidate = Path(org_root) / "SpecGraph" / SPECGRAPH_SUPERVISOR_REL
        if candidate.is_file():
            return candidate
        tried.append(candidate)

    sibling = REPO_ROOT.parent / "SpecGraph" / SPECGRAPH_SUPERVISOR_REL
    if sibling.is_file():
        return sibling
    tried.append(sibling)

    tried_lines = "\n  ".join(str(path) for path in tried)
    raise PlatformError(
        "cannot find SpecGraph supervisor. Set SPECGRAPH_HOME or place "
        "SpecGraph next to Platform. Tried:\n  " + tried_lines
    )


def expand_workspace_path(raw: str, org_root: Path | None) -> Path:
    if not isinstance(raw, str) or not raw:
        raise PlatformError("--path must be a non-empty string")

    org_root_prefix = "${ORG_ROOT}/"
    if raw.startswith(org_root_prefix):
        if org_root is None:
            raise PlatformError(
                "path uses ${ORG_ROOT}/ but ORG_ROOT is not set"
            )
        return (org_root / raw.removeprefix(org_root_prefix)).resolve()

    if not raw.startswith("/"):
        raise PlatformError(
            f"--path must be absolute or start with ${{ORG_ROOT}}/: {raw}"
        )
    return Path(raw).resolve()


def relativize_to_org_root(abs_path: Path, org_root: Path | None) -> str:
    if org_root is None:
        return str(abs_path)
    try:
        rel = abs_path.relative_to(org_root.resolve())
    except ValueError:
        return str(abs_path)
    return f"${{ORG_ROOT}}/{rel.as_posix()}"


def load_init_catalog(catalog_path: Path) -> dict[str, Any]:
    if catalog_path.exists():
        return load_yaml(catalog_path)

    example = load_yaml(DEFAULT_EXAMPLE_CATALOG)
    example["workspaces"] = []
    return example


def validate_init_inputs(
    args: argparse.Namespace,
    catalog: dict[str, Any],
    workspace_root: Path,
) -> None:
    if not PROJECT_ID_RE.match(args.project_id):
        raise PlatformError(
            f"invalid project_id `{args.project_id}`: must match "
            f"{PROJECT_ID_RE.pattern}"
        )
    if len(args.project_id) > 128:
        raise PlatformError("project_id must be at most 128 characters")

    for existing in catalog_workspaces(catalog):
        if existing.get("project_id") == args.project_id:
            raise PlatformError(
                f"project_id `{args.project_id}` already in catalog"
            )

    if workspace_root.exists():
        if not workspace_root.is_dir():
            raise PlatformError(
                f"workspace path exists and is not a directory: {workspace_root}"
            )
        if any(workspace_root.iterdir()):
            raise PlatformError(
                f"workspace path is not empty: {workspace_root}"
            )


def init_timeout_seconds() -> float:
    raw = os.environ.get("PLATFORM_INIT_TIMEOUT_SECONDS")
    if not raw:
        return float(INIT_TIMEOUT_SECONDS)
    try:
        return float(raw)
    except ValueError:
        return float(INIT_TIMEOUT_SECONDS)


def run_specgraph_init(
    supervisor: Path,
    *,
    project_id: str,
    display_name: str,
    workspace_root: Path,
    root_intent: str | None,
) -> subprocess.CompletedProcess[str]:
    cmd: list[str] = [
        sys.executable,
        str(supervisor),
        "--init-product-workspace",
        "--project-id",
        project_id,
        "--display-name",
        display_name,
        "--workspace-root",
        str(workspace_root),
    ]
    if root_intent:
        cmd += ["--root-intent", root_intent]

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    return subprocess.run(
        cmd,
        cwd=str(supervisor.parent.parent),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=init_timeout_seconds(),
        env=env,
    )


def load_initialization_report(workspace_root: Path) -> dict[str, Any]:
    report_path = workspace_root / "runs" / "product_workspace_initialization.json"
    if not report_path.is_file():
        raise PlatformError(
            f"SpecGraph did not produce initialization report at {report_path}"
        )
    try:
        with report_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise PlatformError(f"cannot read report {report_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PlatformError(f"cannot parse report {report_path}: {exc}") from exc


def report_findings_to_diagnostics(report: dict[str, Any]) -> list[Diagnostic]:
    findings = report.get("validation_findings") or []
    diagnostics: list[Diagnostic] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        diagnostics.append(
            Diagnostic(
                level=str(finding.get("level", "INFO")).upper(),
                code=str(finding.get("code", "specgraph_finding")),
                subject=str(finding.get("subject", "workspace")),
                message=str(finding.get("message", "")),
            )
        )
    return diagnostics


def build_catalog_entry(
    *,
    project_id: str,
    display_name: str,
    workspace_root: Path,
    org_root: Path | None,
    governance_profile: str,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "project_id": project_id,
        "display_name": display_name,
        "kind": "product_workspace",
        "status": "active",
        "path": relativize_to_org_root(workspace_root, org_root),
        "governance_profile": governance_profile,
        "specgraph_config": "specgraph.project.yaml",
        "provider": {
            "type": "local_filesystem",
            "specs_root": "specs",
            "runs_root": "runs",
            "proposals_root": "docs/proposals",
        },
    }
    return entry


def format_manual_yaml_entry(entry: dict[str, Any]) -> str:
    try:
        import yaml
    except ImportError:
        return json.dumps(entry, indent=2)
    return yaml.safe_dump(
        [entry],
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def append_workspace_to_catalog(
    catalog_path: Path,
    catalog: dict[str, Any],
    entry: dict[str, Any],
) -> None:
    workspaces = catalog.get("workspaces")
    if not isinstance(workspaces, list):
        workspaces = []
        catalog["workspaces"] = workspaces
    workspaces.append(entry)
    dump_yaml(catalog, catalog_path)


def workspace_init(args: argparse.Namespace) -> int:
    if args.catalog:
        catalog_path = Path(args.catalog)
    else:
        catalog_path = DEFAULT_LOCAL_CATALOG

    if catalog_path.resolve() == DEFAULT_EXAMPLE_CATALOG.resolve():
        raise PlatformError(
            f"refusing to write tracked example catalog: {catalog_path}"
        )

    catalog = load_init_catalog(catalog_path)
    schema_version = catalog.get("schema_version")
    if schema_version not in (None, 1):
        raise PlatformError(
            f"unsupported catalog schema_version {schema_version!r}; "
            "migrate the catalog before running workspace init"
        )

    org_root, _ = resolve_org_root(catalog)
    workspace_root = expand_workspace_path(args.path, org_root)
    validate_init_inputs(args, catalog, workspace_root)

    governance_profile = args.governance_profile
    if governance_profile != "product_workspace":
        raise PlatformError(
            "workspace init only supports governance_profile=product_workspace; "
            f"got {governance_profile}"
        )

    supervisor = resolve_specgraph_supervisor()
    display_name = args.display_name or args.project_id

    if args.dry_run:
        cmd_preview = [
            sys.executable,
            str(supervisor),
            "--init-product-workspace",
            "--project-id",
            args.project_id,
            "--display-name",
            display_name,
            "--workspace-root",
            str(workspace_root),
        ]
        if args.root_intent:
            cmd_preview += ["--root-intent", args.root_intent]
        pending_entry = build_catalog_entry(
            project_id=args.project_id,
            display_name=display_name,
            workspace_root=workspace_root,
            org_root=org_root,
            governance_profile=governance_profile,
        )
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "catalog": str(catalog_path),
                        "supervisor": str(supervisor),
                        "command": cmd_preview,
                        "pending_entry": pending_entry,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"DRY RUN — would invoke supervisor at {supervisor}")
            print("  command: " + " ".join(cmd_preview))
            print(f"  catalog: {catalog_path}")
            print("  pending entry:")
            print(format_manual_yaml_entry(pending_entry))
        return 0

    try:
        result = run_specgraph_init(
            supervisor,
            project_id=args.project_id,
            display_name=display_name,
            workspace_root=workspace_root,
            root_intent=args.root_intent,
        )
    except subprocess.TimeoutExpired:
        print(
            f"platform: SpecGraph supervisor timed out after "
            f"{init_timeout_seconds()}s",
            file=sys.stderr,
        )
        return 1

    supervisor_stdout_target = sys.stderr if args.format == "json" else sys.stdout
    if result.stdout:
        supervisor_stdout_target.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)

    if result.returncode != 0:
        print(
            f"platform: SpecGraph supervisor exited with code {result.returncode}",
            file=sys.stderr,
        )
        return 1

    report = load_initialization_report(workspace_root)
    summary = report.get("summary") or {}
    status = summary.get("status")
    diagnostics = report_findings_to_diagnostics(report)

    def emit_output(catalog_written: bool, exit_code: int) -> int:
        if args.format == "json":
            payload = {
                "catalog": str(catalog_path),
                "catalog_written": catalog_written,
                "workspace": str(workspace_root),
                "report_status": status,
                "review_state": report.get("review_state"),
                "diagnostics": [asdict(d) for d in diagnostics],
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            if diagnostics:
                print(render_diagnostic_table(diagnostics))
            print(f"workspace: {workspace_root}")
            print(f"report status: {status}")
            print(f"catalog: {catalog_path} ({'written' if catalog_written else 'not modified'})")
        return exit_code

    if status not in ("initialized", "ready"):
        return emit_output(catalog_written=False, exit_code=1)

    entry = build_catalog_entry(
        project_id=args.project_id,
        display_name=display_name,
        workspace_root=workspace_root,
        org_root=org_root,
        governance_profile=governance_profile,
    )

    try:
        append_workspace_to_catalog(catalog_path, catalog, entry)
    except OSError as exc:
        snippet = format_manual_yaml_entry(entry)
        print(
            f"platform: SpecGraph initialized workspace at {workspace_root}, "
            f"but writing catalog {catalog_path} failed: {exc}\n"
            f"Add this entry manually under workspaces:\n{snippet}",
            file=sys.stderr,
        )
        return 1

    return emit_output(catalog_written=True, exit_code=0)


def default_compose_path() -> Path:
    env_path = os.environ.get("PLATFORM_COMPOSE_FILE")
    if env_path:
        return Path(env_path)
    if DEFAULT_LOCAL_COMPOSE.exists():
        return DEFAULT_LOCAL_COMPOSE
    return DEFAULT_EXAMPLE_COMPOSE


def default_env_path() -> Path | None:
    env_path = os.environ.get("PLATFORM_ENV_FILE")
    if env_path:
        return Path(env_path)
    if DEFAULT_LOCAL_ENV.exists():
        return DEFAULT_LOCAL_ENV
    return None


def existing_file(path: Path, *, label: str) -> Path:
    if not path.is_file():
        raise PlatformError(f"{label} does not exist or is not a file: {path}")
    return path


def resolve_deploy_paths(
    args: argparse.Namespace,
    *,
    include_env: bool = True,
) -> tuple[list[Path], Path | None]:
    compose_paths = [Path(args.compose_file) if args.compose_file else default_compose_path()]
    if args.profile == "production-web":
        compose_paths.append(DEFAULT_PRODUCTION_WEB_COMPOSE)
    deduped_compose_paths: list[Path] = []
    seen_compose_paths: set[Path] = set()
    for compose_path in compose_paths:
        resolved_compose_path = existing_file(compose_path, label="compose file").resolve()
        if resolved_compose_path in seen_compose_paths:
            continue
        seen_compose_paths.add(resolved_compose_path)
        deduped_compose_paths.append(compose_path)

    if not include_env:
        env_path = None
    elif args.env_file:
        env_path: Path | None = existing_file(Path(args.env_file), label="env file")
    else:
        env_path = default_env_path()
        if env_path is not None:
            env_path = existing_file(env_path, label="env file")

    return deduped_compose_paths, env_path


def deploy_compose_args(args: argparse.Namespace) -> list[str]:
    if args.deploy_command == "render":
        return ["config"]
    if args.deploy_command == "status":
        return ["ps"]
    if args.deploy_command == "up":
        compose_args = ["up", "-d"]
        if args.build:
            compose_args.append("--build")
        return compose_args
    if args.deploy_command == "down":
        compose_args = ["down"]
        if args.volumes:
            compose_args.append("--volumes")
        return compose_args
    raise PlatformError(f"unsupported deploy command: {args.deploy_command}")


def bundle_compose_args(compose_files: list[Path], *, env_file: Path | None) -> list[str]:
    command = ["docker", "compose"]
    for compose_file in compose_files:
        command += ["--file", compose_file.name]
    if env_file is not None:
        command += ["--env-file", env_file.name]
    command += ["up", "-d"]
    return command


def write_deploy_bundle(args: argparse.Namespace) -> DeployBundle:
    compose_paths, _env_path = resolve_deploy_paths(args, include_env=False)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bundled_compose_files: list[Path] = []
    for compose_path in compose_paths:
        destination = output_dir / compose_path.name
        shutil.copyfile(compose_path, destination)
        bundled_compose_files.append(destination)

    env_example = REPO_ROOT / ".env.example"
    bundled_env: Path | None = None
    if env_example.is_file():
        bundled_env = output_dir / ".env.example"
        shutil.copyfile(env_example, bundled_env)

    command = bundle_compose_args(
        bundled_compose_files,
        env_file=Path(".env") if bundled_env is not None else None,
    )
    manifest = output_dir / "platform-deploy-bundle.json"
    payload = {
        "artifact_kind": "platform_deploy_bundle",
        "schema_version": 1,
        "profile": args.profile,
        "compose_files": [path.name for path in bundled_compose_files],
        "env_example": bundled_env.name if bundled_env else None,
        "env_file": ".env" if bundled_env else None,
        "command": command,
        "notes": [
            "Copy .env.example to .env on the target host and set ORG_ROOT.",
            "This bundle targets Compose-capable single-node hosts with an ORG_ROOT checkout.",
            "Timeweb Cloud Apps uses Platform's manifest-only profile instead of this bundle.",
        ],
    }
    manifest.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readme = output_dir / "README.md"
    readme.write_text(
        "# Platform Deploy Bundle\n\n"
        "This bundle contains the Compose files needed for the Platform "
        f"`{args.profile}` deployment profile.\n\n"
        "Before running it on the target host, copy `.env.example` to `.env` "
        "and set machine-local values such as `ORG_ROOT` and public ports.\n\n"
        "Start command:\n\n"
        "```bash\n"
        + " ".join(command)
        + "\n```\n",
        encoding="utf-8",
    )
    return DeployBundle(
        output_dir=output_dir,
        compose_files=bundled_compose_files,
        env_example=bundled_env,
        manifest=manifest,
        command=command,
    )


def build_compose_invocation(args: argparse.Namespace) -> ComposeInvocation:
    compose_paths, env_path = resolve_deploy_paths(args)
    project_name = args.project_name or os.environ.get("COMPOSE_PROJECT_NAME")
    command = [
        args.docker,
        "compose",
    ]
    if project_name:
        command[2:2] = ["--project-name", project_name]
    for compose_path in compose_paths:
        command += ["--file", str(compose_path)]
    if env_path is not None:
        command += ["--env-file", str(env_path)]
    command += deploy_compose_args(args)
    return ComposeInvocation(
        action=args.deploy_command,
        compose_files=compose_paths,
        env_file=env_path,
        project_name=project_name,
        command=command,
    )


def emit_deploy_plan(invocation: ComposeInvocation, *, output_format: str) -> int:
    payload = {
        "action": invocation.action,
        "compose_files": [str(compose_file) for compose_file in invocation.compose_files],
        "env_file": str(invocation.env_file) if invocation.env_file else None,
        "project_name": invocation.project_name,
        "command": invocation.command,
    }
    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"action: {payload['action']}")
        print("compose:")
        for compose_file in payload["compose_files"]:
            print(f"  - {compose_file}")
        print(f"env: {payload['env_file'] or '(none)'}")
        print(f"project: {payload['project_name'] or '(compose default)'}")
        print("command: " + " ".join(invocation.command))
    return 0


def deploy(args: argparse.Namespace) -> int:
    invocation = build_compose_invocation(args)
    if args.dry_run:
        return emit_deploy_plan(invocation, output_format=args.format)

    try:
        completed = subprocess.run(invocation.command, check=False)
    except FileNotFoundError as exc:
        raise PlatformError(
            f"docker executable not found: {args.docker}"
        ) from exc
    return completed.returncode


def deploy_bundle(args: argparse.Namespace) -> int:
    bundle = write_deploy_bundle(args)
    payload = {
        "action": "bundle",
        "output_dir": str(bundle.output_dir),
        "compose_files": [str(path) for path in bundle.compose_files],
        "env_example": str(bundle.env_example) if bundle.env_example else None,
        "manifest": str(bundle.manifest),
        "command": bundle.command,
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"bundle: {bundle.output_dir}")
        print("compose:")
        for compose_file in bundle.compose_files:
            print(f"  - {compose_file}")
        print(f"env example: {bundle.env_example or '(none)'}")
        print(f"manifest: {bundle.manifest}")
    return 0


def require_digest_image_ref(value: str, *, label: str) -> None:
    if not value:
        raise PlatformError(f"{label} must be set")
    if ":latest" in value:
        raise PlatformError(f"{label} must not use the mutable latest tag: {value}")
    if not DIGEST_IMAGE_RE.match(value):
        raise PlatformError(
            f"{label} must be digest-pinned with @sha256:<64 hex chars>: {value}"
        )


def image_ref_from_lock_service(
    services: dict[str, Any],
    service_id: str,
    *,
    lock_path: Path,
) -> str:
    service = services.get(service_id)
    if not isinstance(service, dict):
        raise PlatformError(
            f"image lock {lock_path} must contain services.{service_id}"
        )
    image_ref = service.get("image_ref")
    if not isinstance(image_ref, str) or not image_ref:
        raise PlatformError(
            f"image lock {lock_path} must contain services.{service_id}.image_ref"
        )
    return image_ref


def load_timeweb_image_lock(path: Path) -> TimewebImageRefs:
    if not path.is_file():
        raise PlatformError(f"image lock does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlatformError(f"image lock is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PlatformError(f"image lock must be a JSON object: {path}")
    artifact_kind = payload.get("artifact_kind")
    if artifact_kind != "platform_service_image_lock":
        raise PlatformError(
            f"image lock artifact_kind must be platform_service_image_lock: {path}"
        )
    schema_version = payload.get("schema_version")
    if schema_version != 1:
        raise PlatformError(
            f"image lock schema_version must be 1: {path}"
        )
    services = payload.get("services")
    if not isinstance(services, dict):
        raise PlatformError(f"image lock {path} must contain a services object")
    return TimewebImageRefs(
        specspace_api_image_ref=image_ref_from_lock_service(
            services,
            "specspace_api",
            lock_path=path,
        ),
        specspace_ui_image_ref=image_ref_from_lock_service(
            services,
            "specspace_ui",
            lock_path=path,
        ),
        image_lock=path,
    )


def resolve_timeweb_image_refs(args: argparse.Namespace) -> TimewebImageRefs:
    locked = (
        load_timeweb_image_lock(Path(args.image_lock))
        if args.image_lock
        else TimewebImageRefs("", "")
    )
    refs = TimewebImageRefs(
        specspace_api_image_ref=args.specspace_api_image_ref
        or locked.specspace_api_image_ref,
        specspace_ui_image_ref=args.specspace_ui_image_ref
        or locked.specspace_ui_image_ref,
        image_lock=locked.image_lock,
    )
    require_digest_image_ref(
        refs.specspace_api_image_ref,
        label="SPECSPACE API image ref",
    )
    require_digest_image_ref(
        refs.specspace_ui_image_ref,
        label="SPECSPACE UI image ref",
    )
    return refs


def safe_output_dir(path: Path) -> None:
    if str(path) in ("", "/", ".", ".."):
        raise PlatformError(f"refusing unsafe output directory: {path}")


def bool_from_env(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def positive_int_string(value: str, *, label: str) -> str:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise PlatformError(f"{label} must be a positive integer, got {value!r}") from exc
    if parsed < 1:
        raise PlatformError(f"{label} must be a positive integer, got {value!r}")
    return str(parsed)


def timeweb_hyperprompt_runtime_from_args(args: argparse.Namespace) -> TimewebHyperpromptRuntime:
    work_dir = str(args.hyperprompt_work_dir)
    if args.hyperprompt_http_compile_enabled and not work_dir:
        raise PlatformError("Hyperprompt work dir must be set when HTTP compile is enabled")
    return TimewebHyperpromptRuntime(
        http_compile_enabled=bool(args.hyperprompt_http_compile_enabled),
        work_dir=work_dir,
        compile_timeout_seconds=positive_int_string(
            str(args.hyperprompt_compile_timeout_seconds),
            label="Hyperprompt compile timeout seconds",
        ),
        max_input_bytes=positive_int_string(
            str(args.hyperprompt_max_input_bytes),
            label="Hyperprompt max input bytes",
        ),
        max_output_bytes=positive_int_string(
            str(args.hyperprompt_max_output_bytes),
            label="Hyperprompt max output bytes",
        ),
        bundle_retention_count=positive_int_string(
            str(args.hyperprompt_bundle_retention_count),
            label="Hyperprompt bundle retention count",
        ),
    )


def product_workspace_artifact_base_urls_from_args(args: argparse.Namespace) -> dict[str, str]:
    raw_values = getattr(args, "product_workspace_artifact_base_url", None)
    values: list[str] = []
    if isinstance(raw_values, list):
        values = [str(value).strip() for value in raw_values if str(value).strip()]
    elif raw_values:
        values = [str(raw_values).strip()]
    legacy_url = (
        str(args.team_decision_log_artifact_base_url).strip()
        if getattr(args, "team_decision_log_artifact_base_url", None)
        else ""
    )
    if not values and legacy_url:
        values = [legacy_url]
    if not values:
        values = [str(args.artifact_base_url)]

    bindings: dict[str, str] = {}
    for value in values:
        workspace_id, url = (
            value.split("=", 1)
            if "=" in value
            else ("team-decision-log", value)
        )
        workspace_id = workspace_id.strip().lower().replace("_", "-")
        url = url.strip()
        if not PRODUCT_WORKSPACE_ID_RE.fullmatch(workspace_id):
            raise PlatformError(
                "Product workspace artifact base URL binding must use a safe "
                f"workspace id, got {workspace_id!r}"
            )
        if not url:
            raise PlatformError(
                "Product workspace artifact base URL binding must include a URL "
                f"for {workspace_id!r}"
            )
        bindings[workspace_id] = url
    return bindings


def render_timeweb_hyperprompt_environment(runtime: TimewebHyperpromptRuntime) -> str:
    lines = [
        f"      SPECSPACE_HYPERPROMPT_HTTP_COMPILE_ENABLED: "
        f"\"{str(runtime.http_compile_enabled).lower()}\"\n",
    ]
    if runtime.http_compile_enabled:
        lines += [
            f"      SPECSPACE_HYPERPROMPT_WORK_DIR: \"{runtime.work_dir}\"\n",
            f"      SPECSPACE_HYPERPROMPT_COMPILE_TIMEOUT_SECONDS: "
            f"\"{runtime.compile_timeout_seconds}\"\n",
            f"      SPECSPACE_HYPERPROMPT_MAX_INPUT_BYTES: \"{runtime.max_input_bytes}\"\n",
            f"      SPECSPACE_HYPERPROMPT_MAX_OUTPUT_BYTES: \"{runtime.max_output_bytes}\"\n",
            f"      SPECSPACE_HYPERPROMPT_BUNDLE_RETENTION_COUNT: "
            f"\"{runtime.bundle_retention_count}\"\n",
        ]
    return "".join(lines)


def render_timeweb_compose(
    *,
    api_image_ref: str,
    ui_image_ref: str,
    artifact_base_url: str,
    product_workspace_artifact_base_urls: dict[str, str],
    specpm_registry_url: str,
    release_commit: str,
    hyperprompt_runtime: TimewebHyperpromptRuntime,
) -> str:
    product_workspace_args = "".join(
        "      - --product-workspace-artifact-base-url\n"
        f"      - \"{workspace_id}={artifact_base_url}\"\n"
        for workspace_id, artifact_base_url in sorted(
            product_workspace_artifact_base_urls.items()
        )
    )
    return (
        "name: specspace\n\n"
        "services:\n"
        "  app:\n"
        f"    image: \"{ui_image_ref}\"\n"
        "    ports:\n"
        "      - \"${SPECSPACE_UI_PORT:-5173}:80\"\n"
        "    depends_on:\n"
        "      - specspace-api\n\n"
        "  specspace-api:\n"
        f"    image: \"{api_image_ref}\"\n"
        "    environment:\n"
        f"      SPECSPACE_API_IMAGE_REF: \"{api_image_ref}\"\n"
        f"      SPECSPACE_UI_IMAGE_REF: \"{ui_image_ref}\"\n"
        f"      SPECSPACE_RELEASE_COMMIT: \"{release_commit}\"\n"
        f"{render_timeweb_hyperprompt_environment(hyperprompt_runtime)}"
        "    command:\n"
        "      - python\n"
        "      - viewer/server.py\n"
        "      - --host\n"
        "      - 0.0.0.0\n"
        "      - --port\n"
        "      - \"8001\"\n"
        "      - --dialog-dir\n"
        "      - /data/dialogs\n"
        "      - --artifact-base-url\n"
        f"      - \"{artifact_base_url}\"\n"
        f"{product_workspace_args}"
        "      - --specpm-registry-url\n"
        f"      - \"{specpm_registry_url}\"\n"
        "    ports:\n"
        "      - \"${SPECSPACE_API_PORT:-8001}:8001\"\n"
    )


def write_timeweb_manifest(args: argparse.Namespace) -> TimewebManifest:
    image_refs = resolve_timeweb_image_refs(args)
    hyperprompt_runtime = timeweb_hyperprompt_runtime_from_args(args)

    output_dir = Path(args.output_dir)
    safe_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for entry in output_dir.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    release_created_at = args.release_created_at or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    release_commit = args.release_commit or "unknown"
    product_workspace_artifact_base_urls = product_workspace_artifact_base_urls_from_args(args)
    compose_file = output_dir / "docker-compose.yml"
    readme = output_dir / "README.md"
    manifest = output_dir / "platform-timeweb-deploy.json"

    compose_file.write_text(
        render_timeweb_compose(
            api_image_ref=image_refs.specspace_api_image_ref,
            ui_image_ref=image_refs.specspace_ui_image_ref,
            artifact_base_url=args.artifact_base_url,
            product_workspace_artifact_base_urls=product_workspace_artifact_base_urls,
            specpm_registry_url=args.specpm_registry_url,
            release_commit=release_commit,
            hyperprompt_runtime=hyperprompt_runtime,
        ),
        encoding="utf-8",
    )
    readme.write_text(
        "# Platform Timeweb Deploy Manifest\n\n"
        "This directory is generated by Platform and is intentionally "
        "manifest-only. It is the Platform-owned Timeweb Cloud Apps deploy "
        "tree.\n\n"
        "## Release\n\n"
        f"- Source commit: `{release_commit}`\n"
        f"- Generated at: `{release_created_at}`\n"
        f"- API image: `{image_refs.specspace_api_image_ref}`\n"
        f"- UI image: `{image_refs.specspace_ui_image_ref}`\n"
        f"- Image lock: `{image_refs.image_lock or '(not used)'}`\n"
        f"- SpecGraph artifact source: `{args.artifact_base_url}`\n"
        f"- Product workspace artifact sources: "
        f"`{json.dumps(product_workspace_artifact_base_urls, sort_keys=True)}`\n"
        f"- SpecPM registry source: `{args.specpm_registry_url}`\n"
        f"- HTTP Hyperprompt compile: "
        f"`{'enabled' if hyperprompt_runtime.http_compile_enabled else 'disabled'}`\n"
        f"- Hyperprompt scratch workspace: "
        f"`{hyperprompt_runtime.work_dir if hyperprompt_runtime.http_compile_enabled else '(not used)'}`\n\n"
        "## Notes\n\n"
        "- The first service is named `app` because Timeweb proxies the public "
        "domain to the first compose service.\n"
        "- The manifest must not contain source files, bind mounts, build "
        "sections, or required environment interpolation.\n",
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "artifact_kind": "platform_timeweb_deploy_manifest",
                "schema_version": 1,
                "compose_file": compose_file.name,
                "readme": readme.name,
                "release_commit": release_commit,
                "release_created_at": release_created_at,
                "image_lock": str(image_refs.image_lock) if image_refs.image_lock else None,
                "specspace_api_image_ref": image_refs.specspace_api_image_ref,
                "specspace_ui_image_ref": image_refs.specspace_ui_image_ref,
                "artifact_base_url": args.artifact_base_url,
                "product_workspace_artifact_base_urls": product_workspace_artifact_base_urls,
                "hyperprompt_http_compile_enabled": (
                    hyperprompt_runtime.http_compile_enabled
                ),
                "hyperprompt_work_dir": (
                    hyperprompt_runtime.work_dir
                    if hyperprompt_runtime.http_compile_enabled
                    else None
                ),
                "hyperprompt_compile_timeout_seconds": (
                    hyperprompt_runtime.compile_timeout_seconds
                ),
                "hyperprompt_max_input_bytes": hyperprompt_runtime.max_input_bytes,
                "hyperprompt_max_output_bytes": hyperprompt_runtime.max_output_bytes,
                "hyperprompt_bundle_retention_count": (
                    hyperprompt_runtime.bundle_retention_count
                ),
                "specpm_registry_url": args.specpm_registry_url,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return TimewebManifest(
        output_dir=output_dir,
        compose_file=compose_file,
        readme=readme,
        manifest=manifest,
    )


def service_blocks(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    in_services = False
    order: list[str] = []
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if line == "services:":
            in_services = True
            continue
        if not in_services:
            continue
        if line and not line.startswith(" "):
            break
        match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if match:
            current = match.group(1)
            order.append(current)
            blocks[current] = []
            continue
        if current is not None:
            blocks[current].append(line)
    return order, blocks


def command_for_service(blocks: dict[str, list[str]], service_name: str) -> list[str]:
    values: list[str] = []
    in_command = False
    for line in blocks.get(service_name, []):
        if re.match(r"^    command:\s*$", line):
            in_command = True
            continue
        if in_command:
            match = re.match(r"^      -\s*(.*?)\s*$", line)
            if match:
                values.append(match.group(1).strip().strip('"').strip("'"))
                continue
            if line.strip() and not line.startswith("      "):
                break
    return values


def environment_for_service(blocks: dict[str, list[str]], service_name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_environment = False
    for line in blocks.get(service_name, []):
        if re.match(r"^    environment:\s*$", line):
            in_environment = True
            continue
        if in_environment:
            match = re.match(r"^      ([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", line)
            if match:
                values[match.group(1)] = match.group(2).strip().strip('"').strip("'")
                continue
            if line.strip() and not line.startswith("      "):
                break
    return values


def command_value_after(command: list[str], flag: str) -> str | None:
    try:
        index = command.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(command):
        return None
    return command[index + 1]


def command_values_after(command: list[str], flag: str) -> list[str]:
    values: list[str] = []
    for index, value in enumerate(command):
        if value == flag and index + 1 < len(command):
            values.append(command[index + 1])
    return values


def image_for_service(blocks: dict[str, list[str]], service_name: str) -> str | None:
    for line in blocks.get(service_name, []):
        match = re.match(r"^    image:\s*(.+?)\s*$", line)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return None


def validate_timeweb_manifest_tree(
    root: Path,
    *,
    artifact_base_url: str,
    product_workspace_artifact_base_urls: dict[str, str],
    specpm_registry_url: str,
    hyperprompt_runtime: TimewebHyperpromptRuntime,
) -> list[str]:
    target_file = "docker-compose.yml"
    compose_path = root / target_file
    allowed_top_level = {target_file, "README.md", "platform-timeweb-deploy.json"}
    errors: list[str] = []

    if not compose_path.is_file():
        errors.append(f"missing {target_file}")

    if root.is_dir():
        actual_top_level = {entry.name for entry in root.iterdir() if entry.name != ".git"}
        unexpected = sorted(actual_top_level - allowed_top_level)
        if unexpected:
            errors.append(
                "manifest-only tree contains unexpected top-level entries: "
                + ", ".join(unexpected)
            )

    if not compose_path.is_file():
        return errors

    text = compose_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if re.search(r"(?m)^[ \t]*build:", text):
        errors.append(f"{target_file} must not build from source")
    if re.search(r"(?m)^[ \t]*volumes:", text):
        errors.append(f"{target_file} must not declare volumes")
    if re.search(r"\$\{[^}]*\?", text):
        errors.append(f"{target_file} must not use required env interpolation")
    if "/app/deploy/specspace-demo" in text:
        errors.append(f"{target_file} must not reference bundled demo artifacts")

    order, blocks = service_blocks(lines)
    if not order:
        errors.append(f"{target_file} must declare services")
    elif order[0] != "app":
        errors.append(
            f"{target_file} must declare the UI service first as 'app', got {order[0]!r}"
        )

    api_command = command_for_service(blocks, "specspace-api")
    if not api_command:
        errors.append("specspace-api must declare a command list")
    actual_artifact_base_url = command_value_after(api_command, "--artifact-base-url")
    if actual_artifact_base_url is None:
        errors.append(f"{target_file} must configure --artifact-base-url on specspace-api")
    elif actual_artifact_base_url != artifact_base_url:
        errors.append(
            f"{target_file} specspace-api command must point at artifact base URL "
            f"{artifact_base_url}, got {actual_artifact_base_url}"
        )
    actual_product_workspace_args = command_values_after(
        api_command,
        "--product-workspace-artifact-base-url",
    )
    actual_product_workspace_urls: dict[str, str] = {}
    for entry in actual_product_workspace_args:
        if "=" not in entry:
            errors.append(
                f"{target_file} product workspace artifact URL binding must use "
                f"WORKSPACE_ID=URL, got {entry!r}"
            )
            continue
        workspace_id, url = entry.split("=", 1)
        actual_product_workspace_urls[workspace_id] = url
    if not actual_product_workspace_urls:
        errors.append(
            f"{target_file} must configure --product-workspace-artifact-base-url "
            "on specspace-api"
        )
    elif actual_product_workspace_urls != product_workspace_artifact_base_urls:
        errors.append(
            f"{target_file} specspace-api command must point at product workspace "
            f"artifact base URLs {product_workspace_artifact_base_urls}, got "
            f"{actual_product_workspace_urls}"
        )
    actual_specpm_registry_url = command_value_after(api_command, "--specpm-registry-url")
    if actual_specpm_registry_url is None:
        errors.append(f"{target_file} must configure --specpm-registry-url on specspace-api")
    elif actual_specpm_registry_url != specpm_registry_url:
        errors.append(
            f"{target_file} specspace-api command must point at SpecPM registry URL "
            f"{specpm_registry_url}, got {actual_specpm_registry_url}"
        )

    api_environment = environment_for_service(blocks, "specspace-api")
    expected_compile_enabled = str(hyperprompt_runtime.http_compile_enabled).lower()
    actual_compile_enabled = api_environment.get(
        "SPECSPACE_HYPERPROMPT_HTTP_COMPILE_ENABLED"
    )
    if actual_compile_enabled != expected_compile_enabled:
        errors.append(
            f"{target_file} specspace-api environment must set "
            "SPECSPACE_HYPERPROMPT_HTTP_COMPILE_ENABLED to "
            f"{expected_compile_enabled}, got {actual_compile_enabled!r}"
        )
    if hyperprompt_runtime.http_compile_enabled:
        expected_hyperprompt_environment = {
            "SPECSPACE_HYPERPROMPT_WORK_DIR": hyperprompt_runtime.work_dir,
            "SPECSPACE_HYPERPROMPT_COMPILE_TIMEOUT_SECONDS": (
                hyperprompt_runtime.compile_timeout_seconds
            ),
            "SPECSPACE_HYPERPROMPT_MAX_INPUT_BYTES": hyperprompt_runtime.max_input_bytes,
            "SPECSPACE_HYPERPROMPT_MAX_OUTPUT_BYTES": hyperprompt_runtime.max_output_bytes,
            "SPECSPACE_HYPERPROMPT_BUNDLE_RETENTION_COUNT": (
                hyperprompt_runtime.bundle_retention_count
            ),
        }
        for key, expected in expected_hyperprompt_environment.items():
            actual = api_environment.get(key)
            if actual != expected:
                errors.append(
                    f"{target_file} specspace-api environment must set {key} "
                    f"to {expected}, got {actual!r}"
                )

    for service_name in ("app", "specspace-api"):
        image = image_for_service(blocks, service_name)
        if image is None:
            errors.append(f"{service_name} must declare an image")
        elif ":latest" in image:
            errors.append(f"{service_name} image must not use latest: {image}")
        elif not DIGEST_IMAGE_RE.match(image):
            errors.append(f"{service_name} image must be digest-pinned: {image}")

    return errors


def deploy_timeweb_render(args: argparse.Namespace) -> int:
    manifest = write_timeweb_manifest(args)
    hyperprompt_runtime = timeweb_hyperprompt_runtime_from_args(args)
    errors = validate_timeweb_manifest_tree(
        manifest.output_dir,
        artifact_base_url=args.artifact_base_url,
        product_workspace_artifact_base_urls=product_workspace_artifact_base_urls_from_args(args),
        specpm_registry_url=args.specpm_registry_url,
        hyperprompt_runtime=hyperprompt_runtime,
    )
    if errors:
        raise PlatformError("generated Timeweb manifest is invalid: " + "; ".join(errors))

    payload = {
        "action": "timeweb-render",
        "output_dir": str(manifest.output_dir),
        "compose_file": str(manifest.compose_file),
        "readme": str(manifest.readme),
        "manifest": str(manifest.manifest),
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"timeweb manifest: {manifest.output_dir}")
        print(f"compose: {manifest.compose_file}")
        print(f"manifest: {manifest.manifest}")
    return 0


def deploy_timeweb_validate(args: argparse.Namespace) -> int:
    root = Path(args.path)
    hyperprompt_runtime = timeweb_hyperprompt_runtime_from_args(args)
    errors = validate_timeweb_manifest_tree(
        root,
        artifact_base_url=args.artifact_base_url,
        product_workspace_artifact_base_urls=product_workspace_artifact_base_urls_from_args(args),
        specpm_registry_url=args.specpm_registry_url,
        hyperprompt_runtime=hyperprompt_runtime,
    )
    payload = {
        "action": "timeweb-validate",
        "path": str(root),
        "valid": not errors,
        "errors": errors,
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif errors:
        print("\n".join(errors))
    else:
        print(f"Timeweb deploy tree OK: {root}")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="platform",
        description="Operate local 0AL Platform metadata.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    workspace_parser = subcommands.add_parser(
        "workspace",
        help="Inspect Platform workspace catalog entries.",
    )
    workspace_subcommands = workspace_parser.add_subparsers(
        dest="workspace_command",
        required=True,
    )

    list_parser = workspace_subcommands.add_parser(
        "list",
        help="List known workspaces from the Platform catalog.",
    )
    list_parser.add_argument(
        "--catalog",
        help=(
            "Path to a workspace catalog. Defaults to "
            "PLATFORM_WORKSPACES_CATALOG, workspaces.local.yaml, then "
            "workspaces.example.yaml."
        ),
    )
    list_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    list_parser.add_argument(
        "--kind",
        choices=["core_repository", "product_workspace"],
        help="Only include workspaces of this kind.",
    )
    list_parser.add_argument(
        "--status",
        choices=["active", "inactive", "archived"],
        help="Only include workspaces with this status.",
    )
    list_parser.set_defaults(func=workspace_list)

    doctor_parser = workspace_subcommands.add_parser(
        "doctor",
        help="Validate workspace catalog structure, profiles, paths, and references.",
    )
    doctor_parser.add_argument(
        "--catalog",
        help=(
            "Path to a workspace catalog. Defaults to "
            "PLATFORM_WORKSPACES_CATALOG, workspaces.local.yaml, then "
            "workspaces.example.yaml."
        ),
    )
    doctor_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    doctor_parser.set_defaults(func=workspace_doctor)

    init_parser = workspace_subcommands.add_parser(
        "init",
        help="Initialize a new product workspace via SpecGraph.",
    )
    init_parser.add_argument("--project-id", required=True)
    init_parser.add_argument(
        "--path",
        required=True,
        help=(
            "Absolute workspace root, or ${ORG_ROOT}/<rel>. "
            "Must not exist or must be an empty directory."
        ),
    )
    init_parser.add_argument(
        "--display-name",
        help="Operator-facing name. Defaults to --project-id when omitted.",
    )
    init_parser.add_argument("--root-intent")
    init_parser.add_argument(
        "--governance-profile",
        choices=["product_workspace"],
        default="product_workspace",
    )
    init_parser.add_argument(
        "--catalog",
        help=(
            "Catalog to update. Defaults to workspaces.local.yaml. "
            "Refuses to write the tracked example."
        ),
    )
    init_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve inputs and print the planned command without invoking SpecGraph.",
    )
    init_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    init_parser.set_defaults(func=workspace_init)

    deployment_profile_parser = subcommands.add_parser(
        "deployment-profile",
        help="Validate deployment profile authority boundaries.",
    )
    deployment_profile_subcommands = deployment_profile_parser.add_subparsers(
        dest="deployment_profile_command",
        required=True,
    )
    deployment_profile_validate_parser = deployment_profile_subcommands.add_parser(
        "validate",
        help="Validate a Platform deployment profile JSON artifact.",
    )
    deployment_profile_validate_parser.add_argument(
        "--profile",
        required=True,
        help="Path to a platform_deployment_profile JSON artifact.",
    )
    deployment_profile_validate_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    deployment_profile_validate_parser.set_defaults(func=deployment_profile_validate)

    git_service_parser = subcommands.add_parser(
        "git-service",
        help="Validate Git Service operation contracts and envelopes.",
    )
    git_service_subcommands = git_service_parser.add_subparsers(
        dest="git_service_command",
        required=True,
    )
    git_service_contract_parser = git_service_subcommands.add_parser(
        "validate-contract",
        help="Validate a Git Service operation contract JSON artifact.",
    )
    git_service_contract_parser.add_argument(
        "--contract",
        required=True,
        help="Path to a Git Service operation contract JSON artifact.",
    )
    git_service_contract_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    git_service_contract_parser.set_defaults(func=git_service_validate_contract)
    git_service_request_parser = git_service_subcommands.add_parser(
        "validate-request",
        help="Validate a Git Service operation request envelope.",
    )
    git_service_request_parser.add_argument(
        "--request",
        required=True,
        help="Path to a Git Service operation request JSON artifact.",
    )
    git_service_request_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    git_service_request_parser.set_defaults(func=git_service_validate_request)
    git_service_response_parser = git_service_subcommands.add_parser(
        "validate-response",
        help="Validate a Git Service operation response envelope.",
    )
    git_service_response_parser.add_argument(
        "--response",
        required=True,
        help="Path to a Git Service operation response JSON artifact.",
    )
    git_service_response_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    git_service_response_parser.set_defaults(func=git_service_validate_response)
    git_service_execute_parser = git_service_subcommands.add_parser(
        "execute-promotion",
        help=(
            "Orchestrate a promotion request through the local graph-repository "
            "adapter sequence."
        ),
    )
    git_service_execute_parser.add_argument(
        "--contract",
        required=True,
        help="Path to a Git Service operation contract JSON artifact.",
    )
    git_service_execute_parser.add_argument(
        "--promotion-request",
        required=True,
        help="Path to a platform_graph_repository_promotion_request artifact.",
    )
    git_service_execute_parser.add_argument(
        "--approval-decision",
        required=True,
        help=(
            "Path to a candidate_approval_decision artifact. Git Service "
            "execution requires an approved, ready decision."
        ),
    )
    git_service_execute_parser.add_argument(
        "--deployment-profile",
        default=str(DEFAULT_PRODUCT_IDEA_TO_SPEC_DEPLOYMENT_PROFILE),
        help=(
            "Path to a platform_deployment_profile artifact. Defaults to the "
            "product idea-to-spec workbench profile."
        ),
    )
    git_service_execute_parser.add_argument(
        "--repository-dir",
        required=True,
        help="Local Git checkout that owns the candidate worktree.",
    )
    git_service_execute_parser.add_argument(
        "--workspace-dir",
        required=True,
        help="Target directory for the candidate Git worktree.",
    )
    git_service_execute_parser.add_argument(
        "--materialized-source-dir",
        help=(
            "Directory containing materialized candidate files at the same "
            "relative paths listed by the promotion request."
        ),
    )
    git_service_execute_parser.add_argument(
        "--message",
        help="Commit message. Defaults to the promotion request review title.",
    )
    git_service_execute_parser.add_argument(
        "--repo",
        help="Optional GitHub repository passed to gh as owner/name.",
    )
    git_service_execute_parser.add_argument(
        "--gh-bin",
        default="gh",
        help="GitHub CLI executable to use for open-review.",
    )
    git_service_execute_parser.add_argument(
        "--open-review-dry-run",
        action="store_true",
        help="Validate and render open-review without pushing or creating a PR.",
    )
    git_service_execute_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and render the planned execution without adapter writes.",
    )
    git_service_execute_parser.add_argument(
        "--output",
        help="Optional path where the execution report JSON should be written.",
    )
    git_service_execute_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist the execution report.",
    )
    git_service_execute_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    git_service_execute_parser.set_defaults(func=git_service_execute_promotion)
    git_service_finalize_parser = git_service_subcommands.add_parser(
        "finalize-promotion",
        help=(
            "Inspect review status and publish a read model through the Git "
            "Service post-review boundary."
        ),
    )
    git_service_finalize_parser.add_argument(
        "--contract",
        required=True,
        help="Path to a Git Service operation contract JSON artifact.",
    )
    git_service_finalize_parser.add_argument(
        "--open-review-report",
        required=True,
        help="Path to a graph repository open-review report.",
    )
    git_service_finalize_parser.add_argument(
        "--worktree-dir",
        required=True,
        help="Candidate worktree that owns the open-review report.",
    )
    git_service_finalize_parser.add_argument(
        "--bundle-dir",
        required=True,
        help="Public-safe read-model bundle directory to publish after merge.",
    )
    git_service_finalize_parser.add_argument(
        "--output-dir",
        required=True,
        help="Destination directory for the published read model.",
    )
    git_service_finalize_parser.add_argument(
        "--manifest-name",
        default="artifact_manifest.json",
        help="Required bundle manifest file name.",
    )
    git_service_finalize_parser.add_argument(
        "--repo",
        help="Optional GitHub repository passed to gh as owner/name.",
    )
    git_service_finalize_parser.add_argument(
        "--gh-bin",
        default="gh",
        help="GitHub CLI executable to use for review-status.",
    )
    git_service_finalize_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect review state and validate read-model publication only.",
    )
    git_service_finalize_parser.add_argument(
        "--output",
        help="Optional path where the finalization report JSON should be written.",
    )
    git_service_finalize_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist the finalization report.",
    )
    git_service_finalize_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    git_service_finalize_parser.set_defaults(func=git_service_finalize_promotion)

    graph_repository_parser = subcommands.add_parser(
        "graph-repository",
        help="Validate Graph Repository Service contracts.",
    )
    graph_repository_subcommands = graph_repository_parser.add_subparsers(
        dest="graph_repository_command",
        required=True,
    )
    graph_repository_validate_parser = graph_repository_subcommands.add_parser(
        "validate",
        help="Validate a Graph Repository Service contract JSON artifact.",
    )
    graph_repository_validate_parser.add_argument(
        "--contract",
        required=True,
        help="Path to a graph repository service contract JSON artifact.",
    )
    graph_repository_validate_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    graph_repository_validate_parser.set_defaults(func=graph_repository_validate)
    graph_repository_plan_parser = graph_repository_subcommands.add_parser(
        "plan",
        help=(
            "Build a report-only graph repository execution plan from "
            "SpecGraph run artifacts."
        ),
    )
    graph_repository_plan_parser.add_argument(
        "--contract",
        required=True,
        help="Path to a graph repository service contract JSON artifact.",
    )
    graph_repository_plan_parser.add_argument(
        "--runs-dir",
        required=True,
        help="Directory containing required SpecGraph run JSON artifacts.",
    )
    graph_repository_plan_parser.add_argument(
        "--output",
        help="Optional path where the execution plan JSON should be written.",
    )
    graph_repository_plan_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    graph_repository_plan_parser.set_defaults(func=graph_repository_plan)
    graph_repository_prepare_parser = graph_repository_subcommands.add_parser(
        "prepare-local",
        help="Prepare a local candidate workspace from a ready execution plan.",
    )
    graph_repository_prepare_parser.add_argument(
        "--plan",
        required=True,
        help="Path to a graph repository execution plan JSON artifact.",
    )
    graph_repository_prepare_parser.add_argument(
        "--candidate-id",
        required=True,
        help="Stable candidate id used to derive the candidate branch name.",
    )
    graph_repository_prepare_parser.add_argument(
        "--workspace-dir",
        required=True,
        help="Empty directory where local candidate workspace metadata will be written.",
    )
    graph_repository_prepare_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render the local preparation report without writing files.",
    )
    graph_repository_prepare_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    graph_repository_prepare_parser.set_defaults(func=graph_repository_prepare_local)
    graph_repository_promotion_parser = graph_repository_subcommands.add_parser(
        "promotion-request",
        help="Build a report-only request to promote a candidate graph to review.",
    )
    graph_repository_promotion_parser.add_argument(
        "--plan",
        required=True,
        help="Path to a graph repository execution plan JSON artifact.",
    )
    graph_repository_promotion_parser.add_argument(
        "--candidate-id",
        required=True,
        help="Stable candidate id used to derive the candidate branch name.",
    )
    graph_repository_promotion_parser.add_argument(
        "--workflow-lane",
        default="product_idea_to_spec",
        choices=["product_idea_to_spec", "specgraph_bootstrap"],
        help="Workflow lane represented by this promotion request.",
    )
    graph_repository_promotion_parser.add_argument(
        "--deployment-profile-id",
        default="product_idea_to_spec_workbench",
        help="Deployment profile id expected to authorize this request.",
    )
    graph_repository_promotion_parser.add_argument(
        "--target-repository-role",
        default="product_spec_workspace",
        choices=["product_spec_workspace", "specgraph_bootstrap"],
        help="Repository role targeted by this promotion request.",
    )
    graph_repository_promotion_parser.add_argument(
        "--authority-profile",
        default="workspace_owner_controlled",
        choices=[
            "workspace_owner_controlled",
            "maintainer_bootstrap_controlled",
            "self_evolution",
        ],
        help="Authority profile expected to authorize this request.",
    )
    graph_repository_promotion_parser.add_argument(
        "--path",
        action="append",
        default=[],
        help=(
            "Materialized candidate path to include in the future review commit. "
            "May be provided multiple times."
        ),
    )
    graph_repository_promotion_parser.add_argument(
        "--base",
        default="main",
        help="Base branch for the future review pull request.",
    )
    graph_repository_promotion_parser.add_argument(
        "--title",
        required=True,
        help="Review title requested for the future pull request.",
    )
    graph_repository_promotion_parser.add_argument(
        "--body",
        required=True,
        help="Review body requested for the future pull request.",
    )
    graph_repository_promotion_parser.add_argument(
        "--output",
        help="Optional path where the promotion request JSON should be written.",
    )
    graph_repository_promotion_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render the promotion request without writing files.",
    )
    graph_repository_promotion_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    graph_repository_promotion_parser.set_defaults(
        func=graph_repository_promotion_request
    )
    graph_repository_worktree_parser = graph_repository_subcommands.add_parser(
        "prepare-worktree",
        help="Create a local Git worktree from a ready graph repository execution plan.",
    )
    graph_repository_worktree_parser.add_argument(
        "--plan",
        required=True,
        help="Path to a graph repository execution plan JSON artifact.",
    )
    graph_repository_worktree_parser.add_argument(
        "--repository-dir",
        required=True,
        help="Local Git checkout that owns the candidate worktree.",
    )
    graph_repository_worktree_parser.add_argument(
        "--candidate-id",
        required=True,
        help="Stable candidate id used to derive the candidate branch name.",
    )
    graph_repository_worktree_parser.add_argument(
        "--workspace-dir",
        required=True,
        help="Target directory for the local Git worktree.",
    )
    graph_repository_worktree_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render planned Git commands without executing them.",
    )
    graph_repository_worktree_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    graph_repository_worktree_parser.set_defaults(
        func=graph_repository_prepare_worktree
    )
    graph_repository_commit_parser = graph_repository_subcommands.add_parser(
        "commit-worktree",
        help="Create a candidate-branch commit from explicit worktree paths.",
    )
    graph_repository_commit_parser.add_argument(
        "--prepare-report",
        required=True,
        help="Path to a graph repository worktree prepare report.",
    )
    graph_repository_commit_parser.add_argument(
        "--worktree-dir",
        required=True,
        help="Git worktree containing materialized candidate changes.",
    )
    graph_repository_commit_parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Relative worktree path to stage. May be provided multiple times.",
    )
    graph_repository_commit_parser.add_argument(
        "--message",
        required=True,
        help="Commit message for the candidate branch review commit.",
    )
    graph_repository_commit_parser.add_argument(
        "--author-name",
        default="Platform Graph Repository",
        help="Git author name for the candidate branch review commit.",
    )
    graph_repository_commit_parser.add_argument(
        "--author-email",
        default="platform@example.invalid",
        help="Git author email for the candidate branch review commit.",
    )
    graph_repository_commit_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    graph_repository_commit_parser.set_defaults(func=graph_repository_commit_worktree)
    graph_repository_review_parser = graph_repository_subcommands.add_parser(
        "open-review",
        help="Push a candidate branch and open a pull request review.",
    )
    graph_repository_review_parser.add_argument(
        "--commit-report",
        required=True,
        help="Path to a graph repository review commit report.",
    )
    graph_repository_review_parser.add_argument(
        "--worktree-dir",
        required=True,
        help="Git worktree containing the candidate branch commit.",
    )
    graph_repository_review_parser.add_argument(
        "--base",
        default="main",
        help="Base branch for the review pull request.",
    )
    graph_repository_review_parser.add_argument(
        "--title",
        required=True,
        help="Pull request title.",
    )
    graph_repository_review_parser.add_argument(
        "--body",
        required=True,
        help="Pull request body.",
    )
    graph_repository_review_parser.add_argument(
        "--repo",
        help="Optional GitHub repository passed to gh as owner/name.",
    )
    graph_repository_review_parser.add_argument(
        "--gh-bin",
        default="gh",
        help="GitHub CLI executable to use.",
    )
    graph_repository_review_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render planned push/review commands without executing them.",
    )
    graph_repository_review_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    graph_repository_review_parser.set_defaults(func=graph_repository_open_review)
    graph_repository_status_parser = graph_repository_subcommands.add_parser(
        "review-status",
        help="Inspect pull request status from an open review report.",
    )
    graph_repository_status_parser.add_argument(
        "--open-review-report",
        required=True,
        help="Path to a graph repository open review report.",
    )
    graph_repository_status_parser.add_argument(
        "--worktree-dir",
        required=True,
        help="Worktree directory where the status report should be written.",
    )
    graph_repository_status_parser.add_argument(
        "--repo",
        help="Optional GitHub repository passed to gh as owner/name.",
    )
    graph_repository_status_parser.add_argument(
        "--gh-bin",
        default="gh",
        help="GitHub CLI executable to use.",
    )
    graph_repository_status_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    graph_repository_status_parser.set_defaults(func=graph_repository_review_status)
    graph_repository_publish_parser = graph_repository_subcommands.add_parser(
        "publish-read-model",
        help="Publish a public-safe read-model bundle after merged review status.",
    )
    graph_repository_publish_parser.add_argument(
        "--review-status-report",
        required=True,
        help="Path to a graph repository review status report.",
    )
    graph_repository_publish_parser.add_argument(
        "--bundle-dir",
        required=True,
        help="Public-safe read-model bundle directory to publish.",
    )
    graph_repository_publish_parser.add_argument(
        "--output-dir",
        required=True,
        help="Destination directory for the published read model.",
    )
    graph_repository_publish_parser.add_argument(
        "--manifest-name",
        default="artifact_manifest.json",
        help="Required bundle manifest file name.",
    )
    graph_repository_publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate publish readiness without copying the bundle.",
    )
    graph_repository_publish_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    graph_repository_publish_parser.set_defaults(
        func=graph_repository_publish_read_model
    )

    product_repair_parser = subcommands.add_parser(
        "product-repair-rerun",
        help="Validate and execute controlled product repair rerun handoffs.",
    )
    product_repair_subcommands = product_repair_parser.add_subparsers(
        dest="product_repair_rerun_command",
        required=True,
    )
    product_repair_plan_parser = product_repair_subcommands.add_parser(
        "plan",
        help="Build a controlled execution plan for a SpecSpace repair rerun request.",
    )
    product_repair_plan_parser.add_argument(
        "--deployment-profile",
        default=str(DEFAULT_PRODUCT_IDEA_TO_SPEC_DEPLOYMENT_PROFILE),
        help=(
            "Path to a platform_deployment_profile artifact. Defaults to the "
            "product idea-to-spec workbench profile."
        ),
    )
    product_repair_plan_parser.add_argument(
        "--specgraph-dir",
        default=str((REPO_ROOT.parent / "SpecGraph").resolve()),
        help="Local SpecGraph checkout that owns the repair rerun make target.",
    )
    product_repair_plan_parser.add_argument(
        "--rerun-request",
        help=(
            "SpecSpace-owned rerun request state artifact. Defaults to "
            "runs/idea_to_spec_repair_rerun_requests.json under --specgraph-dir."
        ),
    )
    product_repair_plan_parser.add_argument(
        "--import-preview",
        help=(
            "SpecGraph import preview for SpecSpace repair drafts. Defaults to "
            "runs/specspace_repair_draft_import_preview.json under --specgraph-dir."
        ),
    )
    product_repair_plan_parser.add_argument(
        "--repair-session",
        help=(
            "Idea-to-spec repair session journal. Defaults to "
            "runs/idea_to_spec_repair_session.json under --specgraph-dir."
        ),
    )
    product_repair_plan_parser.add_argument(
        "--request-gate",
        help=(
            "SpecGraph rerun request gate artifact. Defaults to "
            "runs/specspace_repair_rerun_request_gate.json under --specgraph-dir."
        ),
    )
    product_repair_plan_parser.add_argument(
        "--output",
        help="Optional path where the execution plan JSON should be written.",
    )
    product_repair_plan_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_repair_plan_parser.set_defaults(func=product_repair_rerun_plan)

    product_repair_execute_parser = product_repair_subcommands.add_parser(
        "execute",
        help="Run the allowed SpecGraph repair rerun make target from a ready plan.",
    )
    product_repair_execute_parser.add_argument(
        "--plan",
        required=True,
        help="Path to a platform_product_repair_rerun_execution_plan artifact.",
    )
    product_repair_execute_parser.add_argument(
        "--python",
        help="Optional PYTHON make variable passed to SpecGraph.",
    )
    product_repair_execute_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render the make invocation without executing it.",
    )
    product_repair_execute_parser.add_argument(
        "--output",
        help="Optional path where the execution report JSON should be written.",
    )
    product_repair_execute_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist the execution report.",
    )
    product_repair_execute_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_repair_execute_parser.set_defaults(func=product_repair_rerun_execute)

    product_repair_publish_parser = product_repair_subcommands.add_parser(
        "publish",
        help="Publish and verify public-safe SpecGraph repair rerun artifacts.",
    )
    product_repair_publish_parser.add_argument(
        "--execution-report",
        required=True,
        help="Path to a platform_product_repair_rerun_execution_report artifact.",
    )
    product_repair_publish_parser.add_argument(
        "--specgraph-dir",
        help=(
            "Local SpecGraph checkout. Defaults to specgraph_dir from the "
            "execution report."
        ),
    )
    product_repair_publish_parser.add_argument(
        "--python",
        help="Optional PYTHON make variable passed to publish-bundle.",
    )
    product_repair_publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render publication without running publish-bundle.",
    )
    product_repair_publish_parser.add_argument(
        "--output",
        help="Optional path where the publication report JSON should be written.",
    )
    product_repair_publish_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist the publication report.",
    )
    product_repair_publish_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_repair_publish_parser.set_defaults(func=product_repair_rerun_publish)

    product_repair_smoke_parser = product_repair_subcommands.add_parser(
        "smoke",
        help="Run an end-to-end product repair rerun demo smoke.",
    )
    product_repair_smoke_parser.add_argument(
        "--deployment-profile",
        default=str(DEFAULT_PRODUCT_IDEA_TO_SPEC_DEPLOYMENT_PROFILE),
        help=(
            "Path to a platform_deployment_profile artifact. Defaults to the "
            "product idea-to-spec workbench profile."
        ),
    )
    product_repair_smoke_parser.add_argument(
        "--specgraph-dir",
        default=str((REPO_ROOT.parent / "SpecGraph").resolve()),
        help="Local SpecGraph checkout that owns the repair rerun make target.",
    )
    product_repair_smoke_parser.add_argument(
        "--rerun-request",
        help=(
            "SpecSpace-owned rerun request state artifact. Defaults to "
            "runs/idea_to_spec_repair_rerun_requests.json under --specgraph-dir."
        ),
    )
    product_repair_smoke_parser.add_argument(
        "--import-preview",
        help=(
            "SpecGraph import preview for SpecSpace repair drafts. Defaults to "
            "runs/specspace_repair_draft_import_preview.json under --specgraph-dir."
        ),
    )
    product_repair_smoke_parser.add_argument(
        "--repair-session",
        help=(
            "Idea-to-spec repair session journal. Defaults to "
            "runs/idea_to_spec_repair_session.json under --specgraph-dir."
        ),
    )
    product_repair_smoke_parser.add_argument(
        "--request-gate",
        help=(
            "SpecGraph rerun request gate artifact. Defaults to "
            "runs/specspace_repair_rerun_request_gate.json under --specgraph-dir."
        ),
    )
    product_repair_smoke_parser.add_argument(
        "--python",
        help="Optional PYTHON make variable passed to SpecGraph targets.",
    )
    product_repair_smoke_parser.add_argument(
        "--plan-output",
        help=(
            "Optional path for the intermediate product repair rerun execution "
            "plan. Defaults to runs/platform_product_repair_rerun_execution_plan.json."
        ),
    )
    product_repair_smoke_parser.add_argument(
        "--execution-output",
        help=(
            "Optional path for the intermediate product repair rerun execution "
            "report. Defaults to runs/platform_product_repair_rerun_execution_report.json."
        ),
    )
    product_repair_smoke_parser.add_argument(
        "--publication-output",
        help=(
            "Optional path for the intermediate product repair rerun publication "
            "report. Defaults to runs/platform_product_repair_rerun_publication_report.json."
        ),
    )
    product_repair_smoke_parser.add_argument(
        "--output",
        help=(
            "Optional path where the smoke report JSON should be written. "
            "Defaults to runs/platform_product_repair_rerun_smoke_report.json."
        ),
    )
    product_repair_smoke_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist the smoke report.",
    )
    product_repair_smoke_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_repair_smoke_parser.set_defaults(func=product_repair_rerun_smoke)

    product_candidate_approval_parser = subcommands.add_parser(
        "product-candidate-approval",
        help="Validate SpecSpace candidate approval intents and materialize approval decisions.",
    )
    product_candidate_approval_subcommands = (
        product_candidate_approval_parser.add_subparsers(
            dest="product_candidate_approval_command",
            required=True,
        )
    )
    product_candidate_approval_gate_parser = (
        product_candidate_approval_subcommands.add_parser(
            "gate",
            help="Build a read-only gate report for a SpecSpace candidate approval intent.",
        )
    )
    product_candidate_approval_gate_parser.add_argument(
        "--deployment-profile",
        default=str(DEFAULT_PRODUCT_IDEA_TO_SPEC_DEPLOYMENT_PROFILE),
        help=(
            "Path to a platform_deployment_profile artifact. Defaults to the "
            "product idea-to-spec workbench profile."
        ),
    )
    product_candidate_approval_gate_parser.add_argument(
        "--specgraph-dir",
        default=str((REPO_ROOT.parent / "SpecGraph").resolve()),
        help="Local SpecGraph checkout that owns product idea-to-spec runs.",
    )
    product_candidate_approval_gate_parser.add_argument(
        "--approval-intents",
        help=(
            "SpecSpace-owned candidate approval intent state. Defaults to "
            "runs/idea_to_spec_candidate_approval_intents.json under --specgraph-dir."
        ),
    )
    product_candidate_approval_gate_parser.add_argument(
        "--repair-session",
        help=(
            "Idea-to-spec repair session journal. Defaults to "
            "runs/idea_to_spec_repair_session.json under --specgraph-dir."
        ),
    )
    product_candidate_approval_gate_parser.add_argument(
        "--promotion-gate",
        help=(
            "Idea-to-spec promotion gate artifact. Defaults to "
            "runs/idea_to_spec_promotion_gate.json under --specgraph-dir."
        ),
    )
    product_candidate_approval_gate_parser.add_argument(
        "--repair-execution",
        help=(
            "Platform product repair rerun execution report. Defaults to "
            "runs/platform_product_repair_rerun_execution_report.json under "
            "--specgraph-dir."
        ),
    )
    product_candidate_approval_gate_parser.add_argument(
        "--repair-publication",
        help=(
            "Platform product repair rerun publication report. Defaults to "
            "runs/platform_product_repair_rerun_publication_report.json under "
            "--specgraph-dir."
        ),
    )
    product_candidate_approval_gate_parser.add_argument(
        "--workspace-id",
        help="Optional workspace id used to select the active SpecSpace intent.",
    )
    product_candidate_approval_gate_parser.add_argument(
        "--path",
        action="append",
        default=[],
        help=(
            "Materialized candidate path approved for future Git Service promotion. "
            "May be provided multiple times."
        ),
    )
    product_candidate_approval_gate_parser.add_argument(
        "--output",
        help=(
            "Optional path where the gate report JSON should be written. Defaults to "
            "runs/platform_candidate_approval_intent_gate_report.json."
        ),
    )
    product_candidate_approval_gate_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist the gate report.",
    )
    product_candidate_approval_gate_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_candidate_approval_gate_parser.set_defaults(
        func=product_candidate_approval_gate
    )

    product_candidate_approval_materialize_parser = (
        product_candidate_approval_subcommands.add_parser(
            "materialize",
            help="Materialize a candidate_approval_decision from a ready gate report.",
        )
    )
    product_candidate_approval_materialize_parser.add_argument(
        "--gate-report",
        required=True,
        help="Path to a platform_candidate_approval_intent_gate_report artifact.",
    )
    product_candidate_approval_materialize_parser.add_argument(
        "--output",
        help=(
            "Optional path where candidate_approval_decision JSON should be written. "
            "Defaults to candidate_approval_decision.json next to the gate report."
        ),
    )
    product_candidate_approval_materialize_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist a blocked decision report when the gate is not ready.",
    )
    product_candidate_approval_materialize_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_candidate_approval_materialize_parser.set_defaults(
        func=product_candidate_approval_materialize
    )

    product_candidate_promotion_parser = subcommands.add_parser(
        "product-candidate-promotion",
        help="Build product idea-to-spec promotion request handoff artifacts.",
    )
    product_candidate_promotion_subcommands = (
        product_candidate_promotion_parser.add_subparsers(
            dest="product_candidate_promotion_command",
            required=True,
        )
    )
    product_candidate_promotion_request_parser = (
        product_candidate_promotion_subcommands.add_parser(
            "request",
            help=(
                "Build a graph repository promotion request from a ready "
                "candidate approval decision."
            ),
        )
    )
    product_candidate_promotion_request_parser.add_argument(
        "--plan",
        required=True,
        help="Path to a platform_graph_repository_execution_plan artifact.",
    )
    product_candidate_promotion_request_parser.add_argument(
        "--approval-decision",
        required=True,
        help="Path to a candidate_approval_decision artifact.",
    )
    product_candidate_promotion_request_parser.add_argument(
        "--deployment-profile-id",
        default="product_idea_to_spec_workbench",
        help="Deployment profile id expected to authorize this request.",
    )
    product_candidate_promotion_request_parser.add_argument(
        "--authority-profile",
        default="workspace_owner_controlled",
        choices=[
            "workspace_owner_controlled",
            "maintainer_bootstrap_controlled",
            "self_evolution",
        ],
        help="Authority profile expected to authorize this request.",
    )
    product_candidate_promotion_request_parser.add_argument(
        "--base",
        default="main",
        help="Base branch for the future review pull request.",
    )
    product_candidate_promotion_request_parser.add_argument(
        "--title",
        help=(
            "Optional review title. Defaults to a title derived from the "
            "candidate approval decision."
        ),
    )
    product_candidate_promotion_request_parser.add_argument(
        "--body",
        help=(
            "Optional review body. Defaults to the candidate approval decision "
            "reason."
        ),
    )
    product_candidate_promotion_request_parser.add_argument(
        "--output",
        help=(
            "Optional path where the promotion request JSON should be written. "
            "Defaults to graph_repository_promotion_request.json next to --plan."
        ),
    )
    product_candidate_promotion_request_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render the promotion request without writing files.",
    )
    product_candidate_promotion_request_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_candidate_promotion_request_parser.set_defaults(
        func=product_candidate_promotion_request
    )

    product_candidate_promotion_execute_parser = (
        product_candidate_promotion_subcommands.add_parser(
            "execute",
            help=(
                "Run controlled Git Service promotion execution from a ready "
                "product promotion request."
            ),
        )
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--contract",
        default=str(REPO_ROOT / "git-service-operation-contract.example.json"),
        help="Path to a Git Service operation contract JSON artifact.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--promotion-request",
        required=True,
        help="Path to a platform_graph_repository_promotion_request artifact.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--approval-decision",
        required=True,
        help="Path to a candidate_approval_decision artifact.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--deployment-profile",
        default=str(DEFAULT_PRODUCT_IDEA_TO_SPEC_DEPLOYMENT_PROFILE),
        help=(
            "Path to a platform_deployment_profile artifact. Defaults to the "
            "product idea-to-spec workbench profile."
        ),
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--repository-dir",
        required=True,
        help="Local Git checkout that owns the candidate worktree.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--workspace-dir",
        required=True,
        help="Target directory for the candidate Git worktree.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--materialized-source-dir",
        help=(
            "Directory containing materialized candidate files. Defaults to "
            "runs/materialized_candidate_specs beside the execution plan runs_dir."
        ),
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--message",
        help="Commit message. Defaults to the promotion request review title.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--repo",
        help="Optional GitHub repository passed to gh as owner/name.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--gh-bin",
        default="gh",
        help="GitHub CLI executable to use for open-review.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--git-service-output",
        help=(
            "Optional path for the inner Git Service execution report. Defaults "
            "to a sibling report beside the product execution report in dry-run "
            "mode and to .platform/git_service_promotion_execution_report.json "
            "in the candidate worktree otherwise."
        ),
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--open-review-dry-run",
        action="store_true",
        help="Validate commit/open-review flow without pushing or creating a PR.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and render the planned execution without Git writes.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--output",
        help=(
            "Optional path where the product promotion execution report JSON "
            "should be written. Defaults to "
            "product_candidate_promotion_execution_report.json next to the "
            "promotion request."
        ),
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist the product promotion execution report.",
    )
    product_candidate_promotion_execute_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_candidate_promotion_execute_parser.set_defaults(
        func=product_candidate_promotion_execute
    )

    product_candidate_promotion_review_status_parser = (
        product_candidate_promotion_subcommands.add_parser(
            "review-status",
            help=(
                "Inspect post-review status for a product candidate promotion "
                "execution."
            ),
        )
    )
    product_candidate_promotion_review_status_parser.add_argument(
        "--execution-report",
        required=True,
        help=(
            "Path to platform_product_candidate_promotion_execution_report."
        ),
    )
    product_candidate_promotion_review_status_parser.add_argument(
        "--repo",
        help="Optional GitHub repository passed to gh as owner/name.",
    )
    product_candidate_promotion_review_status_parser.add_argument(
        "--gh-bin",
        default="gh",
        help="GitHub CLI executable to use for review status inspection.",
    )
    product_candidate_promotion_review_status_parser.add_argument(
        "--output",
        help=(
            "Optional path where the product review status report JSON should "
            "be written. Defaults to "
            "product_candidate_promotion_review_status_report.json beside the "
            "execution report."
        ),
    )
    product_candidate_promotion_review_status_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist the product review status report.",
    )
    product_candidate_promotion_review_status_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_candidate_promotion_review_status_parser.set_defaults(
        func=product_candidate_promotion_review_status
    )

    product_candidate_promotion_publish_parser = (
        product_candidate_promotion_subcommands.add_parser(
            "publish-read-model",
            help=(
                "Publish a public-safe read model after the product candidate "
                "review is merged."
            ),
        )
    )
    product_candidate_promotion_publish_parser.add_argument(
        "--review-status-report",
        required=True,
        help=(
            "Path to platform_product_candidate_promotion_review_status_report."
        ),
    )
    product_candidate_promotion_publish_parser.add_argument(
        "--bundle-dir",
        required=True,
        help="Public-safe bundle directory to publish as the read model.",
    )
    product_candidate_promotion_publish_parser.add_argument(
        "--output-dir",
        required=True,
        help="Target directory for the published read model.",
    )
    product_candidate_promotion_publish_parser.add_argument(
        "--manifest-name",
        default="artifact_manifest.json",
        help="Manifest name inside the bundle and published output.",
    )
    product_candidate_promotion_publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate publication without copying the read model.",
    )
    product_candidate_promotion_publish_parser.add_argument(
        "--output",
        help=(
            "Optional path where the product read-model publication report JSON "
            "should be written. Defaults to "
            "product_candidate_promotion_read_model_publication_report.json "
            "beside the review status report."
        ),
    )
    product_candidate_promotion_publish_parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not persist the product read-model publication report.",
    )
    product_candidate_promotion_publish_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    product_candidate_promotion_publish_parser.set_defaults(
        func=product_candidate_promotion_publish_read_model
    )

    deploy_parser = subcommands.add_parser(
        "deploy",
        help="Operate the local Docker Compose deployment profile.",
    )
    deploy_subcommands = deploy_parser.add_subparsers(
        dest="deploy_command",
        required=True,
    )

    def add_deploy_common(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--compose-file",
            help=(
                "Compose file to use. Defaults to PLATFORM_COMPOSE_FILE, "
                "docker-compose.local.yml, then docker-compose.example.yml."
            ),
        )
        command_parser.add_argument(
            "--profile",
            choices=["dev", "production-web"],
            default="dev",
            help=(
                "Deployment profile. production-web overlays the default compose "
                "file with a static SpecSpace web service."
            ),
        )
        command_parser.add_argument(
            "--env-file",
            help=(
                "Env file to pass to docker compose. Defaults to "
                "PLATFORM_ENV_FILE, then .env when present."
            ),
        )
        command_parser.add_argument(
            "--project-name",
            help=(
                "Compose project name. When omitted, Docker Compose uses its "
                "normal project-name resolution, including COMPOSE_PROJECT_NAME "
                "from the environment/.env and the compose file name."
            ),
        )
        command_parser.add_argument(
            "--docker",
            default=os.environ.get("PLATFORM_DOCKER", "docker"),
            help="Docker executable to invoke.",
        )
        command_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the docker compose command without executing it.",
        )
        command_parser.add_argument(
            "--format",
            choices=["table", "json"],
            default="table",
            help="Dry-run output format.",
        )

    render_parser = deploy_subcommands.add_parser(
        "render",
        help="Render the effective Docker Compose configuration.",
    )
    add_deploy_common(render_parser)
    render_parser.set_defaults(func=deploy)

    up_parser = deploy_subcommands.add_parser(
        "up",
        help="Start the local deployment profile with docker compose up -d.",
    )
    add_deploy_common(up_parser)
    up_parser.add_argument(
        "--build",
        action="store_true",
        help="Pass --build to docker compose up.",
    )
    up_parser.set_defaults(func=deploy)

    down_parser = deploy_subcommands.add_parser(
        "down",
        help="Stop the local deployment profile with docker compose down.",
    )
    add_deploy_common(down_parser)
    down_parser.add_argument(
        "--volumes",
        action="store_true",
        help="Pass --volumes to docker compose down.",
    )
    down_parser.set_defaults(func=deploy)

    status_parser = deploy_subcommands.add_parser(
        "status",
        help="Show docker compose service status.",
    )
    add_deploy_common(status_parser)
    status_parser.set_defaults(func=deploy)

    bundle_parser = deploy_subcommands.add_parser(
        "bundle",
        help="Write a portable Compose deploy bundle for CI artifacts.",
    )
    bundle_parser.add_argument(
        "--compose-file",
        help=(
            "Compose file to include. Defaults to PLATFORM_COMPOSE_FILE, "
            "docker-compose.local.yml, then docker-compose.example.yml."
        ),
    )
    bundle_parser.add_argument(
        "--profile",
        choices=["dev", "production-web"],
        default="production-web",
        help="Deployment profile to package. Defaults to production-web.",
    )
    bundle_parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to create or update with the deploy bundle.",
    )
    bundle_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    bundle_parser.set_defaults(func=deploy_bundle, env_file=None)

    def add_timeweb_hyperprompt_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.set_defaults(
            hyperprompt_http_compile_enabled=bool_from_env(
                "SPECSPACE_HYPERPROMPT_HTTP_COMPILE_ENABLED",
                default=True,
            )
        )
        command_parser.add_argument(
            "--enable-hyperprompt-http-compile",
            dest="hyperprompt_http_compile_enabled",
            action="store_true",
            help=(
                "Render SpecSpace HTTP-provider Hyperprompt compile settings "
                "(default for Timeweb production)."
            ),
        )
        command_parser.add_argument(
            "--disable-hyperprompt-http-compile",
            dest="hyperprompt_http_compile_enabled",
            action="store_false",
            help="Render SpecSpace HTTP-provider Hyperprompt compile as disabled.",
        )
        command_parser.add_argument(
            "--hyperprompt-work-dir",
            default=os.environ.get(
                "SPECSPACE_HYPERPROMPT_WORK_DIR",
                DEFAULT_TIMEWEB_HYPERPROMPT_WORK_DIR,
            ),
            help="Writable scratch directory for SpecSpace Hyperprompt compile.",
        )
        command_parser.add_argument(
            "--hyperprompt-compile-timeout-seconds",
            default=os.environ.get(
                "SPECSPACE_HYPERPROMPT_COMPILE_TIMEOUT_SECONDS",
                DEFAULT_TIMEWEB_HYPERPROMPT_COMPILE_TIMEOUT_SECONDS,
            ),
            help="SpecSpace Hyperprompt compile subprocess timeout.",
        )
        command_parser.add_argument(
            "--hyperprompt-max-input-bytes",
            default=os.environ.get(
                "SPECSPACE_HYPERPROMPT_MAX_INPUT_BYTES",
                DEFAULT_TIMEWEB_HYPERPROMPT_MAX_INPUT_BYTES,
            ),
            help="Maximum generated Markdown input bytes accepted by SpecSpace.",
        )
        command_parser.add_argument(
            "--hyperprompt-max-output-bytes",
            default=os.environ.get(
                "SPECSPACE_HYPERPROMPT_MAX_OUTPUT_BYTES",
                DEFAULT_TIMEWEB_HYPERPROMPT_MAX_OUTPUT_BYTES,
            ),
            help="Maximum compiled Markdown bytes returned by SpecSpace.",
        )
        command_parser.add_argument(
            "--hyperprompt-bundle-retention-count",
            default=os.environ.get(
                "SPECSPACE_HYPERPROMPT_BUNDLE_RETENTION_COUNT",
                DEFAULT_TIMEWEB_HYPERPROMPT_BUNDLE_RETENTION_COUNT,
            ),
            help="Number of SpecSpace-owned Hyperprompt scratch bundles to retain.",
        )

    timeweb_render_parser = deploy_subcommands.add_parser(
        "timeweb-render",
        help="Write a Timeweb Cloud Apps manifest-only deploy tree.",
    )
    timeweb_render_parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to create or replace with the Timeweb deploy tree.",
    )
    timeweb_render_parser.add_argument(
        "--image-lock",
        default=os.environ.get("PLATFORM_SERVICE_IMAGE_LOCK", ""),
        help=(
            "JSON platform_service_image_lock file with digest-pinned service "
            "image refs. Explicit image-ref flags or env vars override lock values."
        ),
    )
    timeweb_render_parser.add_argument(
        "--specspace-api-image-ref",
        default=os.environ.get("SPECSPACE_API_IMAGE_REF", ""),
        help="Digest-pinned SpecSpace API image ref.",
    )
    timeweb_render_parser.add_argument(
        "--specspace-ui-image-ref",
        default=os.environ.get("SPECSPACE_UI_IMAGE_REF", ""),
        help="Digest-pinned SpecSpace UI image ref.",
    )
    timeweb_render_parser.add_argument(
        "--artifact-base-url",
        default=os.environ.get("SPECSPACE_ARTIFACT_BASE_URL", "https://specgraph.tech"),
        help="Static SpecGraph artifact base URL.",
    )
    timeweb_render_parser.add_argument(
        "--product-workspace-artifact-base-url",
        action="append",
        default=(
            [os.environ["SPECSPACE_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL"]]
            if os.environ.get("SPECSPACE_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL")
            else None
        ),
        help=(
            "Static artifact base URL for a product workspace. Use "
            "WORKSPACE_ID=URL; a bare URL is kept as a compatibility shorthand "
            "for team-decision-log. May be repeated."
        ),
    )
    timeweb_render_parser.add_argument(
        "--team-decision-log-artifact-base-url",
        default=os.environ.get("SPECSPACE_TEAM_DECISION_LOG_ARTIFACT_BASE_URL", ""),
        help=(
            "Deprecated compatibility alias for --product-workspace-artifact-base-url."
        ),
    )
    timeweb_render_parser.add_argument(
        "--specpm-registry-url",
        default=os.environ.get("SPECSPACE_SPECPM_REGISTRY_URL", "https://specpm.dev"),
        help="Readonly SpecPM registry URL.",
    )
    timeweb_render_parser.add_argument(
        "--release-commit",
        default=os.environ.get("SPECSPACE_RELEASE_COMMIT"),
        help="Release commit to embed in deployment metadata.",
    )
    timeweb_render_parser.add_argument(
        "--release-created-at",
        default=os.environ.get("SPECSPACE_RELEASE_CREATED_AT"),
        help="UTC release timestamp to embed in deployment metadata.",
    )
    add_timeweb_hyperprompt_args(timeweb_render_parser)
    timeweb_render_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    timeweb_render_parser.set_defaults(func=deploy_timeweb_render)

    timeweb_validate_parser = deploy_subcommands.add_parser(
        "timeweb-validate",
        help="Validate a Timeweb Cloud Apps manifest-only deploy tree.",
    )
    timeweb_validate_parser.add_argument(
        "--path",
        required=True,
        help="Timeweb deploy tree directory to validate.",
    )
    timeweb_validate_parser.add_argument(
        "--artifact-base-url",
        default=os.environ.get("TIMEWEB_REQUIRED_ARTIFACT_BASE_URL", "https://specgraph.tech"),
        help="Required static SpecGraph artifact base URL.",
    )
    timeweb_validate_parser.add_argument(
        "--product-workspace-artifact-base-url",
        action="append",
        default=(
            [os.environ["TIMEWEB_REQUIRED_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL"]]
            if os.environ.get("TIMEWEB_REQUIRED_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL")
            else None
        ),
        help=(
            "Required static artifact base URL for a product workspace. Use "
            "WORKSPACE_ID=URL; a bare URL is kept as a compatibility shorthand "
            "for team-decision-log. May be repeated."
        ),
    )
    timeweb_validate_parser.add_argument(
        "--team-decision-log-artifact-base-url",
        default=os.environ.get("TIMEWEB_REQUIRED_TEAM_DECISION_LOG_ARTIFACT_BASE_URL", ""),
        help=(
            "Deprecated compatibility alias for --product-workspace-artifact-base-url."
        ),
    )
    timeweb_validate_parser.add_argument(
        "--specpm-registry-url",
        default=os.environ.get("TIMEWEB_REQUIRED_SPECPM_REGISTRY_URL", "https://specpm.dev"),
        help="Required readonly SpecPM registry URL.",
    )
    add_timeweb_hyperprompt_args(timeweb_validate_parser)
    timeweb_validate_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format.",
    )
    timeweb_validate_parser.set_defaults(func=deploy_timeweb_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PlatformError as exc:
        parser.exit(2, f"platform: error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
