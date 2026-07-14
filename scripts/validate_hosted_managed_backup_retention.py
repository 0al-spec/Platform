"""Validate the hosted managed backup-retention policy contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_POLICY = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "hosted-managed"
    / "backup-retention-policy.json"
)
EXPECTED_TIERS = {
    "vps_private": {"minimum": 3, "maximum_age_days": 7, "encrypted": False},
    "operator_offsite_encrypted": {
        "minimum": 7,
        "maximum_age_days": 30,
        "encrypted": True,
    },
    "cloud_offsite_encrypted": {
        "minimum": 7,
        "maximum_age_days": 30,
        "encrypted": True,
    },
}
EXPECTED_PROTECTED_STATES = {
    "current_production_signoff",
    "latest_verified_backup",
    "only_recovery_copy",
}
EXPECTED_AUTHORITY_BOUNDARY = {
    "may_delete_backups",
    "may_decrypt_backups",
    "may_restore_production_database",
}


class RetentionPolicyError(RuntimeError):
    """The retention policy does not satisfy the production safety contract."""


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    if policy.get("artifact_kind") != (
        "platform_hosted_managed_backup_retention_policy"
    ):
        findings.append("artifact_kind_invalid")
    if policy.get("contract_ref") != (
        "platform.hosted-managed.backup-retention.v1"
    ):
        findings.append("contract_ref_invalid")
    if policy.get("schema_version") != 1:
        findings.append("schema_version_invalid")

    selection = policy.get("selection")
    if not isinstance(selection, dict):
        findings.append("selection_missing")
    else:
        if selection.get("timestamp_source") != "backup_id_utc":
            findings.append("timestamp_source_invalid")
        if selection.get("prune_rule") != (
            "older_than_maximum_age_and_exceeds_minimum_successful_copies"
        ):
            findings.append("prune_rule_invalid")

    tiers = policy.get("tiers")
    if not isinstance(tiers, dict) or set(tiers) != set(EXPECTED_TIERS):
        findings.append("tier_set_invalid")
        tiers = {}
    for tier_id, expected in EXPECTED_TIERS.items():
        tier = tiers.get(tier_id)
        if not isinstance(tier, dict):
            findings.append(f"{tier_id}_missing")
            continue
        if tier.get("minimum_successful_copies") != expected["minimum"]:
            findings.append(f"{tier_id}_minimum_invalid")
        if tier.get("maximum_age_days") != expected["maximum_age_days"]:
            findings.append(f"{tier_id}_maximum_age_invalid")
        if tier.get("encrypted") is not expected["encrypted"]:
            findings.append(f"{tier_id}_encryption_invalid")
        if tier.get("requires_digest_verification") is not True:
            findings.append(f"{tier_id}_digest_verification_missing")
        if tier.get("requires_restore_smoke") is not True:
            findings.append(f"{tier_id}_restore_smoke_missing")

    protected_states = policy.get("protected_states")
    if (
        not isinstance(protected_states, list)
        or len(protected_states) != len(set(protected_states))
        or set(protected_states) != EXPECTED_PROTECTED_STATES
    ):
        findings.append("protected_states_invalid")

    deletion = policy.get("deletion")
    if not isinstance(deletion, dict):
        findings.append("deletion_policy_missing")
    elif (
        deletion.get("automatic") is not False
        or deletion.get("manual_confirmation_required") is not True
        or deletion.get("requires_second_failure_domain") is not True
    ):
        findings.append("deletion_policy_unsafe")

    boundary = policy.get("authority_boundary")
    if (
        not isinstance(boundary, dict)
        or set(boundary) != EXPECTED_AUTHORITY_BOUNDARY
    ):
        findings.append("authority_boundary_missing")
    else:
        for key, value in boundary.items():
            if (
                not isinstance(key, str)
                or not key.startswith("may_")
                or value is not False
            ):
                findings.append("authority_boundary_expanded")
                break

    return {
        "artifact_kind": (
            "platform_hosted_managed_backup_retention_policy_validation_report"
        ),
        "contract_ref": "platform.hosted-managed.backup-retention-validation.v1",
        "ok": not findings,
        "findings": sorted(set(findings)),
        "summary": {
            "status": (
                "retention_policy_valid"
                if not findings
                else "retention_policy_invalid"
            ),
            "tier_count": len(tiers),
            "automatic_deletion": (
                deletion.get("automatic") if isinstance(deletion, dict) else None
            ),
        },
        "authority_boundary": {
            "may_delete_backups": False,
            "may_decrypt_backups": False,
            "may_restore_production_database": False,
        },
    }


def load_and_validate(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetentionPolicyError(
            "retention policy is unavailable or invalid"
        ) from exc
    if not isinstance(policy, dict):
        raise RetentionPolicyError("retention policy must be an object")
    return validate_policy(policy)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args(argv)
    try:
        report = load_and_validate(args.policy.resolve())
    except RetentionPolicyError as exc:
        report = {
            "artifact_kind": (
                "platform_hosted_managed_backup_retention_policy_validation_report"
            ),
            "contract_ref": (
                "platform.hosted-managed.backup-retention-validation.v1"
            ),
            "ok": False,
            "findings": [str(exc)],
            "summary": {"status": "retention_policy_invalid"},
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
