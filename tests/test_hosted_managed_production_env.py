from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts import render_hosted_managed_production_env as renderer


def image_lock() -> dict:
    digest = "a" * 64
    return {
        "artifact_kind": "platform_hosted_managed_image_lock",
        "schema_version": 1,
        "generated_at": "2026-07-13T00:00:00+00:00",
        "source_commit": "b" * 40,
        "platforms": ["linux/amd64", "linux/arm64"],
        "images": {
            "platform": {
                "image_ref": f"ghcr.io/0al-spec/platform-hosted-managed@sha256:{digest}"
            },
            "postgresql": {"image_ref": f"postgres@sha256:{digest}"},
            "ingress": {
                "image_ref": f"ghcr.io/0al-spec/platform-hosted-managed-ingress@sha256:{digest}",
                "base_image_ref": f"caddy@sha256:{digest}",
                "upstream_file_capability_removed": True,
            },
        },
        "supply_chain": {"provenance_attestation": True, "sbom_attestation": True},
        "privacy_boundary": {"public_safe": True, "includes_secrets": False},
        "authority_boundary": {"may_deploy_production": False},
    }


class HostedManagedProductionEnvTests(unittest.TestCase):
    def test_runbook_uses_renderer_and_current_platform_image_repository(self) -> None:
        runbook = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "hosted-managed-operations.md"
        ).read_text(encoding="utf-8")
        self.assertIn("render_hosted_managed_production_env.py", runbook)
        self.assertIn("ghcr.io/0al-spec/platform-hosted-managed@sha256:", runbook)
        self.assertNotIn("ghcr.io/0al-spec/platform@sha256:<digest>", runbook)

    def test_renderer_uses_validated_lock_and_read_only_canary_scope(self) -> None:
        rendered, report = renderer.render_environment(
            image_lock=image_lock(),
            artifact_root="/srv/0al/specgraph",
            state_dir="/srv/0al/specspace-state",
            backup_root="/srv/0al/backups",
            secret_root="/srv/0al/secrets",
            ingress_bind_ip="203.0.113.10",
            ingress_port=443,
        )
        self.assertIn(
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST=review_status_execute\n", rendered
        )
        self.assertIn("PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE=postgres@sha256:", rendered)
        self.assertIn(
            "PLATFORM_MANAGED_OPERATION_TOKEN_FILE=/srv/0al/secrets/service-token",
            rendered,
        )
        self.assertNotIn("token-value", rendered)
        self.assertEqual(report["summary"]["enabled_operation_ids"], ["review_status_execute"])
        self.assertFalse(report["authority_boundary"]["may_deploy_production"])

    def test_renderer_uses_exact_promotion_dry_run_profile(self) -> None:
        rendered, report = renderer.render_environment(
            image_lock=image_lock(),
            artifact_root="/srv/0al/specgraph",
            state_dir="/srv/0al/specspace-state",
            backup_root="/srv/0al/backups",
            secret_root="/srv/0al/secrets",
            ingress_bind_ip="203.0.113.10",
            ingress_port=443,
            operation_profile="promotion-dry-run",
        )

        self.assertIn(
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST=promotion_execute_dry_run\n",
            rendered,
        )
        self.assertNotIn("review_status_execute", rendered)
        self.assertEqual(report["summary"]["operation_profile"], "promotion-dry-run")
        self.assertEqual(
            report["summary"]["enabled_operation_ids"],
            ["promotion_execute_dry_run"],
        )

    def test_renderer_rejects_overlapping_roots_and_invalid_bind_address(self) -> None:
        arguments = {
            "image_lock": image_lock(),
            "artifact_root": "/srv/0al/specgraph",
            "state_dir": "/srv/0al/specgraph/state",
            "backup_root": "/srv/0al/backups",
            "secret_root": "/srv/0al/secrets",
            "ingress_bind_ip": "managed.example.org",
            "ingress_port": 443,
        }
        with self.assertRaisesRegex(renderer.ProductionEnvRenderError, "must not overlap"):
            renderer.render_environment(**arguments)
        arguments["state_dir"] = "/srv/0al/specspace-state"
        with self.assertRaisesRegex(renderer.ProductionEnvRenderError, "bind IP is invalid"):
            renderer.render_environment(**arguments)

    def test_invalid_lock_does_not_replace_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock_path = root / "image-lock.json"
            lock_path.write_text(json.dumps({"artifact_kind": "invalid"}), encoding="utf-8")
            output = root / "production.env"
            output.write_text("existing=true\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                result = renderer.main(
                    [
                        "--image-lock",
                        str(lock_path),
                        "--output",
                        str(output),
                        "--overwrite",
                    ]
                )
            self.assertEqual(result, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "existing=true\n")

    def test_atomic_output_is_group_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "production.env"
            renderer._write_atomic(output, "KEY=value\n", overwrite=False)
            self.assertEqual(output.stat().st_mode & 0o777, 0o440)
            with self.assertRaisesRegex(renderer.ProductionEnvRenderError, "already exists"):
                renderer._write_atomic(output, "OTHER=value\n", overwrite=False)


if __name__ == "__main__":
    unittest.main()
