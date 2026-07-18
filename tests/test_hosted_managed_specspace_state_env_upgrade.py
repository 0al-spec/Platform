from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import hosted_managed_specspace_state_env_upgrade as upgrade
from scripts import render_hosted_managed_production_env as renderer


def image_lock() -> dict:
    digest = "a" * 64
    return {
        "artifact_kind": "platform_hosted_managed_image_lock",
        "schema_version": 1,
        "generated_at": "2026-07-18T00:00:00+00:00",
        "source_commit": "b" * 40,
        "platforms": ["linux/amd64", "linux/arm64"],
        "images": {
            "platform": {
                "image_ref": (
                    "ghcr.io/0al-spec/platform-hosted-managed@sha256:"
                    f"{digest}"
                )
            },
            "postgresql": {"image_ref": f"postgres@sha256:{digest}"},
            "ingress": {
                "image_ref": (
                    "ghcr.io/0al-spec/platform-hosted-managed-ingress@sha256:"
                    f"{digest}"
                ),
                "base_image_ref": f"caddy@sha256:{digest}",
                "upstream_file_capability_removed": True,
            },
        },
        "supply_chain": {
            "provenance_attestation": True,
            "sbom_attestation": True,
        },
        "privacy_boundary": {
            "public_safe": True,
            "includes_secrets": False,
        },
        "authority_boundary": {"may_deploy_production": False},
    }


class SpecSpaceStateEnvironmentUpgradeTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, str]:
        lock_path = root / "image-lock.json"
        lock_path.write_text(json.dumps(image_lock()), encoding="utf-8")
        rendered, _ = renderer.render_environment(
            image_lock=image_lock(),
            artifact_root="/srv/0al/specgraph",
            state_dir="/srv/0al/specspace-state",
            backup_root="/srv/0al/backups",
            secret_root="/srv/0al/secrets",
            ingress_bind_ip="203.0.113.10",
            ingress_port=443,
        )
        legacy = "\n".join(
            line
            for line in rendered.splitlines()
            if line.split("=", 1)[0] not in upgrade.STATE_ENV_KEYS
        ) + "\n"
        env_file = root / "production.env"
        env_file.write_text(legacy, encoding="utf-8")
        return lock_path, env_file, rendered

    def test_upgrade_adds_only_state_inventory_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path, env_file, expected = self.fixture(Path(temp_dir))
            with mock.patch.object(
                upgrade,
                "_preflight",
                return_value={"ok": True},
            ):
                first = upgrade.upgrade_environment(
                    image_lock_path=lock_path,
                    env_file=env_file,
                    service_url="https://managed.example.test",
                    confirm=True,
                )
                second = upgrade.upgrade_environment(
                    image_lock_path=lock_path,
                    env_file=env_file,
                    service_url="https://managed.example.test",
                    confirm=True,
                )
            final_content = env_file.read_text(encoding="utf-8")

        self.assertEqual(first["summary"]["action"], "upgraded")
        self.assertEqual(first["summary"]["added_key_count"], 3)
        self.assertEqual(second["summary"]["action"], "unchanged")
        self.assertEqual(final_content, expected)
        self.assertNotIn(temp_dir, str(first))

    def test_upgrade_requires_confirmation_and_rejects_other_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path, env_file, _ = self.fixture(Path(temp_dir))
            with self.assertRaisesRegex(
                upgrade.StateEnvironmentUpgradeError,
                "explicit confirmation",
            ):
                upgrade.upgrade_environment(
                    image_lock_path=lock_path,
                    env_file=env_file,
                    service_url="https://managed.example.test",
                    confirm=False,
                )
            with env_file.open("a", encoding="utf-8") as handle:
                handle.write("UNRELATED=value\n")
            with self.assertRaisesRegex(
                upgrade.StateEnvironmentUpgradeError,
                "inventory drift",
            ):
                upgrade.upgrade_environment(
                    image_lock_path=lock_path,
                    env_file=env_file,
                    service_url="https://managed.example.test",
                    confirm=True,
                )


if __name__ == "__main__":
    unittest.main()
