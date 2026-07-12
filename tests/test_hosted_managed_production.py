from __future__ import annotations

from datetime import datetime, timezone
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import hosted_managed_production_preflight as preflight
from scripts import hosted_managed_production_probe as probe
from scripts import hosted_managed_production_signoff as signoff
from scripts import hosted_managed_runtime_backup as backup


class HostedManagedProductionPreflightTests(unittest.TestCase):
    def fixture(self, root: Path) -> dict:
        uid = os.getuid()
        gid = os.getgid()
        artifact_root = root / "artifacts"
        state_dir = root / "state"
        artifact_root.mkdir()
        state_dir.mkdir()
        secrets = root / "secrets"
        secrets.mkdir()
        values = {
            "service_token": b"service-token-0123456789abcdef0123456789abcdef",
            "database_password": b"database-password-0123456789abcdef",
            "database_url": (
                b"postgresql://managed:password@managed-operation-postgres/managed"
            ),
            "github_token": b"github-token-0123456789abcdef",
            "tls_certificate": (
                b"-----BEGIN CERTIFICATE-----\n"
                + b"A" * 80
                + b"\n-----END CERTIFICATE-----"
            ),
            "tls_private_key": (
                b"-----BEGIN PRIVATE KEY-----\n"
                + b"B" * 80
                + b"\n-----END PRIVATE KEY-----"
            ),
        }
        secret_paths = {}
        for label, value in values.items():
            path = secrets / label
            path.write_bytes(value)
            path.chmod(0o440)
            secret_paths[label] = path
        digest = "a" * 64
        return {
            "service_url": "https://managed.example.test",
            "allowlist": "review_status_execute",
            "image_refs": {
                "platform": f"ghcr.io/0al/platform@sha256:{digest}",
                "postgresql": f"postgres@sha256:{digest}",
                "ingress": f"caddy@sha256:{digest}",
            },
            "secret_paths": secret_paths,
            "artifact_root": artifact_root,
            "state_dir": state_dir,
            "expected_secret_uid": uid,
            "runtime_uid": uid,
            "runtime_gid": gid,
        }

    def test_ready_preflight_is_public_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            report = preflight.run_preflight(**fixture)
        self.assertTrue(report["ok"], report["diagnostics"])
        self.assertEqual(report["summary"]["enabled_operations"], ["review_status_execute"])
        rendered = str(report)
        self.assertNotIn(temp_dir, rendered)
        self.assertNotIn("service-token", rendered)

    def test_preflight_rejects_unsafe_transport_scope_and_secret_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            fixture["service_url"] = "http://managed.example.test?token=value"
            fixture["allowlist"] = "review_status_execute,promotion_review_execute"
            fixture["secret_paths"]["service_token"].chmod(0o644)
            report = preflight.run_preflight(**fixture)
        self.assertFalse(report["ok"])
        self.assertIn("service_url_not_private_https_endpoint", report["diagnostics"])
        self.assertIn("deployment_allowlist_not_exact_canary_scope", report["diagnostics"])
        self.assertIn("service_token_mode_not_0440", report["diagnostics"])

    def test_preflight_requires_distinct_secret_values_and_digest_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            shared = fixture["secret_paths"]["service_token"].read_bytes()
            fixture["secret_paths"]["github_token"].chmod(0o600)
            fixture["secret_paths"]["github_token"].write_bytes(shared)
            fixture["secret_paths"]["github_token"].chmod(0o440)
            fixture["image_refs"]["platform"] = "ghcr.io/0al/platform:latest"
            report = preflight.run_preflight(**fixture)
        self.assertFalse(report["ok"])
        self.assertIn("secret_values_not_distinct", report["diagnostics"])
        self.assertIn("platform_image_not_digest_pinned", report["diagnostics"])

    def test_dry_run_requires_explicit_preflight_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            fixture["allowlist"] = (
                "review_status_execute,promotion_execute_dry_run"
            )
            blocked = preflight.run_preflight(**fixture)
            fixture["allow_dry_run"] = True
            ready = preflight.run_preflight(**fixture)
        self.assertFalse(blocked["ok"])
        self.assertTrue(ready["ok"], ready["diagnostics"])


class HostedManagedRuntimeBackupTests(unittest.TestCase):
    def test_backup_archives_workspace_artifacts_without_paths_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_root = root / "specgraph"
            run_dir = artifact_root / "runs" / "workspace-a"
            run_dir.mkdir(parents=True)
            (run_dir / "report.json").write_text('{"ok":true}\n', encoding="utf-8")
            database_url = root / "database-url"
            database_url.write_text(
                "postgresql://managed:password@postgres/managed\n",
                encoding="utf-8",
            )
            backup_root = root / "backups"
            backup_root.mkdir()
            database_export = {
                "artifact_kind": "platform_hosted_managed_queue_backup",
                "schema_version": 1,
                "tables": {table: [] for table in backup.QUEUE_TABLES},
            }
            with mock.patch.object(
                backup, "_database_export", return_value=database_export
            ), mock.patch.object(
                backup,
                "_row_counts",
                return_value={table: 0 for table in backup.QUEUE_TABLES},
            ):
                report = backup.create_backup(
                    database_url_file=database_url,
                    artifact_root=artifact_root,
                    backup_root=backup_root,
                    backup_id="test-backup",
                )

            destination = backup_root / "test-backup"
            backup._verify_artifact_archive(
                destination / "workspace-artifacts.tar.gz",
                report["artifact_inventory"],
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["summary"]["artifact_file_count"], 1)
            self.assertFalse(report["privacy_boundary"]["public_safe"])
            self.assertNotIn(temp_dir, str(report))

    def test_backup_refuses_symbolic_links_in_artifact_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs = root / "runs"
            runs.mkdir()
            target = root / "private.json"
            target.write_text("private", encoding="utf-8")
            (runs / "linked.json").symlink_to(target)
            with self.assertRaisesRegex(backup.HostedBackupError, "symbolic links"):
                backup._artifact_inventory(root)

    def test_restore_smoke_rejects_tampered_database_export_before_connecting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_root = root / "specgraph"
            (artifact_root / "runs").mkdir(parents=True)
            database_url = root / "database-url"
            database_url.write_text(
                "postgresql://managed:password@postgres/managed\n",
                encoding="utf-8",
            )
            backup_root = root / "backups"
            backup_root.mkdir()
            database_export = {
                "artifact_kind": "platform_hosted_managed_queue_backup",
                "schema_version": 1,
                "tables": {table: [] for table in backup.QUEUE_TABLES},
            }
            with mock.patch.object(
                backup, "_database_export", return_value=database_export
            ), mock.patch.object(
                backup,
                "_row_counts",
                return_value={table: 0 for table in backup.QUEUE_TABLES},
            ):
                backup.create_backup(
                    database_url_file=database_url,
                    artifact_root=artifact_root,
                    backup_root=backup_root,
                    backup_id="tampered",
                )
            export_path = backup_root / "tampered" / "managed-operations.json"
            export_path.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(backup, "_driver") as driver:
                with self.assertRaisesRegex(backup.HostedBackupError, "digest mismatch"):
                    backup.restore_smoke(
                        database_url_file=database_url,
                        backup_root=backup_root,
                        backup_id="tampered",
                    )
            driver.assert_not_called()


class HostedManagedProductionProbeTests(unittest.TestCase):
    def fixture_runner(self, *, heartbeat_generated_at: str):
        rows = [
            {
                "Service": service,
                "State": "running",
                "Health": "healthy",
            }
            for service in sorted(probe.EXPECTED_SERVICES)
        ]
        heartbeat = {
            "artifact_kind": "platform_hosted_managed_operation_worker_health",
            "ok": True,
            "adapter": "postgresql",
            "generated_at": heartbeat_generated_at,
            "heartbeat_sequence": 12,
            "last_cycle_status": "hosted_managed_operation_worker_idle",
        }

        def runner(command, **kwargs):
            output = json.dumps(heartbeat) if "exec" in command else json.dumps(rows)
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

        return runner

    def test_probe_requires_healthy_tls_runtime_and_exact_allowlist(self) -> None:
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        report = probe.run_probe(
            service_url="https://managed.example.test",
            compose_file=Path("/srv/platform/compose.yml"),
            project_name="platform-managed",
            now=now,
            runner=self.fixture_runner(heartbeat_generated_at=now.isoformat()),
            fetch_health=lambda _: {
                "ok": True,
                "adapter": "postgresql",
                "enabled_operation_ids": ["review_status_execute"],
            },
        )
        self.assertTrue(report["ok"], report["diagnostics"])
        self.assertEqual(report["summary"]["healthy_service_count"], 4)
        self.assertNotIn("/srv/platform", str(report))

    def test_probe_blocks_stale_heartbeat_and_expanded_allowlist(self) -> None:
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        report = probe.run_probe(
            service_url="https://managed.example.test",
            compose_file=Path("/srv/platform/compose.yml"),
            project_name="platform-managed",
            now=now,
            runner=self.fixture_runner(
                heartbeat_generated_at="2026-07-12T23:58:00+00:00"
            ),
            fetch_health=lambda _: {
                "ok": True,
                "adapter": "postgresql",
                "enabled_operation_ids": [
                    "review_status_execute",
                    "promotion_execute_dry_run",
                ],
            },
        )
        self.assertFalse(report["ok"])
        self.assertIn("worker_heartbeat_stale", report["diagnostics"])
        self.assertIn("service_allowlist_not_read_only_canary", report["diagnostics"])

    def test_probe_rejects_url_userinfo_before_fetching(self) -> None:
        with self.assertRaisesRegex(
            probe.ProductionProbeError,
            "clean HTTPS service URL",
        ):
            probe.run_probe(
                service_url="https://user:password@managed.example.test",
                compose_file=Path("/srv/platform/compose.yml"),
                project_name="platform-managed",
                fetch_health=lambda _: self.fail("health must not be fetched"),
            )


class HostedManagedProductionSignoffTests(unittest.TestCase):
    def evidence(self) -> dict[str, dict]:
        generated_at = "2026-07-13T00:00:00+00:00"
        reports = {
            label: {
                "artifact_kind": kind,
                "generated_at": generated_at,
                "ok": True,
            }
            for label, kind in signoff.EXPECTED_KINDS.items()
        }
        for label in ("probe_before_reboot", "probe_after_reboot"):
            reports[label].update(
                {
                    "summary": {"status": "healthy"},
                    "service": {
                        "origin": "https://managed.example.test",
                        "enabled_operation_ids": ["review_status_execute"],
                    },
                }
            )
        canary = {
            "summary": {"profile": "read_only"},
            "queue": {"status": "succeeded", "attempt": 1},
            "request": {
                "request_id": "managed-operation://request-1",
                "idempotency_key": "idempotency-1",
                "operation_id": "review_status_execute",
                "workspace_id": "hosted-operation-canary",
            },
            "authoritative_outputs": {
                "observed_refs": ["runs/workspace/review.json"],
                "verified_refs": ["runs/workspace/review.json"],
                "receipt_pins_reports": True,
            },
        }
        reports["canary"].update(copy.deepcopy(canary))
        reports["replay_canary"].update(copy.deepcopy(canary))
        reports["recovery"]["summary"] = {
            "strict": True,
            "policy_safe": True,
            "preflight_blocked": False,
        }
        reports["preflight"]["summary"] = {
            "status": "ready",
            "enabled_operations": ["review_status_execute"],
            "dry_run_enabled": False,
        }
        reports["backup"]["backup_id"] = "production-1"
        reports["backup"]["summary"] = {
            "status": "backup_ready",
            "database_backup_schema_version": 1,
        }
        reports["restore_smoke"]["backup_id"] = "production-1"
        reports["restore_smoke"]["summary"] = {
            "status": "restore_smoke_passed",
            "temporary_database_removed": True,
        }
        reports["queue_audit"]["summary"] = {"rollback_ready": True}
        reports["hosted_specspace_smoke"]["summary"] = {
            "expected_managed_mode": "backend_managed_ready"
        }
        reports["rollback_specspace_smoke"]["summary"] = {
            "expected_managed_mode": "read_only"
        }
        return reports

    def test_signoff_requires_complete_reboot_replay_backup_and_rollback_evidence(self) -> None:
        report = signoff.build_signoff(
            self.evidence(),
            now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        )
        self.assertTrue(report["ok"], report["diagnostics"])
        self.assertEqual(report["summary"]["status"], "production_canary_signed_off")
        self.assertTrue(report["summary"]["rollback_verified"])

    def test_signoff_blocks_reexecution_and_expanded_allowlist(self) -> None:
        evidence = self.evidence()
        evidence["replay_canary"]["queue"]["attempt"] = 2
        evidence["probe_after_reboot"]["service"]["enabled_operation_ids"] = [
            "review_status_execute",
            "promotion_execute_dry_run",
        ]
        report = signoff.build_signoff(
            evidence,
            now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        )
        self.assertFalse(report["ok"])
        self.assertIn("replay_canary_attempt_not_one", report["diagnostics"])
        self.assertIn("probe_after_reboot_allowlist_invalid", report["diagnostics"])

    def test_signoff_rejects_write_capable_evidence(self) -> None:
        evidence = self.evidence()
        evidence["canary"]["authority_boundary"] = {"may_execute_platform": True}
        report = signoff.build_signoff(
            evidence,
            now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        )
        self.assertFalse(report["ok"])
        self.assertIn("canary_write_authority_expanded", report["diagnostics"])

    def test_signoff_rejects_stale_and_out_of_order_evidence(self) -> None:
        evidence = self.evidence()
        evidence["preflight"]["generated_at"] = "2026-07-10T00:00:00+00:00"
        evidence["backup"]["generated_at"] = "2026-07-13T00:30:00+00:00"
        evidence["probe_before_reboot"]["generated_at"] = (
            "2026-07-13T00:45:00+00:00"
        )
        report = signoff.build_signoff(
            evidence,
            now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        )
        self.assertFalse(report["ok"])
        self.assertIn("preflight_evidence_stale", report["diagnostics"])
        self.assertIn(
            "evidence_order_invalid_probe_before_reboot_after_backup",
            report["diagnostics"],
        )


if __name__ == "__main__":
    unittest.main()
