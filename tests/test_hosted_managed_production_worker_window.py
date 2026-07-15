from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from scripts import hosted_managed_production_worker_window as production_window
from scripts import hosted_managed_worker_window as window_module


REQUEST_ID = (
    "managed-operation://hosted-operation-canary/review_status_execute/"
    + "1" * 24
)


class WindowRunner:
    def __init__(
        self,
        *,
        artifact_root: Path,
        running_before: bool = False,
        timeout: bool = False,
        recovery_fails: bool = False,
        recovery_times_out: bool = False,
        removal_fails: bool = False,
    ) -> None:
        self.artifact_root = artifact_root
        self.running_before = running_before
        self.timeout = timeout
        self.recovery_fails = recovery_fails
        self.recovery_times_out = recovery_times_out
        self.removal_fails = removal_fails
        self.commands: list[list[str]] = []
        self.ps_count = 0

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if "ps" in command:
            self.ps_count += 1
            stdout = (
                "managed-operation-worker\n"
                if self.running_before and self.ps_count == 1
                else "managed-operation-postgres\nmanaged-operation-service\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
        if "run" in command and production_window.MAINTENANCE_SERVICE in command:
            if self.recovery_times_out:
                raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 1))
            return subprocess.CompletedProcess(
                command,
                1 if self.recovery_fails else 0,
                stdout="{}",
                stderr="",
            )
        if "run" in command and production_window.WINDOW_SERVICE in command:
            if self.timeout:
                raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 1))
            window_id = kwargs["env"]["PLATFORM_MANAGED_WORKER_WINDOW_ID"]
            path = window_module.report_path(self.artifact_root, window_id)
            report = {
                "artifact_kind": window_module.REPORT_ARTIFACT_KIND,
                "schema_version": 1,
                "contract_ref": window_module.REPORT_CONTRACT_REF,
                "window_id": window_id,
                "request": {"request_id": REQUEST_ID},
                "policy": {
                    "sha256": window_module.policy_sha256(
                        window_module.load_policy(
                            (
                                Path(window_module.__file__).resolve().parents[1]
                                / "deploy"
                                / "hosted-managed"
                                / "worker-window-policy.json"
                            ).resolve()
                        )
                    )
                },
                "summary": {
                    "status": "bounded_worker_window_completed",
                    "one_shot_cycle_complete": True,
                },
                "privacy_boundary": {
                    "public_safe": True,
                    "includes_request_payload": False,
                    "includes_secret_values": False,
                    "includes_local_paths": False,
                },
                "authority_boundary": {
                    "accepts_arbitrary_commands": False,
                    "expands_operation_allowlist": False,
                    "executes_unpinned_requests": False,
                    "keeps_worker_running": False,
                    "retries_irreversible_operations": False,
                    "queue_status_is_lifecycle_evidence": False,
                    "platform_output_reports_are_authoritative": True,
                },
            }
            window_module.write_report(path, report)
            return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")
        if command[:3] == ["docker", "rm", "--force"]:
            return subprocess.CompletedProcess(
                command,
                1 if self.removal_fails else 0,
                stdout="",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="unexpected")


class HostedManagedProductionWorkerWindowTests(unittest.TestCase):
    def fixture(self, root: Path) -> dict:
        compose_file = root / "compose.yml"
        compose_file.write_text("services: {}\n", encoding="utf-8")
        artifact_root = root / "artifacts"
        artifact_root.mkdir()
        env_file = root / "production.env"
        env_file.write_text(
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST=review_status_execute\n"
            f"PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT={artifact_root}\n"
            "PRIVATE_FIXTURE_SECRET=must-not-leak\n",
            encoding="utf-8",
        )
        return {
            "compose_file": compose_file.resolve(),
            "env_file": env_file.resolve(),
            "project_name": "platform-managed-production",
            "window_id": "pilot-20260715t120000z",
            "request_id": REQUEST_ID,
            "output": (root / "evidence.json").resolve(),
        }

    def test_runbook_window_id_example_matches_contract(self) -> None:
        runbook = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "hosted-managed-operations.md"
        ).read_text(encoding="utf-8")
        match = re.search(
            r'window_id="review-status-\$\(date -u (\+[^)]+)\)"',
            runbook,
        )

        self.assertIsNotNone(match)
        assert match is not None
        date_format = match.group(1).removeprefix("+")
        sample = "review-status-" + datetime.now(timezone.utc).strftime(date_format)
        self.assertRegex(sample, window_module.WINDOW_ID_RE)

    def test_runs_fixed_one_shot_service_and_verifies_stopped_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            runner = WindowRunner(artifact_root=root / "artifacts")

            report = production_window.execute_window(**fixture, runner=runner)

        self.assertEqual(
            report["summary"]["status"],
            "production_bounded_worker_window_completed",
        )
        self.assertTrue(report["summary"]["worker_stopped"])
        run_commands = [
            command
            for command in runner.commands
            if production_window.WINDOW_SERVICE in command
        ]
        self.assertEqual(len(run_commands), 1)
        self.assertIn(production_window.WINDOW_SERVICE, run_commands[0])
        self.assertIn("--no-deps", run_commands[0])
        self.assertNotIn("must-not-leak", json.dumps(report))
        self.assertNotIn(temp_dir, json.dumps(report))

    def test_running_continuous_worker_blocks_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            runner = WindowRunner(
                artifact_root=root / "artifacts",
                running_before=True,
            )

            report = production_window.execute_window(**fixture, runner=runner)

        self.assertEqual(
            report["summary"]["status"],
            "production_bounded_worker_window_blocked",
        )
        self.assertIn(
            "worker_already_running_before_window",
            report["diagnostics"],
        )
        self.assertFalse(
            any(production_window.WINDOW_SERVICE in command for command in runner.commands)
        )

    def test_existing_matching_evidence_returns_without_compose_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            first_runner = WindowRunner(artifact_root=root / "artifacts")
            expected = production_window.execute_window(
                **fixture,
                runner=first_runner,
            )
            second_runner = WindowRunner(artifact_root=root / "artifacts")

            repeated = production_window.execute_window(
                **fixture,
                runner=second_runner,
            )

        self.assertEqual(repeated, expected)
        self.assertEqual(second_runner.commands, [])

    def test_foreign_existing_evidence_blocks_before_compose_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            fixture["output"].write_text(
                json.dumps({"artifact_kind": "foreign"}),
                encoding="utf-8",
            )
            runner = WindowRunner(artifact_root=root / "artifacts")

            with self.assertRaisesRegex(
                production_window.ProductionWorkerWindowError,
                "violates its contract",
            ):
                production_window.execute_window(**fixture, runner=runner)

        self.assertEqual(runner.commands, [])

    def test_strict_recovery_failure_blocks_before_worker_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            runner = WindowRunner(
                artifact_root=root / "artifacts",
                recovery_fails=True,
            )

            report = production_window.execute_window(**fixture, runner=runner)

        self.assertEqual(
            report["summary"]["status"],
            "production_bounded_worker_window_blocked",
        )
        self.assertIn("strict_recovery_preflight_failed", report["diagnostics"])
        self.assertFalse(
            any(production_window.WINDOW_SERVICE in command for command in runner.commands)
        )

    def test_strict_recovery_timeout_blocks_before_worker_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            runner = WindowRunner(
                artifact_root=root / "artifacts",
                recovery_times_out=True,
            )

            report = production_window.execute_window(**fixture, runner=runner)

        self.assertIn("strict_recovery_preflight_timed_out", report["diagnostics"])
        self.assertFalse(
            any(production_window.WINDOW_SERVICE in command for command in runner.commands)
        )

    def test_timeout_forces_container_removal_and_blocks_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            runner = WindowRunner(
                artifact_root=root / "artifacts",
                timeout=True,
            )

            report = production_window.execute_window(**fixture, runner=runner)

        self.assertEqual(
            report["summary"]["status"],
            "production_bounded_worker_window_blocked",
        )
        self.assertIn(
            "bounded_worker_container_timed_out",
            report["diagnostics"],
        )
        self.assertTrue(
            any(command[:3] == ["docker", "rm", "--force"] for command in runner.commands)
        )

    def test_timeout_surfaces_failed_container_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            runner = WindowRunner(
                artifact_root=root / "artifacts",
                timeout=True,
                removal_fails=True,
            )

            report = production_window.execute_window(**fixture, runner=runner)

        self.assertIn(
            "bounded_worker_container_removal_failed",
            report["diagnostics"],
        )


if __name__ == "__main__":
    unittest.main()
