#!/usr/bin/env python3
"""Small Platform operator CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
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
            "Timeweb Cloud Apps remains SpecSpace-owned until Platform has a manifest-only profile.",
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
