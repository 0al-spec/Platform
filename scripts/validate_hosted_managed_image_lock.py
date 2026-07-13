"""Validate digest-pinned hosted managed runtime image locks."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any


EXPECTED_PLATFORMS = ["linux/amd64", "linux/arm64"]
EXPECTED_IMAGES = {
    "platform": "ghcr.io/0al-spec/platform-hosted-managed",
    "ingress": "ghcr.io/0al-spec/platform-hosted-managed-ingress",
}
DIGEST_REF = re.compile(r"^(?P<name>[^@]+)@sha256:(?P<digest>[0-9a-f]{64})$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class HostedImageLockError(RuntimeError):
    """Image lock does not satisfy the production supply-chain contract."""


def _timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _authority_findings(value: Any, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            if isinstance(key, str) and key.startswith("may_") and nested is not False:
                findings.append(nested_path)
            findings.extend(_authority_findings(nested, path=nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            findings.extend(_authority_findings(nested, path=f"{path}[{index}]"))
    return findings


def validate_image_lock(payload: dict[str, Any]) -> list[str]:
    diagnostics: list[str] = []
    if payload.get("artifact_kind") != "platform_hosted_managed_image_lock":
        diagnostics.append("artifact_kind_invalid")
    if payload.get("schema_version") != 1:
        diagnostics.append("schema_version_invalid")
    if not _timestamp(payload.get("generated_at")):
        diagnostics.append("generated_at_invalid")
    if not isinstance(payload.get("source_commit"), str) or not COMMIT.fullmatch(
        str(payload.get("source_commit"))
    ):
        diagnostics.append("source_commit_invalid")
    if payload.get("platforms") != EXPECTED_PLATFORMS:
        diagnostics.append("platforms_invalid")

    images = payload.get("images")
    if not isinstance(images, dict) or set(images) != set(EXPECTED_IMAGES):
        diagnostics.append("image_set_invalid")
        images = {}
    for label, expected_name in EXPECTED_IMAGES.items():
        image = images.get(label)
        if not isinstance(image, dict):
            diagnostics.append(f"{label}_image_invalid")
            continue
        match = DIGEST_REF.fullmatch(str(image.get("image_ref") or ""))
        if match is None or match.group("name") != expected_name:
            diagnostics.append(f"{label}_image_ref_invalid")
    ingress = images.get("ingress")
    ingress = ingress if isinstance(ingress, dict) else {}
    caddy_match = DIGEST_REF.fullmatch(str(ingress.get("base_image_ref") or ""))
    if caddy_match is None or caddy_match.group("name") not in {"caddy", "docker.io/library/caddy"}:
        diagnostics.append("ingress_base_image_ref_invalid")
    if ingress.get("upstream_file_capability_removed") is not True:
        diagnostics.append("ingress_file_capability_contract_missing")

    supply_chain = payload.get("supply_chain")
    supply_chain = supply_chain if isinstance(supply_chain, dict) else {}
    if supply_chain.get("provenance_attestation") is not True:
        diagnostics.append("provenance_attestation_missing")
    if supply_chain.get("sbom_attestation") is not True:
        diagnostics.append("sbom_attestation_missing")
    privacy = payload.get("privacy_boundary")
    privacy = privacy if isinstance(privacy, dict) else {}
    if privacy.get("public_safe") is not True or privacy.get("includes_secrets") is not False:
        diagnostics.append("privacy_boundary_invalid")
    if _authority_findings(payload):
        diagnostics.append("authority_boundary_expanded")
    return sorted(set(diagnostics))


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    if len(arguments) != 1:
        print("usage: validate_hosted_managed_image_lock.py <image-lock.json>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"ok": False, "diagnostics": ["image_lock_unreadable"]}))
        return 1
    if not isinstance(payload, dict):
        diagnostics = ["image_lock_not_object"]
    else:
        diagnostics = validate_image_lock(payload)
    print(json.dumps({"ok": not diagnostics, "diagnostics": diagnostics}, sort_keys=True))
    return 0 if not diagnostics else 1


if __name__ == "__main__":
    raise SystemExit(main())
