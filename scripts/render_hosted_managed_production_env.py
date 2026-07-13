"""Render a non-secret hosted managed production environment from an image lock."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

try:
    from scripts.validate_hosted_managed_image_lock import validate_image_lock
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    from validate_hosted_managed_image_lock import validate_image_lock


SAFE_ABSOLUTE_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")
READ_ONLY_CANARY_OPERATION = "review_status_execute"
SECRET_FILENAMES = {
    "PLATFORM_MANAGED_OPERATION_TOKEN_FILE": "service-token",
    "PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE": "database-password",
    "PLATFORM_MANAGED_OPERATION_DATABASE_URL_FILE": "database-url",
    "PLATFORM_MANAGED_OPERATION_GITHUB_TOKEN_FILE": "github-token",
    "PLATFORM_MANAGED_OPERATION_TLS_CERTIFICATE_FILE": "tls-certificate.pem",
    "PLATFORM_MANAGED_OPERATION_TLS_PRIVATE_KEY_FILE": "tls-private-key.pem",
}


class ProductionEnvRenderError(RuntimeError):
    """The requested production environment is unsafe or incomplete."""


def _load_image_lock(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionEnvRenderError("image lock is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise ProductionEnvRenderError("image lock must be an object")
    diagnostics = validate_image_lock(payload)
    if diagnostics:
        raise ProductionEnvRenderError(
            "image lock failed validation: " + ", ".join(diagnostics)
        )
    return payload


def _safe_root(value: str, *, label: str) -> Path:
    if not SAFE_ABSOLUTE_PATH.fullmatch(value) or "//" in value:
        raise ProductionEnvRenderError(f"{label} must be a normalized absolute path")
    path = Path(value)
    if path == Path("/") or any(part in {".", ".."} for part in path.parts):
        raise ProductionEnvRenderError(f"{label} must be a bounded absolute path")
    return path


def _roots_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def render_environment(
    *,
    image_lock: dict[str, Any],
    artifact_root: str,
    state_dir: str,
    backup_root: str,
    secret_root: str,
    ingress_bind_ip: str,
    ingress_port: int,
) -> tuple[str, dict[str, Any]]:
    roots = {
        "artifact_root": _safe_root(artifact_root, label="artifact root"),
        "state_dir": _safe_root(state_dir, label="state directory"),
        "backup_root": _safe_root(backup_root, label="backup root"),
        "secret_root": _safe_root(secret_root, label="secret root"),
    }
    labels = list(roots)
    for index, label in enumerate(labels):
        for other_label in labels[index + 1 :]:
            if _roots_overlap(roots[label], roots[other_label]):
                raise ProductionEnvRenderError(
                    f"{label} and {other_label} must not overlap"
                )
    try:
        parsed_ip = ipaddress.ip_address(ingress_bind_ip)
    except ValueError as exc:
        raise ProductionEnvRenderError("ingress bind IP is invalid") from exc
    if parsed_ip.version != 4:
        raise ProductionEnvRenderError("ingress bind IP must be IPv4")
    if not 1 <= ingress_port <= 65535:
        raise ProductionEnvRenderError("ingress port is outside the valid range")

    images = image_lock["images"]
    values = {
        "PLATFORM_MANAGED_OPERATION_IMAGE": images["platform"]["image_ref"],
        "PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE": images["postgresql"][
            "image_ref"
        ],
        "PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE": images["ingress"]["image_ref"],
        "PLATFORM_MANAGED_OPERATION_ALLOWLIST": READ_ONLY_CANARY_OPERATION,
        "PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT": str(roots["artifact_root"]),
        "PLATFORM_MANAGED_OPERATION_STATE_DIR": str(roots["state_dir"]),
        "PLATFORM_MANAGED_OPERATION_BACKUP_ROOT": str(roots["backup_root"]),
        "PLATFORM_MANAGED_OPERATION_INGRESS_BIND_IP": str(parsed_ip),
        "PLATFORM_MANAGED_OPERATION_INGRESS_PORT": str(ingress_port),
    }
    values.update(
        {
            key: str(roots["secret_root"] / filename)
            for key, filename in SECRET_FILENAMES.items()
        }
    )
    rendered = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    report = {
        "artifact_kind": "platform_hosted_managed_production_env_render_report",
        "contract_ref": "platform.hosted-managed.production-env.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "summary": {
            "status": "production_env_rendered",
            "source_commit": image_lock["source_commit"],
            "image_count": 3,
            "enabled_operation_ids": [READ_ONLY_CANARY_OPERATION],
            "secret_ref_count": len(SECRET_FILENAMES),
            "environment_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        },
        "privacy_boundary": {
            "public_safe": True,
            "includes_secret_values": False,
            "includes_secret_paths": False,
            "includes_local_paths": False,
        },
        "authority_boundary": {
            "may_deploy_production": False,
            "may_create_secrets": False,
            "may_execute_platform": False,
            "may_enqueue_operations": False,
        },
    }
    return rendered, report


def _write_atomic(path: Path, content: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ProductionEnvRenderError("output already exists; use --overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o440)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-lock", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--artifact-root", default="/srv/0al/specgraph")
    parser.add_argument("--state-dir", default="/srv/0al/specspace-state")
    parser.add_argument("--backup-root", default="/srv/0al/backups")
    parser.add_argument("--secret-root", default="/srv/0al/secrets")
    parser.add_argument("--ingress-bind-ip", default="0.0.0.0")
    parser.add_argument("--ingress-port", type=int, default=443)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        image_lock = _load_image_lock(Path(args.image_lock))
        rendered, report = render_environment(
            image_lock=image_lock,
            artifact_root=args.artifact_root,
            state_dir=args.state_dir,
            backup_root=args.backup_root,
            secret_root=args.secret_root,
            ingress_bind_ip=args.ingress_bind_ip,
            ingress_port=args.ingress_port,
        )
        _write_atomic(Path(args.output), rendered, overwrite=args.overwrite)
    except ProductionEnvRenderError as exc:
        report = {
            "artifact_kind": "platform_hosted_managed_production_env_render_report",
            "ok": False,
            "summary": {"status": "blocked"},
            "diagnostics": [str(exc)],
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
