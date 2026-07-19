from __future__ import annotations

from datetime import datetime, timezone
import hashlib
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
DRY_RUN_REQUEST_ID = (
    "managed-operation://hosted-operation-canary/promotion_execute_dry_run/"
    + "2" * 24
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
        window_service = next(
            (
                service
                for service in (
                    production_window.WINDOW_SERVICE,
                    production_window.PROMOTION_DRY_RUN_WINDOW_SERVICE,
                )
                if "run" in command and service in command
            ),
            None,
        )
        if window_service is not None:
            if self.timeout:
                raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 1))
            window_id = kwargs["env"]["PLATFORM_MANAGED_WORKER_WINDOW_ID"]
            request_id = kwargs["env"]["PLATFORM_MANAGED_WORKER_WINDOW_REQUEST_ID"]
            dry_run = (
                window_service == production_window.PROMOTION_DRY_RUN_WINDOW_SERVICE
            )
            policy_filename = (
                "promotion-dry-run-worker-window-policy.json"
                if dry_run
                else "worker-window-policy.json"
            )
            operation_id = (
                "promotion_execute_dry_run" if dry_run else "review_status_execute"
            )
            output_reports = []
            if dry_run:
                workspace_runs = (
                    self.artifact_root / "runs" / "hosted-operation-canary"
                )
                workspace_runs.mkdir(parents=True, exist_ok=True)
                product_path = (
                    workspace_runs
                    / "product_candidate_promotion_execution_report.json"
                )
                product_path.write_text(
                    json.dumps(
                        {
                            "artifact_kind": "platform_product_candidate_promotion_execution_report",
                            "ok": True,
                            "dry_run": True,
                            "open_review_dry_run": True,
                            "summary": {
                                "status": "dry_run",
                                "worktree_prepare_dry_run": True,
                                "physical_worktree_created": False,
                                "commit_created": False,
                                "review_opened": False,
                                "read_model_published": False,
                            },
                            "git_review": {
                                "physical_worktree_created": False,
                                "commit_sha": None,
                                "review_url": None,
                                "review_opened": False,
                            },
                            "authority_boundary": {
                                "specspace_direct_git_write": False,
                                "controlled_git_service_execution": False,
                                "creates_candidate_worktree_or_branch": False,
                                "creates_candidate_commit": False,
                                "opens_pull_requests": False,
                                "merges_pull_requests": False,
                                "publishes_read_models": False,
                                "canonical_spec_mutation_without_review": False,
                                "ontology_package_write": False,
                                "ontology_term_acceptance": False,
                                "private_artifact_publication": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                git_path = workspace_runs / "git_service_promotion_execution_report.json"
                git_path.write_text(
                    json.dumps(
                        {
                            "artifact_kind": "platform_git_service_promotion_execution_report",
                            "ok": True,
                            "dry_run": True,
                            "open_review_dry_run": True,
                            "copied_materialized_files": [],
                            "operations": [
                                {"name": "prepare_worktree", "status": "dry_run"},
                                {"name": "commit_candidate", "status": "skipped_dry_run"},
                                {"name": "open_review", "status": "skipped_dry_run"},
                            ],
                            "authority_boundary": {
                                "specspace_direct_git_write": False,
                                "canonical_spec_mutation_without_review": False,
                                "ontology_package_write": False,
                                "auto_merge": False,
                                "private_artifact_publication": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                for logical_ref, report_path in (
                    (
                        "runs/product_candidate_promotion_execution_report.json",
                        product_path,
                    ),
                    ("runs/git_service_promotion_execution_report.json", git_path),
                ):
                    output_reports.append(
                        {
                            "logical_ref": logical_ref,
                            "sha256": hashlib.sha256(
                                report_path.read_bytes()
                            ).hexdigest(),
                        }
                    )
            path = window_module.report_path(self.artifact_root, window_id)
            report = {
                "artifact_kind": window_module.REPORT_ARTIFACT_KIND,
                "schema_version": 1,
                "contract_ref": window_module.REPORT_CONTRACT_REF,
                "window_id": window_id,
                "request": {
                    "request_id": request_id,
                    "operation_id": operation_id,
                    "workspace_id": "hosted-operation-canary",
                },
                "policy": {
                    "sha256": window_module.policy_sha256(
                        window_module.load_policy(
                            (
                                Path(window_module.__file__).resolve().parents[1]
                                / "deploy"
                                / "hosted-managed"
                                / policy_filename
                            ).resolve()
                        )
                    )
                },
                "summary": {
                    "status": "bounded_worker_window_completed",
                    "one_shot_cycle_complete": True,
                },
                "execution": {
                    "authoritative_output_reports": output_reports,
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

    def dry_run_fixture(self, root: Path) -> dict:
        fixture = self.fixture(root)
        fixture["env_file"].write_text(
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST=promotion_execute_dry_run\n"
            f"PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT={root / 'artifacts'}\n",
            encoding="utf-8",
        )
        fixture["request_id"] = DRY_RUN_REQUEST_ID
        fixture["window_id"] = "promotion-dry-run-20260715t120000z"
        fixture["operation_profile"] = "promotion-dry-run"
        return fixture

    def use_bounded_product_allowlist(self, fixture: dict) -> None:
        content = fixture["env_file"].read_text(encoding="utf-8")
        content = re.sub(
            r"PLATFORM_MANAGED_OPERATION_ALLOWLIST=[^\n]+",
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST="
            "promotion_execute_dry_run,review_status_execute",
            content,
        )
        fixture["env_file"].write_text(content, encoding="utf-8")

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
        self.assertIn(
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST=review_status_execute",
            run_commands[0],
        )
        recovery_command = next(
            command
            for command in runner.commands
            if production_window.MAINTENANCE_SERVICE in command
        )
        self.assertEqual(
            recovery_command[
                recovery_command.index("--expected-request-id") + 1
            ],
            REQUEST_ID,
        )
        self.assertNotIn("must-not-leak", json.dumps(report))
        self.assertNotIn(temp_dir, json.dumps(report))

    def test_runs_strict_promotion_dry_run_service_and_verifies_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.dry_run_fixture(root)
            runner = WindowRunner(artifact_root=root / "artifacts")

            report = production_window.execute_window(**fixture, runner=runner)
            physical_workspace_created = (
                root
                / "artifacts"
                / ".platform"
                / "candidates"
                / "hosted-operation-canary"
            ).exists()

        self.assertEqual(
            report["summary"]["status"],
            "production_bounded_worker_window_completed",
        )
        self.assertEqual(report["operation_profile"], "promotion-dry-run")
        self.assertTrue(report["summary"]["dry_run_reports_verified"])
        self.assertFalse(physical_workspace_created)
        self.assertTrue(
            any(
                production_window.PROMOTION_DRY_RUN_WINDOW_SERVICE in command
                for command in runner.commands
            )
        )

    def test_combined_deployment_still_uses_operation_specific_worker_scope(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_fixture = self.fixture(root)
            self.use_bounded_product_allowlist(review_fixture)
            review_runner = WindowRunner(artifact_root=root / "artifacts")
            review_report = production_window.execute_window(
                **review_fixture,
                runner=review_runner,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dry_run_fixture = self.dry_run_fixture(root)
            self.use_bounded_product_allowlist(dry_run_fixture)
            dry_run_runner = WindowRunner(artifact_root=root / "artifacts")
            dry_run_report = production_window.execute_window(
                **dry_run_fixture,
                runner=dry_run_runner,
            )

        self.assertEqual(
            review_report["summary"]["status"],
            "production_bounded_worker_window_completed",
        )
        self.assertEqual(
            dry_run_report["summary"]["status"],
            "production_bounded_worker_window_completed",
        )
        review_command = next(
            command
            for command in review_runner.commands
            if production_window.WINDOW_SERVICE in command
        )
        dry_run_command = next(
            command
            for command in dry_run_runner.commands
            if production_window.PROMOTION_DRY_RUN_WINDOW_SERVICE in command
        )
        self.assertIn(
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST=review_status_execute",
            review_command,
        )
        self.assertNotIn("promotion_execute_dry_run", review_command)
        self.assertIn(
            "PLATFORM_MANAGED_OPERATION_ALLOWLIST=promotion_execute_dry_run",
            dry_run_command,
        )
        self.assertNotIn("review_status_execute", dry_run_command)

    def test_worker_rejects_unapproved_deployment_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            fixture["env_file"].write_text(
                "PLATFORM_MANAGED_OPERATION_ALLOWLIST="
                "review_status_execute,promotion_review_execute\n"
                f"PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT={root / 'artifacts'}\n",
                encoding="utf-8",
            )
            runner = WindowRunner(artifact_root=root / "artifacts")

            with self.assertRaisesRegex(
                production_window.ProductionWorkerWindowError,
                "not an approved deployment profile",
            ):
                production_window.execute_window(**fixture, runner=runner)

        self.assertEqual(runner.commands, [])

    def test_dry_run_blocks_when_report_claims_git_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.dry_run_fixture(root)
            runner = WindowRunner(artifact_root=root / "artifacts")
            original = runner.__call__

            def mutation_runner(command, **kwargs):
                completed = original(command, **kwargs)
                if production_window.PROMOTION_DRY_RUN_WINDOW_SERVICE in command:
                    report_path = (
                        root
                        / "artifacts"
                        / "runs"
                        / "hosted-operation-canary"
                        / "product_candidate_promotion_execution_report.json"
                    )
                    payload = json.loads(report_path.read_text(encoding="utf-8"))
                    payload["summary"]["commit_created"] = True
                    report_path.write_text(json.dumps(payload), encoding="utf-8")
                return completed

            report = production_window.execute_window(
                **fixture,
                runner=mutation_runner,
            )

        self.assertEqual(
            report["summary"]["status"],
            "production_bounded_worker_window_blocked",
        )
        self.assertIn(
            "product_promotion_report_not_strict_dry_run",
            report["diagnostics"],
        )
        self.assertIn(
            "dry_run_authoritative_report_digest_mismatch",
            report["diagnostics"],
        )

    def test_dry_run_blocks_when_physical_candidate_workspace_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.dry_run_fixture(root)
            candidate_workspace = (
                root
                / "artifacts"
                / ".platform"
                / "candidates"
                / "hosted-operation-canary"
            )
            candidate_workspace.mkdir(parents=True)
            runner = WindowRunner(artifact_root=root / "artifacts")

            report = production_window.execute_window(**fixture, runner=runner)

        self.assertEqual(
            report["summary"]["status"],
            "production_bounded_worker_window_blocked",
        )
        self.assertIn("dry_run_physical_worktree_present", report["diagnostics"])

    def test_request_operation_must_match_selected_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.dry_run_fixture(root)
            fixture["request_id"] = REQUEST_ID
            runner = WindowRunner(artifact_root=root / "artifacts")

            with self.assertRaisesRegex(
                production_window.ProductionWorkerWindowError,
                "does not match the production profile",
            ):
                production_window.execute_window(**fixture, runner=runner)

        self.assertEqual(runner.commands, [])

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
