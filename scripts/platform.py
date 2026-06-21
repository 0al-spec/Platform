#!/usr/bin/env python3
"""Small Platform operator CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
DEFAULT_LOCAL_ENV = REPO_ROOT / ".env"
SPECGRAPH_SUPERVISOR_REL = Path("tools") / "supervisor.py"
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
INIT_TIMEOUT_SECONDS = 120
DEFAULT_TIMEWEB_HYPERPROMPT_WORK_DIR = "/tmp"
DEFAULT_TIMEWEB_HYPERPROMPT_COMPILE_TIMEOUT_SECONDS = "60"
DEFAULT_TIMEWEB_HYPERPROMPT_MAX_INPUT_BYTES = "1048576"
DEFAULT_TIMEWEB_HYPERPROMPT_MAX_OUTPUT_BYTES = "2097152"
DEFAULT_TIMEWEB_HYPERPROMPT_BUNDLE_RETENTION_COUNT = "20"
DIGEST_IMAGE_RE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*(?::[a-z0-9._-]+)?@sha256:[0-9a-f]{64}$"
)


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
    specpm_registry_url: str,
    release_commit: str,
    hyperprompt_runtime: TimewebHyperpromptRuntime,
) -> str:
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
    compose_file = output_dir / "docker-compose.yml"
    readme = output_dir / "README.md"
    manifest = output_dir / "platform-timeweb-deploy.json"

    compose_file.write_text(
        render_timeweb_compose(
            api_image_ref=image_refs.specspace_api_image_ref,
            ui_image_ref=image_refs.specspace_ui_image_ref,
            artifact_base_url=args.artifact_base_url,
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
