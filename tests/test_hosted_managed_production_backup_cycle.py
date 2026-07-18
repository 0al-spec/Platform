from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import hosted_managed_production_backup_cycle as backup_cycle


def _completed(command: list[str], *, stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(command, returncode, stdout, "")


class ProductionBackupCycleTests(unittest.TestCase):
    def fixture(self, root: Path) -> dict:
        return {
            "backup_id": "production-20260714t120000z",
            "service_url": "https://managed.example.test",
            "compose_file": root / "compose.yml",
            "env_file": root / "production.env",
            "project_name": "platform-managed-production",
            "backup_root": root / "backups",
            "probe_output": root / "evidence" / "probe-before.json",
            "backup_id_output": root / "evidence" / "backup-id.txt",
            "sleep": lambda _seconds: None,
        }

    def test_cycle_quiesces_backs_up_verifies_and_recovers_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calls: list[list[str]] = []

            def runner(command, **_kwargs):
                calls.append(command)
                rendered = " ".join(command)
                if "queue-audit" in rendered:
                    return _completed(
                        command,
                        stdout=json.dumps(
                            {
                                "ok": True,
                                "summary": {
                                    "rollback_ready": True,
                                    "active_job_count": 0,
                                    "lock_count": 0,
                                },
                            }
                        ),
                    )
                if " restore-smoke " in f" {rendered} ":
                    backup_dir = root / "backups" / "production-20260714t120000z"
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    for name in (
                        "backup-report.json",
                        "managed-operations.json",
                        "specspace-state.json",
                        "restore-smoke-report.json",
                        "workspace-artifacts.tar.gz",
                    ):
                        (backup_dir / name).write_text("fixture", encoding="utf-8")
                    return _completed(
                        command,
                        stdout=json.dumps(
                            {
                                "ok": True,
                                "summary": {
                                    "status": "restore_smoke_passed",
                                    "database_row_counts_verified": True,
                                    "state_database_row_counts_verified": True,
                                    "artifact_inventory_verified": True,
                                    "temporary_database_removed": True,
                                },
                            }
                        ),
                    )
                if (
                    "hosted_managed_runtime_backup.py" in rendered
                    and "restore-smoke" not in rendered
                ):
                    return _completed(
                        command,
                        stdout=json.dumps(
                            {
                                "ok": True,
                                "summary": {"status": "backup_ready"},
                            }
                        ),
                    )
                return _completed(command)

            probe_calls: list[str] = []

            def probe(**_kwargs):
                probe_calls.append("probe")
                return {"ok": True, "summary": {"status": "ready"}}

            report = backup_cycle.run_backup_cycle(
                **self.fixture(root), runner=runner, probe=probe
            )

            self.assertTrue(report["ok"], report["diagnostics"])
            self.assertEqual(report["summary"]["status"], "backup_cycle_ready")
            self.assertTrue(report["summary"]["runtime_recovered"])
            self.assertEqual(len(probe_calls), 2)
            self.assertEqual(
                (root / "evidence" / "backup-id.txt").read_text().strip(),
                "production-20260714t120000z",
            )
            rendered_calls = [" ".join(command) for command in calls]
            stop_boundary = next(
                index
                for index, command in enumerate(rendered_calls)
                if (
                    " stop managed-operation-ingress managed-operation-service "
                    "specspace-state-service"
                    in command
                )
            )
            stop_worker = next(
                index
                for index, command in enumerate(rendered_calls)
                if " stop managed-operation-worker" in command
            )
            backup = next(
                index
                for index, command in enumerate(rendered_calls)
                if "hosted_managed_runtime_backup.py backup" in command
            )
            restart = next(
                index
                for index, command in enumerate(rendered_calls)
                if (
                    " up --detach specspace-state-service "
                    "managed-operation-service"
                    in command
                )
            )
            self.assertLess(stop_boundary, stop_worker)
            self.assertLess(stop_worker, backup)
            self.assertLess(backup, restart)

    def test_backup_failure_still_recovers_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calls: list[str] = []

            def runner(command, **_kwargs):
                rendered = " ".join(command)
                calls.append(rendered)
                if "queue-audit" in rendered:
                    return _completed(
                        command,
                        stdout=json.dumps(
                            {
                                "ok": True,
                                "summary": {
                                    "rollback_ready": True,
                                    "active_job_count": 0,
                                    "lock_count": 0,
                                },
                            }
                        ),
                    )
                if "hosted_managed_runtime_backup.py backup" in rendered:
                    return _completed(command, returncode=1)
                return _completed(command)

            report = backup_cycle.run_backup_cycle(
                **self.fixture(root),
                runner=runner,
                probe=lambda **_kwargs: {"ok": True},
            )

            self.assertFalse(report["ok"])
            self.assertTrue(report["summary"]["runtime_recovered"])
            self.assertTrue(
                any(
                    " up --detach specspace-state-service "
                    "managed-operation-service"
                    in command
                    for command in calls
                )
            )
            self.assertFalse((root / "evidence" / "backup-id.txt").exists())

    def test_partial_quiesce_failure_still_attempts_runtime_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calls: list[str] = []

            def runner(command, **_kwargs):
                rendered = " ".join(command)
                calls.append(rendered)
                if "queue-audit" in rendered:
                    return _completed(
                        command,
                        stdout=json.dumps(
                            {
                                "ok": True,
                                "summary": {
                                    "rollback_ready": True,
                                    "active_job_count": 0,
                                    "lock_count": 0,
                                },
                            }
                        ),
                    )
                if " stop managed-operation-ingress" in rendered:
                    return _completed(command, returncode=1)
                return _completed(command)

            report = backup_cycle.run_backup_cycle(
                **self.fixture(root),
                runner=runner,
                probe=lambda **_kwargs: {"ok": True},
            )

            self.assertFalse(report["ok"])
            self.assertTrue(report["summary"]["runtime_recovered"])
            self.assertTrue(
                any(
                    " up --detach specspace-state-service "
                    "managed-operation-service"
                    in command
                    for command in calls
                )
            )

    def test_cycle_rejects_unsafe_backup_id_before_compose(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(Path(temp_dir))
            fixture["backup_id"] = "../production"
            with self.assertRaisesRegex(
                backup_cycle.ProductionBackupCycleError, "backup id is invalid"
            ):
                backup_cycle.run_backup_cycle(**fixture)


if __name__ == "__main__":
    unittest.main()
