"""Fail-closed host preflight for production hosted managed operations."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from typing import Any
from urllib.parse import urlsplit


READ_ONLY_CANARY_OPERATION = "review_status_execute"
DRY_RUN_OPERATION = "promotion_execute_dry_run"
SECRET_SPECS = {
    "service_token": (32, None),
    "database_password": (24, None),
    "database_url": (32, "postgresql"),
    "github_token": (20, None),
    "tls_certificate": (64, "certificate"),
    "tls_private_key": (64, "private_key"),
}


class ProductionPreflightError(RuntimeError):
    """Production inputs do not satisfy the deployment contract."""


def _digest_pinned_image(value: str) -> bool:
    prefix, marker, digest = value.partition("@sha256:")
    return bool(prefix and marker and len(digest) == 64) and all(
        character in "0123456789abcdef" for character in digest.lower()
    )


def _secret_diagnostic(
    *,
    label: str,
    path: Path,
    minimum_length: int,
    content_kind: str | None,
    expected_uid: int,
    expected_gid: int,
) -> tuple[list[str], bytes | None]:
    diagnostics: list[str] = []
    if not path.is_absolute():
        return [f"{label}_path_not_absolute"], None
    if path.is_symlink():
        return [f"{label}_path_is_symlink"], None
    try:
        metadata = path.stat()
    except OSError:
        return [f"{label}_file_missing"], None
    if not stat.S_ISREG(metadata.st_mode):
        diagnostics.append(f"{label}_not_regular_file")
    if stat.S_IMODE(metadata.st_mode) != 0o440:
        diagnostics.append(f"{label}_mode_not_0440")
    if metadata.st_uid != expected_uid:
        diagnostics.append(f"{label}_owner_uid_mismatch")
    if metadata.st_gid != expected_gid:
        diagnostics.append(f"{label}_owner_gid_mismatch")
    try:
        content = path.read_bytes().strip()
    except OSError:
        diagnostics.append(f"{label}_unreadable")
        return diagnostics, None
    if len(content) < minimum_length:
        diagnostics.append(f"{label}_too_short")
    if b"\x00" in content or b"\r" in content:
        diagnostics.append(f"{label}_invalid_bytes")
    if content_kind == "postgresql" and not content.startswith(
        (b"postgresql://", b"postgres://")
    ):
        diagnostics.append("database_url_scheme_invalid")
    if content_kind == "certificate" and b"BEGIN CERTIFICATE" not in content:
        diagnostics.append("tls_certificate_pem_invalid")
    if content_kind == "private_key" and b"PRIVATE KEY" not in content:
        diagnostics.append("tls_private_key_pem_invalid")
    return diagnostics, content


def _directory_diagnostics(
    *,
    label: str,
    path: Path,
    expected_uid: int,
    expected_gid: int,
    require_owner_write: bool,
) -> list[str]:
    if not path.is_absolute():
        return [f"{label}_path_not_absolute"]
    if path.is_symlink():
        return [f"{label}_path_is_symlink"]
    try:
        metadata = path.stat()
    except OSError:
        return [f"{label}_missing"]
    diagnostics: list[str] = []
    if not stat.S_ISDIR(metadata.st_mode):
        diagnostics.append(f"{label}_not_directory")
    if metadata.st_uid != expected_uid:
        diagnostics.append(f"{label}_owner_uid_mismatch")
    if metadata.st_gid != expected_gid:
        diagnostics.append(f"{label}_owner_gid_mismatch")
    if require_owner_write and not metadata.st_mode & stat.S_IWUSR:
        diagnostics.append(f"{label}_owner_write_missing")
    return diagnostics


def run_preflight(
    *,
    service_url: str,
    allowlist: str,
    image_refs: dict[str, str],
    secret_paths: dict[str, Path],
    artifact_root: Path,
    state_dir: Path,
    expected_secret_uid: int = 0,
    runtime_uid: int = 1000,
    runtime_gid: int = 1000,
    allow_dry_run: bool = False,
) -> dict[str, Any]:
    diagnostics: list[str] = []
    parsed = urlsplit(service_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        diagnostics.append("service_url_not_private_https_endpoint")

    enabled = [item.strip() for item in allowlist.split(",") if item.strip()]
    expected = [READ_ONLY_CANARY_OPERATION]
    if allow_dry_run:
        expected.append(DRY_RUN_OPERATION)
    if enabled != expected:
        diagnostics.append("deployment_allowlist_not_exact_canary_scope")

    for label in ("platform", "postgresql", "ingress"):
        if not _digest_pinned_image(image_refs.get(label, "")):
            diagnostics.append(f"{label}_image_not_digest_pinned")

    if set(secret_paths) != set(SECRET_SPECS):
        diagnostics.append("secret_set_incomplete")
    secret_contents: dict[str, bytes] = {}
    for label, (minimum_length, content_kind) in SECRET_SPECS.items():
        path = secret_paths.get(label)
        if path is None:
            continue
        findings, content = _secret_diagnostic(
            label=label,
            path=path,
            minimum_length=minimum_length,
            content_kind=content_kind,
            expected_uid=expected_secret_uid,
            expected_gid=runtime_gid,
        )
        diagnostics.extend(findings)
        if content is not None:
            secret_contents[label] = content
    if len(secret_contents) != len(set(secret_contents.values())):
        diagnostics.append("secret_values_not_distinct")

    diagnostics.extend(
        _directory_diagnostics(
            label="artifact_root",
            path=artifact_root,
            expected_uid=runtime_uid,
            expected_gid=runtime_gid,
            require_owner_write=True,
        )
    )
    diagnostics.extend(
        _directory_diagnostics(
            label="state_dir",
            path=state_dir,
            expected_uid=runtime_uid,
            expected_gid=runtime_gid,
            require_owner_write=False,
        )
    )

    diagnostics = sorted(set(diagnostics))
    return {
        "artifact_kind": "platform_hosted_managed_production_preflight_report",
        "contract_ref": "platform.hosted-managed.production-preflight.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": not diagnostics,
        "summary": {
            "status": "ready" if not diagnostics else "blocked",
            "service_transport": "https" if parsed.scheme == "https" else "invalid",
            "enabled_operations": enabled,
            "dry_run_enabled": DRY_RUN_OPERATION in enabled,
            "image_count": len(image_refs),
            "secret_file_count": len(secret_paths),
            "artifact_root_ready": not any(
                item.startswith("artifact_root_") for item in diagnostics
            ),
            "state_dir_ready": not any(
                item.startswith("state_dir_") for item in diagnostics
            ),
        },
        "diagnostics": diagnostics,
        "privacy_boundary": {
            "public_safe": True,
            "includes_secret_values": False,
            "includes_secret_paths": False,
            "includes_local_paths": False,
        },
        "authority_boundary": {
            "may_execute_platform": False,
            "may_enqueue_operations": False,
            "may_mutate_specs": False,
            "may_write_ontology": False,
            "may_create_git_review": False,
        },
    }


def _env_path(name: str) -> Path:
    value = os.environ.get(name, "")
    if not value:
        raise ProductionPreflightError(f"{name} is required")
    return Path(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-url", required=True)
    parser.add_argument("--allow-dry-run", action="store_true")
    parser.add_argument("--expected-secret-uid", type=int, default=0)
    parser.add_argument("--runtime-uid", type=int, default=1000)
    parser.add_argument("--runtime-gid", type=int, default=1000)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        report = run_preflight(
            service_url=args.service_url,
            allowlist=os.environ.get("PLATFORM_MANAGED_OPERATION_ALLOWLIST", ""),
            image_refs={
                "platform": os.environ.get("PLATFORM_MANAGED_OPERATION_IMAGE", ""),
                "postgresql": os.environ.get(
                    "PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE", ""
                ),
                "ingress": os.environ.get(
                    "PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE", ""
                ),
            },
            secret_paths={
                "service_token": _env_path("PLATFORM_MANAGED_OPERATION_TOKEN_FILE"),
                "database_password": _env_path(
                    "PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE"
                ),
                "database_url": _env_path(
                    "PLATFORM_MANAGED_OPERATION_DATABASE_URL_FILE"
                ),
                "github_token": _env_path(
                    "PLATFORM_MANAGED_OPERATION_GITHUB_TOKEN_FILE"
                ),
                "tls_certificate": _env_path(
                    "PLATFORM_MANAGED_OPERATION_TLS_CERTIFICATE_FILE"
                ),
                "tls_private_key": _env_path(
                    "PLATFORM_MANAGED_OPERATION_TLS_PRIVATE_KEY_FILE"
                ),
            },
            artifact_root=_env_path("PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT"),
            state_dir=_env_path("PLATFORM_MANAGED_OPERATION_STATE_DIR"),
            expected_secret_uid=args.expected_secret_uid,
            runtime_uid=args.runtime_uid,
            runtime_gid=args.runtime_gid,
            allow_dry_run=args.allow_dry_run,
        )
    except ProductionPreflightError as exc:
        report = {
            "artifact_kind": "platform_hosted_managed_production_preflight_report",
            "ok": False,
            "summary": {"status": "blocked"},
            "diagnostics": [str(exc)],
        }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
