from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import hosted_managed_operation_canary as canary_module
import hosted_managed_operation_executor as executor_module
import hosted_managed_operation_postgres as postgres_module
import hosted_managed_operation_queue as queue_module
import hosted_managed_operation_service as service_module
import hosted_managed_runtime_backup as backup_module
import hosted_managed_production_signoff as signoff_module
import specspace_state_postgres as state_postgres_module
import specspace_state_store as state_store_module
from tests.test_hosted_managed_operation_executor import (
    ExecutorFixture,
    RecordingRunner,
)
from tests.test_hosted_managed_operation_queue import SuccessfulExecutor, request_for


TOKEN = "hosted-postgres-test-token-0123456789abcdef"


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
    def test_real_postgresql_backup_and_restore_smoke(self) -> None:
        database_url = os.environ["PLATFORM_TEST_POSTGRES_URL"]
        queue = postgres_module.PostgreSQLManagedOperationQueue(database_url)
        psycopg, sql = backup_module._driver()
        state_database_name = f"specspace_state_backup_test_{os.getpid()}"
        admin_url = backup_module._replace_database(database_url, "postgres")
        state_database_url = backup_module._replace_database(
            database_url,
            state_database_name,
        )
        state_database_created = False
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("CREATE DATABASE {}").format(
                            sql.Identifier(state_database_name)
                        )
                    )
                    state_database_created = True
            state_store = (
                state_postgres_module.PostgreSQLSpecSpaceStateStore(
                    state_database_url
                )
            )
            try:
                state_store.mutate(
                    state_store_module.StateMutation(
                        workspace_id="workspace-a",
                        record_key="real_idea_entry_requests.json",
                        expected_revision=0,
                        idempotency_key="postgres-backup:state-write:0001",
                        lifecycle_state="active",
                        content={
                            "artifact_kind": (
                                "specspace_real_idea_entry_requests"
                            ),
                            "requests": [],
                            "workspace_id": "workspace-a",
                        },
                    ),
                    now_iso="2026-07-10T00:00:00Z",
                )
            finally:
                state_store.close()
            with queue.connection.cursor() as cursor:
                cursor.execute(
                    "TRUNCATE managed_operation_events, managed_operation_locks, "
                    "managed_operation_jobs RESTART IDENTITY CASCADE"
                )
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                request = request_for(root, "review_status_execute")
                queue.enqueue(
                    request,
                    now_epoch=100,
                    now_iso="2026-07-10T00:00:00Z",
                )
                worker = queue_module.HostedManagedOperationWorker(
                    queue,
                    SuccessfulExecutor(),
                    worker_id="postgres-backup-worker",
                )
                receipt = worker.run_once(
                    now_epoch=101,
                    now_iso="2026-07-10T00:00:01Z",
                )
                self.assertEqual(receipt["status"], "succeeded")
                artifact_root = root / "specgraph"
                report_dir = artifact_root / "runs" / "workspace-a"
                report_dir.mkdir(parents=True)
                (report_dir / "review-status.json").write_text(
                    '{"ok":true}\n', encoding="utf-8"
                )
                database_url_file = root / "database-url"
                database_url_file.write_text(database_url, encoding="utf-8")
                state_database_url_file = root / "state-database-url"
                state_database_url_file.write_text(
                    state_database_url,
                    encoding="utf-8",
                )
                backup_root = root / "backups"
                backup_root.mkdir()
                backup_report = backup_module.create_backup(
                    database_url_file=database_url_file,
                    state_database_url_file=state_database_url_file,
                    artifact_root=artifact_root,
                    backup_root=backup_root,
                    backup_id="postgres-integration",
                )
                restore_report = backup_module.restore_smoke(
                    database_url_file=database_url_file,
                    state_database_url_file=state_database_url_file,
                    backup_root=backup_root,
                    backup_id="postgres-integration",
                )
                queue_audit_report = signoff_module.queue_audit(database_url_file)
        finally:
            queue.close()
            if state_database_created:
                with psycopg.connect(admin_url, autocommit=True) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                                sql.Identifier(state_database_name)
                            )
                        )

        self.assertTrue(backup_report["ok"])
        self.assertEqual(backup_report["summary"]["artifact_file_count"], 1)
        self.assertEqual(
            backup_report["summary"]["state_database_row_counts"],
            {
                "specspace_state_records": 1,
                "specspace_state_versions": 1,
            },
        )
        self.assertTrue(restore_report["ok"])
        self.assertTrue(
            restore_report["summary"]["state_database_row_counts_verified"]
        )
        self.assertTrue(
            restore_report["summary"]["state_mirror_record_count_verified"]
        )
        self.assertEqual(
            restore_report["summary"]["state_mirror_record_count"],
            1,
        )
        self.assertTrue(
            restore_report["summary"]["temporary_state_mirror_removed"]
        )
        self.assertTrue(restore_report["summary"]["temporary_database_removed"])
        self.assertTrue(queue_audit_report["ok"])

    @unittest.skipUnless(
        os.environ.get("PLATFORM_TEST_POSTGRES_URL"),
        "set PLATFORM_TEST_POSTGRES_URL for PostgreSQL queue integration",
    )
    def test_real_postgresql_canary_http_worker_lifecycle(self) -> None:
        database_url = os.environ["PLATFORM_TEST_POSTGRES_URL"]
        setup_queue = postgres_module.PostgreSQLManagedOperationQueue(database_url)
        try:
            with setup_queue.connection.cursor() as cursor:
                cursor.execute(
                    "TRUNCATE managed_operation_events, managed_operation_locks, "
                    "managed_operation_jobs RESTART IDENTITY CASCADE"
                )
        finally:
            setup_queue.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("review_status_execute")
            allowlist = frozenset({"review_status_execute"})
            service = service_module.HostedManagedOperationService(
                queue_factory=lambda: postgres_module.PostgreSQLManagedOperationQueue(
                    database_url
                ),
                adapter="postgresql",
                resolver=fixture.resolver(),
                now_epoch=lambda: 100.0,
                now_iso=lambda: "2026-07-10T00:00:00Z",
                allowed_operation_ids=allowlist,
            )
            service_health = service.health()
            server = service_module.create_server(
                host="127.0.0.1",
                port=0,
                service=service,
                auth_token=TOKEN,
            )
            server_thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
            )
            server_thread.start()
            stop_worker = threading.Event()

            def process_one() -> None:
                worker_queue = postgres_module.PostgreSQLManagedOperationQueue(
                    database_url
                )
                worker = queue_module.HostedManagedOperationWorker(
                    worker_queue,
                    executor_module.PlatformManagedOperationExecutor(
                        resolver=fixture.resolver(),
                        platform_script=fixture.platform_script,
                        runner=RecordingRunner(),
                    ),
                    worker_id="postgres-canary-worker",
                    allowed_operation_ids=allowlist,
                )
                try:
                    while not stop_worker.is_set():
                        receipt = worker.run_once()
                        if receipt is not None:
                            return
                        time.sleep(0.01)
                finally:
                    worker_queue.close()

            worker_thread = threading.Thread(target=process_one, daemon=True)
            worker_thread.start()
            try:
                report = canary_module.run_canary(
                    request=request,
                    service_url=f"http://127.0.0.1:{server.server_address[1]}",
                    token=TOKEN,
                    poll_interval_seconds=0.01,
                    max_wait_seconds=5,
                    artifact_root=fixture.artifact_root,
                )
            finally:
                stop_worker.set()
                worker_thread.join(timeout=5)
                server.shutdown()
                server_thread.join(timeout=5)
                server.server_close()

        self.assertTrue(report["summary"]["ok"], report["diagnostics"])
        self.assertTrue(service_health["ok"])
        self.assertEqual(service_health["adapter"], "postgresql")
        self.assertEqual(
            service_health["enabled_operation_ids"],
            ["review_status_execute"],
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

    @unittest.skipUnless(
        os.environ.get("PLATFORM_TEST_POSTGRES_URL"),
        "set PLATFORM_TEST_POSTGRES_URL for PostgreSQL queue integration",
    )
    def test_real_postgresql_expected_request_pin_skips_neighbor(self) -> None:
        database_url = os.environ["PLATFORM_TEST_POSTGRES_URL"]
        queue = postgres_module.PostgreSQLManagedOperationQueue(database_url)
        try:
            with queue.connection.cursor() as cursor:
                cursor.execute(
                    "TRUNCATE managed_operation_events, managed_operation_locks, "
                    "managed_operation_jobs RESTART IDENTITY CASCADE"
                )
            with tempfile.TemporaryDirectory() as temp_dir:
                temp = Path(temp_dir)
                first = request_for(temp, "review_status_execute")
                second = request_for(
                    temp,
                    "review_status_execute",
                    workspace_id="postgres-pinned-workspace",
                )
                for request in (first, second):
                    queue.enqueue(
                        request,
                        now_epoch=100,
                        now_iso="2026-07-10T00:00:00Z",
                    )
                worker = queue_module.HostedManagedOperationWorker(
                    queue,
                    SuccessfulExecutor(),
                    worker_id="postgres-pinned-worker",
                    expected_request_id=second["request_id"],
                )
                receipt = worker.run_once(
                    now_epoch=101,
                    now_iso="2026-07-10T00:00:01Z",
                )
                first_job = queue.get(first["request_id"])
                second_job = queue.get(second["request_id"])
                snapshot = queue.operational_snapshot()
        finally:
            queue.close()

        self.assertEqual(receipt["request_ref"], second["request_id"])
        self.assertEqual(first_job["status"], "queued")
        self.assertEqual(second_job["status"], "succeeded")
        self.assertEqual(snapshot["active_lock_count"], 0)

    @unittest.skipUnless(
        os.environ.get("PLATFORM_TEST_POSTGRES_URL"),
        "set PLATFORM_TEST_POSTGRES_URL for PostgreSQL queue integration",
    )
    def test_concurrent_idempotent_enqueue_returns_one_queue_job(self) -> None:
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
                request = request_for(Path(temp_dir), "review_status_execute")
                barrier = threading.Barrier(2)

                def enqueue(queue: object) -> dict[str, object]:
                    barrier.wait(timeout=5)
                    return queue.enqueue(
                        request,
                        now_epoch=100,
                        now_iso="2026-07-10T00:00:00Z",
                    )

                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = (
                        executor.submit(enqueue, first_queue),
                        executor.submit(enqueue, second_queue),
                    )
                    receipts = [future.result(timeout=10) for future in futures]
                retry_request = {**request, "generated_at": "2026-07-10T00:00:01Z"}
                retry_receipt = second_queue.enqueue(
                    retry_request,
                    now_epoch=101,
                    now_iso="2026-07-10T00:00:01Z",
                )
                events = first_queue.events(request["request_id"])
        finally:
            first_queue.close()
            second_queue.close()

        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(retry_receipt, receipts[0])
        self.assertEqual([event["status"] for event in events], ["queued"])

    @unittest.skipUnless(
        os.environ.get("PLATFORM_TEST_POSTGRES_URL"),
        "set PLATFORM_TEST_POSTGRES_URL for PostgreSQL queue integration",
    )
    def test_real_postgresql_expired_lease_recovery_respects_replay_policy(self) -> None:
        database_url = os.environ["PLATFORM_TEST_POSTGRES_URL"]
        queue = postgres_module.PostgreSQLManagedOperationQueue(database_url)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp = Path(temp_dir)
                expectations = (
                    ("review_status_execute", "queued"),
                    ("real_idea_intake_execute", "quarantined"),
                )
                for operation_id, expected_status in expectations:
                    with queue.connection.cursor() as cursor:
                        cursor.execute(
                            "TRUNCATE managed_operation_events, managed_operation_locks, "
                            "managed_operation_jobs RESTART IDENTITY CASCADE"
                        )
                    request = request_for(temp, operation_id)
                    queue.enqueue(
                        request,
                        now_epoch=100,
                        now_iso="2026-07-10T00:00:00Z",
                    )
                    queue.lease_next(
                        worker_id="postgres-worker-a",
                        now_epoch=101,
                        now_iso="2026-07-10T00:00:01Z",
                        lease_seconds=10,
                    )

                    receipts = queue.recover_expired(
                        now_epoch=112,
                        now_iso="2026-07-10T00:00:12Z",
                    )
                    job = queue.get(request["request_id"])

                    self.assertEqual(receipts[0]["status"], expected_status)
                    self.assertEqual(job["status"], expected_status)
        finally:
            queue.close()

    @unittest.skipUnless(
        os.environ.get("PLATFORM_TEST_POSTGRES_URL"),
        "set PLATFORM_TEST_POSTGRES_URL for PostgreSQL queue integration",
    )
    def test_real_postgresql_expired_lock_blocks_until_recovery(self) -> None:
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
                first_request = request_for(temp, "real_idea_intake_execute")
                second_request = request_for(temp, "review_status_execute")
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
                first_queue.lease_next(
                    worker_id="postgres-worker-a",
                    now_epoch=101,
                    now_iso="2026-07-10T00:00:01Z",
                    lease_seconds=10,
                )

                blocked = second_queue.lease_next(
                    worker_id="postgres-worker-b",
                    now_epoch=112,
                    now_iso="2026-07-10T00:00:12Z",
                    lease_seconds=10,
                )
                recovered = first_queue.recover_expired(
                    now_epoch=112,
                    now_iso="2026-07-10T00:00:12Z",
                )
                leased_after_recovery = second_queue.lease_next(
                    worker_id="postgres-worker-b",
                    now_epoch=113,
                    now_iso="2026-07-10T00:00:13Z",
                    lease_seconds=10,
                )
        finally:
            first_queue.close()
            second_queue.close()

        self.assertIsNone(blocked)
        self.assertEqual(recovered[0]["status"], "quarantined")
        self.assertEqual(leased_after_recovery.request_id, second_request["request_id"])
