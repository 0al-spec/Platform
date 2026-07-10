from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import hosted_managed_operation_postgres as postgres_module
import hosted_managed_operation_queue as queue_module
from tests.test_hosted_managed_operation_queue import SuccessfulExecutor, request_for


class PostgreSQLManagedOperationQueueTests(unittest.TestCase):
    def test_rejects_non_postgresql_url_before_loading_driver(self) -> None:
        with self.assertRaises(ValueError):
            postgres_module.PostgreSQLManagedOperationQueue("/tmp/queue.sqlite3")

    @unittest.skipUnless(
        os.environ.get("PLATFORM_TEST_POSTGRES_URL"),
        "set PLATFORM_TEST_POSTGRES_URL for PostgreSQL queue integration",
    )
    def test_real_postgresql_queue_lifecycle(self) -> None:
        database_url = os.environ["PLATFORM_TEST_POSTGRES_URL"]
        queue = postgres_module.PostgreSQLManagedOperationQueue(database_url)
        try:
            with queue.connection.cursor() as cursor:
                cursor.execute("TRUNCATE managed_operation_events, managed_operation_locks, managed_operation_jobs RESTART IDENTITY CASCADE")
            with tempfile.TemporaryDirectory() as temp_dir:
                request = request_for(Path(temp_dir), "review_status_execute")
                first = queue.enqueue(
                    request,
                    now_epoch=100,
                    now_iso="2026-07-10T00:00:00Z",
                )
                second = queue.enqueue(
                    request,
                    now_epoch=101,
                    now_iso="2026-07-10T00:00:01Z",
                )
                worker = queue_module.HostedManagedOperationWorker(
                    queue,
                    SuccessfulExecutor(),
                    worker_id="postgres-worker-a",
                )
                receipt = worker.run_once(
                    now_epoch=102,
                    now_iso="2026-07-10T00:00:02Z",
                )
                job = queue.get(request["request_id"])
                events = queue.events(request["request_id"])
        finally:
            queue.close()

        self.assertEqual(first, second)
        self.assertEqual(receipt["status"], "succeeded")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(
            [event["status"] for event in events],
            ["queued", "leased", "running", "succeeded"],
        )

    @unittest.skipUnless(
        os.environ.get("PLATFORM_TEST_POSTGRES_URL"),
        "set PLATFORM_TEST_POSTGRES_URL for PostgreSQL queue integration",
    )
    def test_workspace_lock_is_shared_across_postgresql_connections(self) -> None:
        database_url = os.environ["PLATFORM_TEST_POSTGRES_URL"]
        first_queue = postgres_module.PostgreSQLManagedOperationQueue(database_url)
        second_queue = postgres_module.PostgreSQLManagedOperationQueue(database_url)
        try:
            with first_queue.connection.cursor() as cursor:
                cursor.execute(
                    "TRUNCATE managed_operation_events, managed_operation_locks, "
                    "managed_operation_jobs RESTART IDENTITY CASCADE"
                )
            with tempfile.TemporaryDirectory() as temp_dir:
                temp = Path(temp_dir)
                first_request = request_for(temp, "review_status_execute")
                second_request = request_for(temp, "repair_rerun_publish")
                first_queue.enqueue(
                    first_request,
                    now_epoch=100,
                    now_iso="2026-07-10T00:00:00Z",
                )
                first_queue.enqueue(
                    second_request,
                    now_epoch=100,
                    now_iso="2026-07-10T00:00:00Z",
                )
                leased = first_queue.lease_next(
                    worker_id="postgres-worker-a",
                    now_epoch=101,
                    now_iso="2026-07-10T00:00:01Z",
                    lease_seconds=30,
                )
                blocked = second_queue.lease_next(
                    worker_id="postgres-worker-b",
                    now_epoch=102,
                    now_iso="2026-07-10T00:00:02Z",
                    lease_seconds=30,
                )
        finally:
            first_queue.close()
            second_queue.close()

        self.assertIsNotNone(leased)
        self.assertIsNone(blocked)
