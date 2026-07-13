from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import hosted_managed_production_deploy as deployment
from scripts import render_hosted_managed_production_env as renderer


def image_lock(
    *, source_commit: str = "b" * 40, postgres_digest: str = "a" * 64
) -> dict:
    digest = "a" * 64
    return {
        "artifact_kind": "platform_hosted_managed_image_lock",
        "schema_version": 1,
        "generated_at": "2026-07-14T00:00:00+00:00",
        "source_commit": source_commit,
        "platforms": ["linux/amd64", "linux/arm64"],
        "images": {
            "platform": {
                "image_ref": f"ghcr.io/0al-spec/platform-hosted-managed@sha256:{digest}"
            },
            "postgresql": {"image_ref": f"postgres@sha256:{postgres_digest}"},
            "ingress": {
                "image_ref": f"ghcr.io/0al-spec/platform-hosted-managed-ingress@sha256:{digest}",
                "base_image_ref": f"caddy@sha256:{digest}",
                "upstream_file_capability_removed": True,
            },
        },
        "supply_chain": {
            "provenance_attestation": True,
            "sbom_attestation": True,
        },
        "privacy_boundary": {"public_safe": True, "includes_secrets": False},
        "authority_boundary": {"may_deploy_production": False},
    }


class HostedManagedProductionDeployTests(unittest.TestCase):
    def fixture(self, root: Path) -> dict:
        lock = image_lock()
        lock_path = root / "image-lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        env_file = root / "production.env"
        rendered, _ = renderer.render_environment(
            image_lock=lock,
            artifact_root="/srv/0al/specgraph",
            state_dir="/srv/0al/specspace-state",
            backup_root="/srv/0al/backups",
            secret_root="/srv/0al/secrets",
            ingress_bind_ip="0.0.0.0",
            ingress_port=443,
        )
        env_file.write_text(rendered, encoding="utf-8")
        compose_file = root / "compose.yml"
        compose_file.write_text("services: {}\n", encoding="utf-8")
        commands: list[list[str]] = []

        def runner(command, **kwargs):
            commands.append(command)
            if command[0].endswith("checkout-helper"):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        "repository=platform\n"
                        f"commit={lock['source_commit']}\n"
                        "worktree=clean\n"
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        return {
            "image_lock_path": lock_path,
            "env_file": env_file,
            "compose_file": compose_file,
            "service_url": "https://managed.example.test",
            "project_name": "platform-managed-production",
            "checkout_helper": Path("/usr/local/sbin/checkout-helper"),
            "runner": runner,
            "health_attempts": 1,
            "health_interval_seconds": 0,
            "sleeper": lambda _: None,
            "commands": commands,
            "rendered": rendered,
        }

    def successful_probe(self) -> dict:
        return {
            "ok": True,
            "summary": {"status": "healthy", "healthy_service_count": 4},
        }

    def queue_report(self) -> dict:
        return {
            "ok": True,
            "summary": {"status": "drained", "rollback_ready": True},
        }

    def test_update_validates_drains_pulls_recreates_and_probes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            commands = fixture.pop("commands")
            rendered = fixture.pop("rendered")
            with (
                mock.patch.object(deployment, "_preflight", return_value={"ok": True}),
                mock.patch.object(
                    deployment, "_queue_audit", return_value=self.queue_report()
                ),
                mock.patch.object(
                    deployment,
                    "_probe_until_healthy",
                    return_value=(self.successful_probe(), 2),
                ),
            ):
                report = deployment.deploy(**fixture)

            self.assertTrue(report["ok"])
            self.assertEqual(report["summary"]["source_commit"], "b" * 40)
            self.assertEqual(report["summary"]["healthy_service_count"], 4)
            self.assertEqual(fixture["env_file"].read_text(encoding="utf-8"), rendered)
            compose_commands = [
                command for command in commands if command[0] == "docker"
            ]
            self.assertTrue(
                any(
                    command[-2:] == ["config", "--quiet"]
                    for command in compose_commands
                )
            )
            self.assertTrue(any(command[-1] == "pull" for command in compose_commands))
            self.assertTrue(any("stop" in command for command in compose_commands))
            self.assertTrue(any("up" in command for command in compose_commands))
            self.assertFalse(list(Path(temp_dir).glob(".production.env.candidate.*")))
            self.assertNotIn("/srv/0al", str(report))
            self.assertFalse(report["authority_boundary"]["may_enqueue_operations"])

    def test_checkout_lock_mismatch_blocks_before_compose(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            fixture.pop("rendered")
            commands = fixture.pop("commands")

            def mismatched_runner(command, **kwargs):
                commands.append(command)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=f"repository=platform\ncommit={'c' * 40}\nworktree=clean\n",
                    stderr="",
                )

            fixture["runner"] = mismatched_runner
            with self.assertRaisesRegex(
                deployment.ProductionDeployError, "does not match"
            ):
                deployment.deploy(**fixture)
            self.assertFalse(any(command[0] == "docker" for command in commands))

    def test_postgresql_image_change_requires_separate_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            fixture.pop("commands")
            fixture.pop("rendered")
            changed = image_lock(postgres_digest="c" * 64)
            fixture["image_lock_path"].write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(
                deployment.ProductionDeployError, "database migration"
            ):
                deployment.deploy(**fixture)

    def test_failed_recreation_restores_previous_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            fixture.pop("commands")
            fixture.pop("rendered")
            previous = fixture["env_file"].read_text(encoding="utf-8")
            up_count = 0

            def runner(command, **kwargs):
                nonlocal up_count
                if command[0].endswith("checkout-helper"):
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=f"repository=platform\ncommit={'b' * 40}\nworktree=clean\n",
                        stderr="",
                    )
                if "up" in command:
                    up_count += 1
                    return subprocess.CompletedProcess(
                        command, 1 if up_count == 1 else 0, stdout="", stderr=""
                    )
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            fixture["runner"] = runner
            with (
                mock.patch.object(deployment, "_preflight", return_value={"ok": True}),
                mock.patch.object(
                    deployment, "_queue_audit", return_value=self.queue_report()
                ),
                mock.patch.object(
                    deployment,
                    "_probe_until_healthy",
                    return_value=(self.successful_probe(), 1),
                ),
                self.assertRaisesRegex(
                    deployment.ProductionDeployError, "previous runtime was restored"
                ),
            ):
                deployment.deploy(**fixture)
            self.assertEqual(up_count, 2)
            self.assertEqual(fixture["env_file"].read_text(encoding="utf-8"), previous)

    def test_pull_failure_is_blocked_without_rollback_or_environment_change(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            fixture.pop("commands")
            fixture.pop("rendered")
            previous = fixture["env_file"].read_text(encoding="utf-8")
            up_count = 0

            def runner(command, **kwargs):
                nonlocal up_count
                if command[0].endswith("checkout-helper"):
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=f"repository=platform\ncommit={'b' * 40}\nworktree=clean\n",
                        stderr="",
                    )
                if "up" in command:
                    up_count += 1
                return subprocess.CompletedProcess(
                    command, 1 if command[-1] == "pull" else 0, stdout="", stderr=""
                )

            fixture["runner"] = runner
            with (
                mock.patch.object(deployment, "_preflight", return_value={"ok": True}),
                mock.patch.object(
                    deployment, "_queue_audit", return_value=self.queue_report()
                ),
                self.assertRaisesRegex(
                    deployment.ProductionDeployError, "before runtime mutation"
                ) as raised,
            ):
                deployment.deploy(**fixture)
            self.assertEqual(raised.exception.status, "blocked")
            self.assertEqual(up_count, 0)
            self.assertEqual(fixture["env_file"].read_text(encoding="utf-8"), previous)

    def test_quiesced_enqueue_race_must_drain_before_worker_stops(self) -> None:
        active = {
            "ok": False,
            "summary": {"status": "active", "rollback_ready": False},
        }
        drained = self.queue_report()
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            commands = fixture.pop("commands")
            fixture.pop("rendered")
            audit_reports = [drained, active, drained, drained]
            with (
                mock.patch.object(deployment, "_preflight", return_value={"ok": True}),
                mock.patch.object(
                    deployment, "_queue_audit", side_effect=audit_reports
                ),
                mock.patch.object(
                    deployment,
                    "_probe_until_healthy",
                    return_value=(self.successful_probe(), 1),
                ),
            ):
                report = deployment.deploy(**fixture)
            self.assertTrue(report["ok"])
            self.assertEqual(report["summary"]["drain_attempt"], 2)
            stop_commands = [command for command in commands if "stop" in command]
            self.assertEqual(len(stop_commands), 2)
            self.assertIn("managed-operation-worker", stop_commands[-1])

    def test_active_queue_audit_is_valid_retryable_evidence(self) -> None:
        active = {
            "artifact_kind": "platform_hosted_managed_production_queue_audit_report",
            "ok": False,
            "summary": {"status": "active", "rollback_ready": False},
        }

        commands: list[list[str]] = []

        def runner(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(
                command, 1, stdout=json.dumps(active), stderr=""
            )

        report = deployment._queue_audit(
            env_file=Path("/etc/0al/production.env"),
            compose_file=Path("/srv/0al/platform/compose.yml"),
            project_name="platform-managed-production",
            runner=runner,
        )
        self.assertFalse(report["ok"])
        self.assertFalse(report["summary"]["rollback_ready"])
        self.assertIn("--no-deps", commands[0])


if __name__ == "__main__":
    unittest.main()
