from __future__ import annotations

from http import HTTPStatus
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import hosted_managed_operation_executor as executor_module
import specspace_state_service as service_module
import specspace_state_store as store_module


TOKEN = "specspace-state-test-token-0123456789abcdef"
CONFIRMATION_TOKEN = "confirmation-consumer-test-token-0123456789abcdef"
WORKSPACE_ID = "workspace-a"
RECORD_KEY = "real_idea_entry_requests.json"
CONFIRMATION_KEY = (
    "confirmations/workspace-a/promotion_review_execute/"
    "0123456789abcdef0123456789abcdef.json"
)


def mutation(
    *,
    expected_revision: int = 0,
    idempotency_key: str = "state-write:workspace-a:0001",
    content: dict | None = None,
    lifecycle_state: str = "active",
) -> store_module.StateMutation:
    return store_module.StateMutation(
        workspace_id=WORKSPACE_ID,
        record_key=RECORD_KEY,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        lifecycle_state=lifecycle_state,
        content=content
        or {
            "artifact_kind": "specspace_real_idea_entry_request_state",
            "requests": [{"workspace_id": WORKSPACE_ID, "raw_idea": "private"}],
        },
    )


def confirmation_content() -> dict:
    return {
        "artifact_kind": "platform_hosted_promotion_review_confirmation",
        "schema_version": 1,
        "contract_ref": "platform.hosted-promotion-review-confirmation.v1",
        "confirmation_id": (
            "confirmation://workspace-a/promotion_review_execute/"
            "0123456789abcdef0123456789abcdef"
        ),
        "workspace_id": WORKSPACE_ID,
        "operation_id": "promotion_review_execute",
        "operator_ref": "operator://specspace-basic/session-a",
        "status": "ready",
        "confirmed": True,
    }


class SpecSpaceStateStoreTests(unittest.TestCase):
    def test_sqlite_store_enforces_cas_idempotency_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = store_module.SQLiteSpecSpaceStateStore(
                Path(temp_dir) / "state.sqlite3"
            )
            try:
                first = store.mutate(
                    mutation(),
                    now_iso="2026-07-18T00:00:00Z",
                )
                replay = store.mutate(
                    mutation(),
                    now_iso="2026-07-18T00:00:01Z",
                )
                second = store.mutate(
                    mutation(
                        expected_revision=1,
                        idempotency_key="state-write:workspace-a:0002",
                        content={
                            "artifact_kind": "specspace_real_idea_entry_request_state",
                            "requests": [
                                {
                                    "workspace_id": WORKSPACE_ID,
                                    "raw_idea": "private updated",
                                }
                            ],
                        },
                    ),
                    now_iso="2026-07-18T00:00:02Z",
                )
                history = store.history(WORKSPACE_ID, RECORD_KEY)
                with self.assertRaises(store_module.StateConflictError):
                    store.mutate(
                        mutation(
                            expected_revision=1,
                            idempotency_key="state-write:workspace-a:0003",
                        ),
                        now_iso="2026-07-18T00:00:03Z",
                    )
            finally:
                store.close()

        self.assertEqual(first["revision"], 1)
        self.assertEqual(replay["revision"], 1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual([item["revision"] for item in history], [2, 1])

    def test_idempotency_key_cannot_be_reused_for_other_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = store_module.SQLiteSpecSpaceStateStore(
                Path(temp_dir) / "state.sqlite3"
            )
            try:
                store.mutate(
                    mutation(),
                    now_iso="2026-07-18T00:00:00Z",
                )
                with self.assertRaises(store_module.StateConflictError):
                    store.mutate(
                        mutation(
                            idempotency_key="state-write:workspace-a:0001",
                            content={"requests": []},
                        ),
                        now_iso="2026-07-18T00:00:01Z",
                    )
            finally:
                store.close()

    def test_record_key_allowlist_rejects_cross_workspace_confirmation(self) -> None:
        self.assertEqual(
            store_module.validate_record_key(
                "confirmations/workspace-a/promotion_review_execute/confirm.json",
                workspace_id=WORKSPACE_ID,
            ),
            "confirmations/workspace-a/promotion_review_execute/confirm.json",
        )
        with self.assertRaises(store_module.StateStoreError):
            store_module.validate_record_key(
                "confirmations/workspace-b/promotion_review_execute/confirm.json",
                workspace_id=WORKSPACE_ID,
            )

    def test_retention_keeps_bounded_latest_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = store_module.SQLiteSpecSpaceStateStore(
                Path(temp_dir) / "state.sqlite3"
            )
            try:
                for index in range(4):
                    store.mutate(
                        mutation(
                            expected_revision=index,
                            idempotency_key=f"state-write:workspace-a:{index:04d}",
                            content={"requests": [{"workspace_id": WORKSPACE_ID, "n": index}]},
                        ),
                        now_iso=f"2026-07-18T00:00:0{index}Z",
                    )
                deleted = store.prune_versions(retain_latest=2)
                history = store.history(WORKSPACE_ID, RECORD_KEY)
            finally:
                store.close()

        self.assertEqual(deleted, 2)
        self.assertEqual([item["revision"] for item in history], [4, 3])


class SpecSpaceStateServiceTests(unittest.TestCase):
    def build_service(
        self,
        root: Path,
    ) -> service_module.SpecSpaceStateService:
        database = root / "state.sqlite3"
        return service_module.SpecSpaceStateService(
            store_factory=lambda: store_module.SQLiteSpecSpaceStateStore(database),
            adapter="sqlite",
            mirror_root=root / "mirror",
            now_iso=lambda: "2026-07-18T00:00:00Z",
        )

    def request(
        self,
        base_url: str,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        authorized: bool = True,
        token: str = TOKEN,
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        with urllib.request.urlopen(
            urllib.request.Request(
                f"{base_url}{path}",
                data=data,
                headers=headers,
                method=method,
            )
        ) as response:
            return json.loads(response.read())

    def test_startup_rebuilds_mirror_from_database_and_removes_stale_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "state.sqlite3"
            store = store_module.SQLiteSpecSpaceStateStore(database)
            try:
                record = store.mutate(
                    mutation(),
                    now_iso="2026-07-18T00:00:00Z",
                )
            finally:
                store.close()
            stale = root / "mirror" / "foreign" / RECORD_KEY
            stale.parent.mkdir(parents=True)
            stale.write_text('{"stale":true}\n', encoding="utf-8")

            service = self.build_service(root)
            mirrored = json.loads(
                (
                    root
                    / "mirror"
                    / WORKSPACE_ID
                    / RECORD_KEY
                ).read_text(encoding="utf-8")
            )
            stale_exists = stale.exists()
            mirror_summary = service.mirror_summary

        self.assertEqual(
            store_module.content_sha256(mirrored),
            record["content_sha256"],
        )
        self.assertFalse(stale_exists)
        self.assertEqual(
            mirror_summary,
            {
                "database_record_count": 1,
                "materialized_record_count": 1,
            },
        )

    def test_health_uses_cached_mirror_summary_without_waiting_for_mutation_lock(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            list_record_calls = 0

            class CountingSQLiteStore(store_module.SQLiteSpecSpaceStateStore):
                def list_records(
                    self,
                    *,
                    workspace_id: str | None = None,
                    include_deleted: bool = False,
                ) -> list[dict]:
                    nonlocal list_record_calls
                    list_record_calls += 1
                    return super().list_records(
                        workspace_id=workspace_id,
                        include_deleted=include_deleted,
                    )

            database = root / "state.sqlite3"
            service = service_module.SpecSpaceStateService(
                store_factory=lambda: CountingSQLiteStore(database),
                adapter="sqlite",
                mirror_root=root / "mirror",
                now_iso=lambda: "2026-07-18T00:00:00Z",
            )
            startup_list_record_calls = list_record_calls
            health_result: list[dict] = []
            with service._mirror_lock:
                thread = threading.Thread(
                    target=lambda: health_result.append(service.health()),
                    daemon=True,
                )
                thread.start()
                thread.join(timeout=2)
                health_completed_while_mutation_lock_held = not thread.is_alive()
            thread.join(timeout=2)

        self.assertEqual(startup_list_record_calls, 1)
        self.assertEqual(list_record_calls, startup_list_record_calls)
        self.assertTrue(health_completed_while_mutation_lock_held)
        self.assertTrue(health_result[0]["ok"])
        self.assertEqual(health_result[0]["mirror_record_count"], 0)

    def test_materialization_failure_marks_cached_mirror_unready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = self.build_service(root)

            def fail_materialization(_record: dict) -> None:
                raise RuntimeError("materialization failed")

            service._materialize = fail_materialization
            with self.assertRaisesRegex(RuntimeError, "materialization failed"):
                service.mutate(
                    {
                        "workspace_id": WORKSPACE_ID,
                        "record_key": RECORD_KEY,
                        "expected_revision": 0,
                        "idempotency_key": "state-write:workspace-a:failure-0001",
                        "lifecycle_state": "active",
                        "content": mutation().content,
                    }
                )
            health = service.health()

        self.assertFalse(health["ok"])
        self.assertFalse(health["mirror_ready"])

    def test_http_service_persists_private_record_and_materializes_scoped_mirror(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            server = service_module.create_server(
                host="127.0.0.1",
                port=0,
                service=self.build_service(root),
                auth_token=TOKEN,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            payload = {
                "workspace_id": WORKSPACE_ID,
                "record_key": RECORD_KEY,
                "expected_revision": 0,
                "idempotency_key": "state-write:workspace-a:http-0001",
                "lifecycle_state": "active",
                "content": mutation().content,
                "content_sha256": store_module.content_sha256(mutation().content),
            }
            try:
                report = self.request(
                    base_url,
                    "/v1/specspace-state/record",
                    method="PUT",
                    payload=payload,
                )
                query = urllib.parse.urlencode(
                    {"workspace_id": WORKSPACE_ID, "record_key": RECORD_KEY}
                )
                record = self.request(
                    base_url,
                    f"/v1/specspace-state/record?{query}",
                )
                health = self.request(
                    base_url,
                    "/v1/health",
                    authorized=False,
                )
                mirror = root / "mirror" / WORKSPACE_ID / RECORD_KEY
                mirror_payload = json.loads(mirror.read_text(encoding="utf-8"))
                deleted = self.request(
                    base_url,
                    "/v1/specspace-state/record",
                    method="DELETE",
                    payload={
                        "workspace_id": WORKSPACE_ID,
                        "record_key": RECORD_KEY,
                        "expected_revision": 1,
                        "idempotency_key": "state-delete:workspace-a:http-0001",
                    },
                )
                deleted_health = self.request(
                    base_url,
                    "/v1/health",
                    authorized=False,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            mirror = root / "mirror" / WORKSPACE_ID / RECORD_KEY
            mirror_exists_after_delete = mirror.exists()

        self.assertTrue(report["ok"])
        self.assertEqual(report["record"]["revision"], 1)
        self.assertEqual(record["record"]["content"], mutation().content)
        self.assertEqual(mirror_payload, mutation().content)
        self.assertTrue(health["ok"])
        self.assertEqual(health["mirror_record_count"], 1)
        self.assertTrue(deleted["ok"])
        self.assertEqual(deleted["record"]["revision"], 2)
        self.assertTrue(deleted_health["ok"])
        self.assertEqual(deleted_health["mirror_record_count"], 0)
        self.assertFalse(mirror_exists_after_delete)
        self.assertNotIn("raw_idea", json.dumps(health))

    def test_http_service_requires_auth_and_reports_cas_conflict_without_content(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            server = service_module.create_server(
                host="127.0.0.1",
                port=0,
                service=self.build_service(root),
                auth_token=TOKEN,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            payload = {
                "workspace_id": WORKSPACE_ID,
                "record_key": RECORD_KEY,
                "expected_revision": 0,
                "idempotency_key": "state-write:workspace-a:http-0001",
                "lifecycle_state": "active",
                "content": mutation().content,
            }
            try:
                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    self.request(
                        base_url,
                        "/v1/specspace-state/record",
                        method="PUT",
                        payload=payload,
                        authorized=False,
                    )
                self.request(
                    base_url,
                    "/v1/specspace-state/record",
                    method="PUT",
                    payload=payload,
                )
                conflict_payload = {
                    **payload,
                    "idempotency_key": "state-write:workspace-a:http-0002",
                    "content": {"requests": [{"raw_idea": "must not leak"}]},
                }
                with self.assertRaises(urllib.error.HTTPError) as conflict:
                    self.request(
                        base_url,
                        "/v1/specspace-state/record",
                        method="PUT",
                        payload=conflict_payload,
                    )
                conflict_body = conflict.exception.read().decode("utf-8")
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(unauthorized.exception.code, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(conflict.exception.code, HTTPStatus.CONFLICT)
        self.assertNotIn("must not leak", conflict_body)

    def test_confirmation_consumption_is_atomic_and_same_request_replay_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = self.build_service(root)
            created = service.mutate(
                {
                    "workspace_id": WORKSPACE_ID,
                    "record_key": CONFIRMATION_KEY,
                    "expected_revision": 0,
                    "idempotency_key": "confirmation-create:workspace-a:0001",
                    "lifecycle_state": "active",
                    "content": confirmation_content(),
                }
            )
            consume_payload = {
                "workspace_id": WORKSPACE_ID,
                "record_key": CONFIRMATION_KEY,
                "expected_revision": 1,
                "expected_content_sha256": created["record"]["content_sha256"],
                "operation_id": "promotion_review_execute",
                "request_identity_sha256": "7" * 64,
            }

            first = service.consume_confirmation(consume_payload)
            replay = service.consume_confirmation(
                {**consume_payload, "expected_revision": 2}
            )
            with self.assertRaisesRegex(
                service_module.StateServiceError,
                "consumed confirmation state is terminal",
            ):
                service.mutate(
                    {
                        "workspace_id": WORKSPACE_ID,
                        "record_key": CONFIRMATION_KEY,
                        "expected_revision": 2,
                        "idempotency_key": "confirmation-reactivate:workspace-a:0001",
                        "lifecycle_state": "active",
                        "content": confirmation_content(),
                    }
                )
            with self.assertRaisesRegex(
                service_module.StateServiceError,
                "confirmation is not active",
            ):
                service.consume_confirmation(
                    {
                        **consume_payload,
                        "expected_revision": 2,
                        "request_identity_sha256": "8" * 64,
                    }
                )

        self.assertEqual(first["record"]["revision"], 2)
        self.assertEqual(first["record"]["lifecycle_state"], "consumed")
        self.assertFalse(first["summary"]["idempotent_replay"])
        self.assertEqual(replay["record"]["revision"], 2)
        self.assertTrue(replay["summary"]["idempotent_replay"])
        self.assertEqual(
            first["record"]["content_sha256"],
            created["record"]["content_sha256"],
        )

    def test_http_confirmation_consumption_requires_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            server = service_module.create_server(
                host="127.0.0.1",
                port=0,
                service=self.build_service(root),
                auth_token=TOKEN,
                confirmation_token=CONFIRMATION_TOKEN,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            content = confirmation_content()
            try:
                created = self.request(
                    base_url,
                    "/v1/specspace-state/record",
                    method="PUT",
                    payload={
                        "workspace_id": WORKSPACE_ID,
                        "record_key": CONFIRMATION_KEY,
                        "expected_revision": 0,
                        "idempotency_key": "confirmation-create:workspace-a:0001",
                        "lifecycle_state": "active",
                        "content": content,
                    },
                )
                payload = {
                    "workspace_id": WORKSPACE_ID,
                    "record_key": CONFIRMATION_KEY,
                    "expected_revision": 1,
                    "expected_content_sha256": created["record"]["content_sha256"],
                    "operation_id": "promotion_review_execute",
                    "request_identity_sha256": "9" * 64,
                }
                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    self.request(
                        base_url,
                        "/v1/specspace-state/confirmation/consume",
                        method="POST",
                        payload=payload,
                        authorized=False,
                    )
                consumed = self.request(
                    base_url,
                    "/v1/specspace-state/confirmation/consume",
                    method="POST",
                    payload=payload,
                    token=CONFIRMATION_TOKEN,
                )
                query = urllib.parse.urlencode(
                    {
                        "workspace_id": WORKSPACE_ID,
                        "record_key": CONFIRMATION_KEY,
                    }
                )
                confirmation = self.request(
                    base_url,
                    f"/v1/specspace-state/confirmation?{query}",
                    token=CONFIRMATION_TOKEN,
                )
                with self.assertRaises(urllib.error.HTTPError) as primary_denied:
                    self.request(
                        base_url,
                        f"/v1/specspace-state/confirmation?{query}",
                    )
                with self.assertRaises(urllib.error.HTTPError) as write_denied:
                    self.request(
                        base_url,
                        "/v1/specspace-state/record",
                        method="PUT",
                        payload={
                            "workspace_id": WORKSPACE_ID,
                            "record_key": RECORD_KEY,
                            "expected_revision": 0,
                            "idempotency_key": "state-write:workspace-a:denied",
                            "lifecycle_state": "active",
                            "content": {"requests": []},
                        },
                        token=CONFIRMATION_TOKEN,
                    )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(unauthorized.exception.code, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(primary_denied.exception.code, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(write_denied.exception.code, HTTPStatus.UNAUTHORIZED)
        self.assertTrue(consumed["ok"])
        self.assertEqual(consumed["record"]["lifecycle_state"], "consumed")
        self.assertEqual(confirmation["record"]["revision"], 2)

    def test_workspace_scoped_mirror_is_preferred_by_managed_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            scoped = state_dir / WORKSPACE_ID / RECORD_KEY
            scoped.parent.mkdir(parents=True)
            scoped.write_text('{"scope":"workspace"}\n', encoding="utf-8")
            legacy = state_dir / RECORD_KEY
            legacy.write_text('{"scope":"legacy"}\n', encoding="utf-8")
            resolver = executor_module.FilesystemManagedOperationResolver(
                artifact_root=root / "artifacts",
                state_dir=state_dir,
                specgraph_dir=root / "specgraph",
                binding_validator=lambda binding, workspace: [],
            )

            resolved = resolver.resolve_logical_ref(
                f"specspace-state://{RECORD_KEY}",
                WORKSPACE_ID,
            )

        self.assertEqual(resolved, scoped.resolve())


if __name__ == "__main__":
    unittest.main()
