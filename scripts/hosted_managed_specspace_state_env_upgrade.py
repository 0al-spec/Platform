"""Prepare the one-time production environment inventory for SpecSpace state."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

try:
    from scripts.hosted_managed_production_deploy import (
        ProductionDeployError,
        _load_image_lock,
        _parse_environment,
        _preflight,
        _required,
    )
    from scripts.hosted_managed_production_profiles import (
        REVIEW_STATUS_PROFILE_ID,
    )
    from scripts.render_hosted_managed_production_env import (
        _write_atomic,
        render_environment,
    )
except ModuleNotFoundError:
    from hosted_managed_production_deploy import (
        ProductionDeployError,
        _load_image_lock,
        _parse_environment,
        _preflight,
        _required,
    )
    from hosted_managed_production_profiles import REVIEW_STATUS_PROFILE_ID
    from render_hosted_managed_production_env import (
        _write_atomic,
        render_environment,
    )


STATE_ENV_KEYS = {
    "PLATFORM_SPECSPACE_STATE_TOKEN_FILE",
    "PLATFORM_SPECSPACE_STATE_DB_PASSWORD_FILE",
    "PLATFORM_SPECSPACE_STATE_DATABASE_URL_FILE",
}
RELEASE_IMAGE_KEYS = {
    "PLATFORM_MANAGED_OPERATION_IMAGE",
    "PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE",
}


class StateEnvironmentUpgradeError(RuntimeError):
    """The environment cannot be extended without configuration drift."""


def upgrade_environment(
    *,
    image_lock_path: Path,
    env_file: Path,
    service_url: str,
    confirm: bool,
) -> dict[str, Any]:
    if not confirm:
        raise StateEnvironmentUpgradeError(
            "SpecSpace state environment upgrade requires explicit confirmation"
        )
    if not image_lock_path.is_absolute() or not env_file.is_absolute():
        raise StateEnvironmentUpgradeError("upgrade paths must be absolute")
    try:
        current_content = env_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateEnvironmentUpgradeError(
            "current production environment is unavailable"
        ) from exc
    try:
        current = _parse_environment(current_content)
        image_lock = _load_image_lock(image_lock_path)
        rendered, render_report = render_environment(
            image_lock=image_lock,
            artifact_root=_required(
                current, "PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT"
            ),
            state_dir=_required(
                current, "PLATFORM_MANAGED_OPERATION_STATE_DIR"
            ),
            backup_root=_required(
                current, "PLATFORM_MANAGED_OPERATION_BACKUP_ROOT"
            ),
            secret_root=str(
                Path(
                    _required(
                        current,
                        "PLATFORM_MANAGED_OPERATION_TOKEN_FILE",
                    )
                ).parent
            ),
            ingress_bind_ip=_required(
                current,
                "PLATFORM_MANAGED_OPERATION_INGRESS_BIND_IP",
            ),
            ingress_port=int(
                _required(
                    current,
                    "PLATFORM_MANAGED_OPERATION_INGRESS_PORT",
                )
            ),
        )
        candidate = _parse_environment(rendered)
    except (ProductionDeployError, ValueError) as exc:
        raise StateEnvironmentUpgradeError(str(exc)) from exc

    if set(current) == set(candidate):
        if current != candidate:
            raise StateEnvironmentUpgradeError(
                "environment already has state keys but differs from the image lock"
            )
        action = "unchanged"
    else:
        if set(candidate) - set(current) != STATE_ENV_KEYS or set(current) - set(
            candidate
        ):
            raise StateEnvironmentUpgradeError(
                "environment inventory drift is not the bounded state upgrade"
            )
        drift = {
            key
            for key in current
            if current[key] != candidate.get(key)
        }
        if not drift <= RELEASE_IMAGE_KEYS:
            raise StateEnvironmentUpgradeError(
                "non-image environment drift blocks the state upgrade"
            )
        action = "upgraded"

    preflight = _preflight(
        values=candidate,
        service_url=service_url,
        operation_profile=REVIEW_STATUS_PROFILE_ID,
    )
    if action == "upgraded":
        _write_atomic(env_file, rendered, overwrite=True)

    return {
        "artifact_kind": (
            "platform_hosted_managed_specspace_state_env_upgrade_report"
        ),
        "contract_ref": "platform.hosted-managed.specspace-state-env.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "summary": {
            "status": (
                "specspace_state_environment_ready"
                if action == "unchanged"
                else "specspace_state_environment_upgraded"
            ),
            "action": action,
            "source_commit": image_lock["source_commit"],
            "added_key_count": 0 if action == "unchanged" else len(STATE_ENV_KEYS),
            "preflight_ready": preflight.get("ok") is True,
            "environment_sha256": render_report["summary"][
                "environment_sha256"
            ],
        },
        "privacy_boundary": {
            "public_safe": True,
            "includes_secret_values": False,
            "includes_secret_paths": False,
            "includes_local_paths": False,
        },
        "authority_boundary": {
            "may_deploy_production": False,
            "may_start_workers": False,
            "may_enqueue_operations": False,
            "may_mutate_specs": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-lock", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument(
        "--service-url",
        default="https://managed.specgraph.tech",
    )
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        report = upgrade_environment(
            image_lock_path=Path(args.image_lock),
            env_file=Path(args.env_file),
            service_url=args.service_url,
            confirm=args.confirm,
        )
        exit_code = 0
    except (OSError, StateEnvironmentUpgradeError) as exc:
        report = {
            "artifact_kind": (
                "platform_hosted_managed_specspace_state_env_upgrade_report"
            ),
            "ok": False,
            "summary": {"status": "blocked"},
            "diagnostics": [str(exc)],
        }
        exit_code = 1
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
