#!/usr/bin/env python3
"""Small Platform operator CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_CATALOG = REPO_ROOT / "workspaces.local.yaml"
DEFAULT_EXAMPLE_CATALOG = REPO_ROOT / "workspaces.example.yaml"


class PlatformError(Exception):
    """User-facing CLI error."""


@dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    subject: str
    message: str


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
