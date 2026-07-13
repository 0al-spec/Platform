from __future__ import annotations

from pathlib import Path
import unittest

import yaml

from scripts import validate_hosted_managed_image_lock as validator


REPO_ROOT = Path(__file__).resolve().parents[1]


def image_lock() -> dict:
    digest = "a" * 64
    return {
        "artifact_kind": "platform_hosted_managed_image_lock",
        "schema_version": 1,
        "generated_at": "2026-07-13T00:00:00Z",
        "source_commit": "b" * 40,
        "platforms": ["linux/amd64", "linux/arm64"],
        "images": {
            "platform": {
                "image_ref": (
                    "ghcr.io/0al-spec/platform-hosted-managed@sha256:" + digest
                )
            },
            "ingress": {
                "image_ref": (
                    "ghcr.io/0al-spec/platform-hosted-managed-ingress@sha256:" + digest
                ),
                "base_image_ref": "caddy@sha256:" + digest,
                "upstream_file_capability_removed": True,
            },
        },
        "supply_chain": {
            "provenance_attestation": True,
            "sbom_attestation": True,
        },
        "privacy_boundary": {"public_safe": True, "includes_secrets": False},
        "authority_boundary": {
            "may_deploy_production": False,
            "may_expand_operation_allowlist": False,
            "may_execute_managed_operations": False,
        },
    }


class HostedManagedImageLockTests(unittest.TestCase):
    def test_valid_lock_pins_both_multi_arch_images(self) -> None:
        self.assertEqual(validator.validate_image_lock(image_lock()), [])

    def test_lock_rejects_mutable_image_and_authority_expansion(self) -> None:
        payload = image_lock()
        payload["images"]["platform"]["image_ref"] = (
            "ghcr.io/0al-spec/platform-hosted-managed:latest"
        )
        payload["authority_boundary"]["may_deploy_production"] = True
        diagnostics = validator.validate_image_lock(payload)
        self.assertIn("platform_image_ref_invalid", diagnostics)
        self.assertIn("authority_boundary_expanded", diagnostics)

    def test_publish_workflow_is_manual_multi_arch_and_attested(self) -> None:
        workflow_path = (
            REPO_ROOT / ".github" / "workflows" / "publish-hosted-managed-images.yml"
        )
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        self.assertEqual(workflow[True], {"workflow_dispatch": None})
        self.assertEqual(workflow["permissions"]["packages"], "write")
        self.assertEqual(workflow["jobs"]["publish"]["if"], "github.ref == 'refs/heads/main'")
        text = workflow_path.read_text(encoding="utf-8")
        self.assertEqual(text.count("platforms: linux/amd64,linux/arm64"), 2)
        self.assertEqual(text.count("provenance: mode=max"), 2)
        self.assertEqual(text.count("sbom: true"), 2)
        self.assertIn("CADDY_BASE_IMAGE=${{ steps.caddy.outputs.ref }}", text)


if __name__ == "__main__":
    unittest.main()
