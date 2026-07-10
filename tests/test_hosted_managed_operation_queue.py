from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import hosted_managed_operation_queue as queue_module
import hosted_managed_operations as contracts


def ready_binding(workspace_id: str = "pantry-control") -> dict[str, object]:
    return {
        "artifact_kind": "platform_product_workspace_binding",
        "schema_version": 1,
        "contract_ref": "platform.product-workspace.binding.v1",
        "binding_id": f"product-workspace-binding://{workspace_id}",
        "binding_revision_sha256": "1" * 64,
        "status": "ready",
        "identity": {"workspace_id": workspace_id, "route": f"/{workspace_id}"},
    }


def request_for(
    temp: Path,
    operation_id: str,
    *,
    workspace_id: str = "pantry-control",
    confirmation: bool = False,
) -> dict:
    definition = contracts.operation_by_id(operation_id)
    assert definition is not None
    inputs = {}
    for index, ref in enumerate(definition.input_refs):
        if ref in definition.conditional_input_refs:
            continue
        path = temp / f"{operation_id}-{index}.json"
        path.write_text(
            json.dumps({"artifact_kind": f"test_{operation_id}_{index}"}),
            encoding="utf-8",
        )
        inputs[ref] = path
    return contracts.build_request(
        operation_id=operation_id,
        workspace_binding=ready_binding(workspace_id),
        workspace_binding_ref="runs/platform_product_workspace_initialization_execution_report.json",
        workspace_binding_source_sha256="2" * 64,
        inputs=inputs,
        generated_at="2026-07-10T00:00:00Z",
        confirmation_ref="specspace-state://promotion-review-confirmation.json"
        if confirmation
        else None,
        confirmation_sha256="3" * 64 if confirmation else None,
    )


class SuccessfulExecutor:
    def execute(
        self, leased: queue_module.LeasedOperation
    ) -> queue_module.ExecutionResult:
        return queue_module.ExecutionResult(
            status="succeeded",
            output_reports=tuple(
                {"logical_ref": ref, "sha256": "9" * 64}
                for ref in leased.request["expected_output_reports"]
            ),
        )


class FailingExecutor:
    def execute(self, leased: queue_module.LeasedOperation) -> queue_module.ExecutionResult:
        raise RuntimeError("private executor detail")


class HostedManagedOperationQueueTests(unittest.TestCase):
    def test_enqueue_is_idempotent_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            request = request_for(temp, "review_status_execute")
            database = temp / "queue.sqlite3"
            queue = queue_module.SQLiteManagedOperationQueue(database)
            first = queue.enqueue(
                request,
                now_epoch=100.0,
                now_iso="2026-07-10T00:00:00Z",
            )
            second = queue.enqueue(
                request,
                now_epoch=101.0,
                now_iso="2026-07-10T00:00:01Z",
            )
            queue.close()

            reopened = queue_module.SQLiteManagedOperationQueue(database)
            job = reopened.get(request["request_id"])
            events = reopened.events(request["request_id"])
            reopened.close()

        self.assertEqual(first, second)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "queued")

    def test_workspace_lock_prevents_parallel_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            first_request = request_for(temp, "review_status_execute")
            second_request = request_for(temp, "repair_rerun_publish")
            queue.enqueue(first_request, now_epoch=100, now_iso="2026-07-10T00:00:00Z")
            queue.enqueue(second_request, now_epoch=100, now_iso="2026-07-10T00:00:00Z")

            leased = queue.lease_next(
                worker_id="worker-a",
                now_epoch=101,
                now_iso="2026-07-10T00:00:01Z",
                lease_seconds=30,
            )
            blocked = queue.lease_next(
                worker_id="worker-b",
                now_epoch=102,
                now_iso="2026-07-10T00:00:02Z",
                lease_seconds=30,
            )
            queue.close()

        self.assertIsNotNone(leased)
        self.assertIsNone(blocked)

    def test_worker_completes_only_with_all_expected_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "review_status_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-10T00:00:00Z")
            worker = queue_module.HostedManagedOperationWorker(
                queue,
                SuccessfulExecutor(),
                worker_id="worker-a",
            )

            receipt = worker.run_once(
                now_epoch=101,
                now_iso="2026-07-10T00:00:01Z",
            )
            job = queue.get(request["request_id"])
            queue.close()

        self.assertEqual(receipt["status"], "succeeded")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["attempt"], 1)

    def test_wrong_output_report_cannot_complete_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "review_status_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-10T00:00:00Z")
            leased = queue.lease_next(
                worker_id="worker-a",
                now_epoch=101,
                now_iso="2026-07-10T00:00:01Z",
                lease_seconds=30,
            )
            assert leased is not None

            with self.assertRaises(queue_module.QueueContractError):
                queue.complete(
                    leased,
                    queue_module.ExecutionResult(
                        status="succeeded",
                        output_reports=(
                            {"logical_ref": "runs/foreign.json", "sha256": "9" * 64},
                        ),
                    ),
                    now_epoch=102,
                    now_iso="2026-07-10T00:00:02Z",
                )
            job = queue.get(request["request_id"])
            queue.close()

        self.assertEqual(job["status"], "leased")

    def test_worker_failure_is_bounded_and_does_not_expose_exception_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "review_status_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-10T00:00:00Z")
            worker = queue_module.HostedManagedOperationWorker(
                queue,
                FailingExecutor(),
                worker_id="worker-a",
            )

            receipt = worker.run_once(
                now_epoch=101,
                now_iso="2026-07-10T00:00:01Z",
            )
            queue.close()

        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["diagnostics"], ["executor failed: RuntimeError"])
        self.assertNotIn("private executor detail", json.dumps(receipt))

    def test_dynamic_output_report_template_accepts_scoped_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "repair_rerun_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-10T00:00:00Z")
            leased = queue.lease_next(
                worker_id="worker-a",
                now_epoch=101,
                now_iso="2026-07-10T00:00:01Z",
                lease_seconds=30,
            )
            assert leased is not None

            receipt = queue.complete(
                leased,
                queue_module.ExecutionResult(
                    status="succeeded",
                    output_reports=(
                        {
                            "logical_ref": (
                                "runs/managed_repair_rerun_plans/request-42."
                                "platform_product_repair_rerun_execution_plan.json"
                            ),
                            "sha256": "8" * 64,
                        },
                        {
                            "logical_ref": "runs/platform_product_repair_rerun_execution_report.json",
                            "sha256": "9" * 64,
                        },
                    ),
                ),
                now_epoch=102,
                now_iso="2026-07-10T00:00:02Z",
            )
            queue.close()

        self.assertEqual(receipt["status"], "succeeded")

    def test_expired_read_only_lease_is_requeued(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "review_status_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-10T00:00:00Z")
            queue.lease_next(
                worker_id="worker-a",
                now_epoch=101,
                now_iso="2026-07-10T00:00:01Z",
                lease_seconds=10,
            )

            receipts = queue.recover_expired(
                now_epoch=112,
                now_iso="2026-07-10T00:00:12Z",
            )
            leased_again = queue.lease_next(
                worker_id="worker-b",
                now_epoch=113,
                now_iso="2026-07-10T00:00:13Z",
                lease_seconds=10,
            )
            queue.close()

        self.assertEqual(receipts[0]["status"], "queued")
        self.assertEqual(leased_again.attempt, 2)

    def test_expired_consume_on_attempt_operation_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")
            request = request_for(temp, "real_idea_intake_execute")
            queue.enqueue(request, now_epoch=100, now_iso="2026-07-10T00:00:00Z")
            queue.lease_next(
                worker_id="worker-a",
                now_epoch=101,
                now_iso="2026-07-10T00:00:01Z",
                lease_seconds=10,
            )

            receipts = queue.recover_expired(
                now_epoch=112,
                now_iso="2026-07-10T00:00:12Z",
            )
            job = queue.get(request["request_id"])
            queue.close()

        self.assertEqual(receipts[0]["status"], "quarantined")
        self.assertEqual(job["status"], "quarantined")

    def test_queue_rejects_tampered_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request = request_for(Path(temp_dir), "review_status_execute")
            request["raw_idea"] = "private"
            queue = queue_module.SQLiteManagedOperationQueue(":memory:")

            with self.assertRaises(queue_module.QueueContractError):
                queue.enqueue(
                    request,
                    now_epoch=100,
                    now_iso="2026-07-10T00:00:00Z",
                )
            queue.close()

    def test_cli_initializes_enqueues_and_reports_transport_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            request = request_for(temp, "review_status_execute")
            request_path = temp / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            database = temp / "queue.sqlite3"
            cli = REPO_ROOT / "scripts" / "platform.py"

            initialized = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "managed-operation",
                    "queue-init",
                    "--database",
                    str(database),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            enqueued = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "managed-operation",
                    "enqueue",
                    "--database",
                    str(database),
                    "--request",
                    str(request_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            status = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "managed-operation",
                    "status",
                    "--database",
                    str(database),
                    "--request-id",
                    request["request_id"],
                    "--include-events",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(enqueued.returncode, 0, enqueued.stderr)
        self.assertEqual(status.returncode, 0, status.stderr)
        payload = json.loads(status.stdout)
        self.assertEqual(payload["summary"]["status"], "queued")
        self.assertFalse(
            payload["authority_boundary"]["queue_status_is_lifecycle_evidence"]
        )
        self.assertEqual(len(payload["events"]), 1)


if __name__ == "__main__":
    unittest.main()
