from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import specspace_state_postgres as postgres_module
import specspace_state_service as service_module
import specspace_state_store as store_module


WORKSPACE_ID = "postgres-state-workspace"
RECORD_KEY = "real_idea_entry_requests.json"
CONFIRMATION_KEY = (
    "confirmations/postgres-state-workspace/promotion_review_execute/"
    "0123456789abcdef0123456789abcdef.json"
)


@unittest.skipUnless(
    os.environ.get("PLATFORM_TEST_POSTGRES_URL"),
    "set PLATFORM_TEST_POSTGRES_URL for PostgreSQL state integration",
)
class PostgreSQLSpecSpaceStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_url = os.environ["PLATFORM_TEST_POSTGRES_URL"]
        store = postgres_module.PostgreSQLSpecSpaceStateStore(self.database_url)
        try:
            with store.connection.cursor() as cursor:
                cursor.execute(
                    "TRUNCATE specspace_state_versions, specspace_state_records"
                )
        finally:
            store.close()

    def test_postgresql_state_lifecycle_and_history(self) -> None:
        store = postgres_module.PostgreSQLSpecSpaceStateStore(self.database_url)
        try:
            first = store.mutate(
                store_module.StateMutation(
                    workspace_id=WORKSPACE_ID,
                    record_key=RECORD_KEY,
                    expected_revision=0,
                    idempotency_key="postgres-state:lifecycle:0001",
                    lifecycle_state="active",
                    content={"requests": [{"workspace_id": WORKSPACE_ID}]},
                ),
                now_iso="2026-07-18T00:00:00Z",
            )
            consumed = store.mutate(
                store_module.StateMutation(
                    workspace_id=WORKSPACE_ID,
                    record_key=RECORD_KEY,
                    expected_revision=1,
                    idempotency_key="postgres-state:lifecycle:0002",
                    lifecycle_state="consumed",
                    content={"requests": [{"workspace_id": WORKSPACE_ID, "status": "consumed"}]},
                ),
                now_iso="2026-07-18T00:00:01Z",
            )
            history = store.history(WORKSPACE_ID, RECORD_KEY)
        finally:
            store.close()

        self.assertEqual(first["revision"], 1)
        self.assertEqual(consumed["revision"], 2)
        self.assertEqual(consumed["consumed_at"], "2026-07-18T00:00:01Z")
        self.assertEqual([item["revision"] for item in history], [2, 1])

    def test_concurrent_cas_allows_only_one_writer(self) -> None:
        seed = postgres_module.PostgreSQLSpecSpaceStateStore(self.database_url)
        try:
            seed.mutate(
                store_module.StateMutation(
                    workspace_id=WORKSPACE_ID,
                    record_key=RECORD_KEY,
                    expected_revision=0,
                    idempotency_key="postgres-state:concurrency:seed",
                    lifecycle_state="active",
                    content={"requests": []},
                ),
                now_iso="2026-07-18T00:00:00Z",
            )
        finally:
            seed.close()

        def write(index: int) -> str:
            store = postgres_module.PostgreSQLSpecSpaceStateStore(
                self.database_url
            )
            try:
                store.mutate(
                    store_module.StateMutation(
                        workspace_id=WORKSPACE_ID,
                        record_key=RECORD_KEY,
                        expected_revision=1,
                        idempotency_key=f"postgres-state:concurrency:{index:04d}",
                        lifecycle_state="active",
                        content={"requests": [{"writer": index}]},
                    ),
                    now_iso=f"2026-07-18T00:00:0{index + 1}Z",
                )
                return "written"
            except store_module.StateConflictError:
                return "conflict"
            finally:
                store.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = sorted(executor.map(write, (1, 2)))

        self.assertEqual(results, ["conflict", "written"])

    def test_concurrent_confirmation_consumption_allows_one_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def service(index: int) -> service_module.SpecSpaceStateService:
                return service_module.SpecSpaceStateService(
                    store_factory=lambda: (
                        postgres_module.PostgreSQLSpecSpaceStateStore(
                            self.database_url
                        )
                    ),
                    adapter="postgresql",
                    mirror_root=root / f"mirror-{index}",
                    now_iso=lambda: "2026-08-01T00:05:00Z",
                )

            created = service(0).mutate(
                {
                    "workspace_id": WORKSPACE_ID,
                    "record_key": CONFIRMATION_KEY,
                    "expected_revision": 0,
                    "idempotency_key": "confirmation-create:postgres:0001",
                    "lifecycle_state": "active",
                    "content": {
                        "artifact_kind": (
                            "platform_hosted_promotion_review_confirmation"
                        ),
                        "schema_version": 1,
                        "workspace_id": WORKSPACE_ID,
                        "operation_id": "promotion_review_execute",
                        "status": "ready",
                        "confirmed": True,
                    },
                }
            )

            def consume(index: int) -> str:
                try:
                    service(index).consume_confirmation(
                        {
                            "workspace_id": WORKSPACE_ID,
                            "record_key": CONFIRMATION_KEY,
                            "expected_revision": 1,
                            "expected_content_sha256": created["record"][
                                "content_sha256"
                            ],
                            "operation_id": "promotion_review_execute",
                            "request_identity_sha256": str(index) * 64,
                        }
                    )
                    return "consumed"
                except service_module.StateServiceError:
                    return "conflict"

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = sorted(executor.map(consume, (1, 2)))

        self.assertEqual(results, ["conflict", "consumed"])


if __name__ == "__main__":
    unittest.main()
