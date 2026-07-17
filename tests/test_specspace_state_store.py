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
WORKSPACE_ID = "workspace-a"
RECORD_KEY = "real_idea_entry_requests.json"


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
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = f"Bearer {TOKEN}"
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
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            mirror = root / "mirror" / WORKSPACE_ID / RECORD_KEY
            mirror_payload = json.loads(mirror.read_text(encoding="utf-8"))

        self.assertTrue(report["ok"])
        self.assertEqual(report["record"]["revision"], 1)
        self.assertEqual(record["record"]["content"], mutation().content)
        self.assertEqual(mirror_payload, mutation().content)
        self.assertTrue(health["ok"])
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
