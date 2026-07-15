from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import hosted_managed_operation_queue as queue_module
from scripts import hosted_managed_worker_window as window_module
from tests.test_hosted_managed_operation_queue import (
    SuccessfulExecutor,
    request_for,
)


POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "hosted-managed"
    / "worker-window-policy.json"
)
REPO_ROOT = Path(__file__).resolve().parents[1]


class TerminalExecutor:
    def __init__(self, status: str) -> None:
        self.status = status

    def execute(
        self,
        leased: queue_module.LeasedOperation,
    ) -> queue_module.ExecutionResult:
        return queue_module.ExecutionResult(
            status=self.status,
            diagnostics=(f"fixture {self.status}",),
        )


class InvalidOutputExecutor:
    def execute(
        self,
        leased: queue_module.LeasedOperation,
    ) -> queue_module.ExecutionResult:
        return queue_module.ExecutionResult(
            status="succeeded",
            output_reports=(
                {
                    "logical_ref": window_module.READ_ONLY_OUTPUT_REF,
                    "sha256": "invalid",
                },
            ),
        )


class HostedManagedWorkerWindowTests(unittest.TestCase):
    def policy(self) -> dict:
        return window_module.load_policy(POLICY_PATH.resolve())

    def run_window(
        self,
        queue: queue_module.ManagedOperationQueue,
        request_id: str,
        *,
        executor: queue_module.ManagedOperationExecutor | None = None,
        allowlist: frozenset[str] = frozenset({"review_status_execute"}),
    ) -> dict:
        return window_module.run_window(
            queue=queue,
            executor=executor or SuccessfulExecutor(),
            policy=self.policy(),
            window_id="window-20260715t120000z",
            expected_request_id=request_id,
            worker_id="bounded-worker-a",
            allowed_operation_ids=allowlist,
        )

    def test_policy_is_versioned_read_only_and_fail_closed(self) -> None:
        policy = self.policy()
        self.assertEqual(
            policy["enabled_operation_ids"],
            ["review_status_execute"],
        )
        expanded = copy.deepcopy(policy)
        expanded["enabled_operation_ids"].append("promotion_execute_dry_run")
        self.assertIn(
            "policy_operation_scope_invalid",
            window_module.policy_diagnostics(expanded),
        )
        expanded = copy.deepcopy(policy)
        expanded["authority_boundary"]["may_keep_worker_running"] = True
        self.assertIn(
            "policy_authority_expanded",
            window_module.policy_diagnostics(expanded),
        )

    def test_executes_one_pinned_request_and_drains_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "review_status_execute")
            queue.enqueue(
                request,
                now_epoch=100,
                now_iso="2026-07-15T12:00:00Z",
            )

            report = self.run_window(queue, request["request_id"])
            job = queue.get(request["request_id"])
            queue.close()

        self.assertEqual(
            report["summary"]["status"],
            "bounded_worker_window_completed",
        )
        self.assertTrue(report["summary"]["one_shot_cycle_complete"])
        self.assertTrue(report["summary"]["queue_drained"])
        self.assertEqual(report["summary"]["processed_operation_count"], 1)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["attempt"], 1)
        self.assertTrue(report["execution"]["authoritative_output_reports"])
        self.assertNotIn(temp_dir, json.dumps(report))

    def test_foreign_queued_request_blocks_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            expected = request_for(temp, "review_status_execute")
            foreign = request_for(
                temp,
                "review_status_execute",
                workspace_id="foreign-workspace",
            )
            for request in (expected, foreign):
                queue.enqueue(
                    request,
                    now_epoch=100,
                    now_iso="2026-07-15T12:00:00Z",
                )

            report = self.run_window(queue, expected["request_id"])
            expected_job = queue.get(expected["request_id"])
            foreign_job = queue.get(foreign["request_id"])
            queue.close()

        self.assertEqual(
            report["summary"]["status"],
            "bounded_worker_window_blocked",
        )
        self.assertIn(
            "queue_not_exclusive_to_expected_request",
            report["diagnostics"],
        )
        self.assertEqual(expected_job["status"], "queued")
        self.assertEqual(foreign_job["status"], "queued")
        self.assertEqual(report["summary"]["processed_operation_count"], 0)

    def test_reconciles_terminal_receipt_without_reexecution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "review_status_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-15T12:00:00Z")
            worker = queue_module.HostedManagedOperationWorker(
                queue,
                SuccessfulExecutor(),
                worker_id="previous-window-worker",
            )
            previous_receipt = worker.run_once(
                now_epoch=101,
                now_iso="2026-07-15T12:00:01Z",
            )

            report = self.run_window(queue, request["request_id"])
            job = queue.get(request["request_id"])
            queue.close()

        self.assertEqual(previous_receipt["status"], "succeeded")
        self.assertEqual(
            report["summary"]["status"],
            "bounded_worker_window_completed",
        )
        self.assertTrue(report["execution"]["reconciled_existing_completion"])
        self.assertFalse(report["execution"]["operation_processed"])
        self.assertEqual(job["attempt"], 1)

    def test_expanded_deployment_allowlist_blocks_before_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "review_status_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-15T12:00:00Z")

            report = self.run_window(
                queue,
                request["request_id"],
                allowlist=frozenset(
                    {"review_status_execute", "promotion_execute_dry_run"}
                ),
            )
            job = queue.get(request["request_id"])
            queue.close()

        self.assertIn(
            "deployment_allowlist_not_exact_window_scope",
            report["diagnostics"],
        )
        self.assertEqual(job["status"], "queued")

    def test_terminal_failure_stops_worker_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "review_status_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-15T12:00:00Z")

            report = self.run_window(
                queue,
                request["request_id"],
                executor=TerminalExecutor("timed_out"),
            )
            snapshot = queue.operational_snapshot()
            queue.close()

        self.assertIn("operation_timed_out", report["diagnostics"])
        self.assertTrue(report["summary"]["one_shot_cycle_complete"])
        self.assertEqual(snapshot["active_lock_count"], 0)
        self.assertEqual(snapshot["active_jobs"], [])

    def test_invalid_authoritative_report_digest_fails_queue_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "review_status_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-15T12:00:00Z")

            with self.assertRaisesRegex(
                queue_module.QueueContractError,
                "invalid digest",
            ):
                self.run_window(
                    queue,
                    request["request_id"],
                    executor=InvalidOutputExecutor(),
                )
            queue.close()

    def test_report_materialization_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = window_module.report_path(root, "window-20260715t120000z")
            request_id = (
                "managed-operation://demo-workspace/review_status_execute/"
                + "1" * 24
            )
            report = {
                "artifact_kind": window_module.REPORT_ARTIFACT_KIND,
                "schema_version": 1,
                "contract_ref": window_module.REPORT_CONTRACT_REF,
                "window_id": "window-20260715t120000z",
                "request": {"request_id": request_id},
                "policy": {"sha256": window_module.policy_sha256(self.policy())},
                "summary": {
                    "status": "bounded_worker_window_blocked",
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
            loaded = window_module.load_existing_report(
                path,
                window_id="window-20260715t120000z",
                expected_request_id=request_id,
                expected_policy_sha256=window_module.policy_sha256(self.policy()),
            )
            with self.assertRaisesRegex(
                window_module.WorkerWindowError,
                "already exists",
            ):
                window_module.write_report(path, report)
            with self.assertRaisesRegex(
                window_module.WorkerWindowError,
                "violates its contract",
            ):
                window_module.load_existing_report(
                    path,
                    window_id="window-20260715t120000z",
                    expected_request_id=request_id,
                    expected_policy_sha256="2" * 64,
                )

        self.assertEqual(loaded, report)

    def test_existing_report_rejects_authority_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            window_id = "window-20260715t120000z"
            path = window_module.report_path(root, window_id)
            request_id = (
                "managed-operation://demo-workspace/review_status_execute/"
                + "1" * 24
            )
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            report = self.run_window(queue, request_id)
            queue.close()
            report["window_id"] = window_id
            report["request"]["request_id"] = request_id
            report["authority_boundary"]["may_keep_worker_running"] = True
            window_module.write_report(path, report)

            with self.assertRaisesRegex(
                window_module.WorkerWindowError,
                "violates its contract",
            ):
                window_module.load_existing_report(
                    path,
                    window_id=window_id,
                    expected_request_id=request_id,
                    expected_policy_sha256=window_module.policy_sha256(self.policy()),
                )

    def test_platform_cli_materializes_blocked_missing_request_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_root = root / "artifacts"
            state_dir = root / "state"
            specgraph_dir = root / "SpecGraph"
            for path in (artifact_root, state_dir, specgraph_dir):
                path.mkdir()
            (specgraph_dir / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
            request_id = (
                "managed-operation://demo-workspace/review_status_execute/"
                + "1" * 24
            )
            window_id = "window-20260715t120000z"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "platform.py"),
                    "managed-operation",
                    "worker-window",
                    "--database",
                    str(root / "queue.sqlite3"),
                    "--artifact-root",
                    str(artifact_root),
                    "--state-dir",
                    str(state_dir),
                    "--specgraph-dir",
                    str(specgraph_dir),
                    "--worker-id",
                    "bounded-worker-test",
                    "--expected-request-id",
                    request_id,
                    "--window-id",
                    window_id,
                    "--policy",
                    str(POLICY_PATH.resolve()),
                    "--operation-allowlist",
                    "review_status_execute",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            report_file = window_module.report_path(artifact_root, window_id)
            report = json.loads(report_file.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(
            report["summary"]["status"],
            "bounded_worker_window_blocked",
        )
        self.assertIn("expected_request_missing", report["diagnostics"])


if __name__ == "__main__":
    unittest.main()
