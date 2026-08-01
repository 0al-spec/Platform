from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest

from scripts import specspace_state_client as client_module
from scripts import specspace_state_service as service_module
from scripts import specspace_state_store as store_module


TOKEN = "specspace-state-client-token-0123456789abcdef"
CONFIRMATION_TOKEN = "confirmation-client-token-0123456789abcdef"
WORKSPACE_ID = "workspace-a"
RECORD_KEY = (
    "confirmations/workspace-a/promotion_review_execute/"
    "0123456789abcdef0123456789abcdef.json"
)


def content() -> dict:
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


class SpecSpaceStateClientTests(unittest.TestCase):
    def test_client_reads_and_consumes_one_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "state.sqlite3"
            service = service_module.SpecSpaceStateService(
                store_factory=lambda: store_module.SQLiteSpecSpaceStateStore(
                    database
                ),
                adapter="sqlite",
                mirror_root=root / "mirror",
                now_iso=lambda: "2026-08-01T00:00:00Z",
            )
            created = service.mutate(
                {
                    "workspace_id": WORKSPACE_ID,
                    "record_key": RECORD_KEY,
                    "expected_revision": 0,
                    "idempotency_key": "confirmation-create:workspace-a:0001",
                    "lifecycle_state": "active",
                    "content": content(),
                }
            )
            server = service_module.create_server(
                host="127.0.0.1",
                port=0,
                service=service,
                auth_token=TOKEN,
                confirmation_token=CONFIRMATION_TOKEN,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = client_module.SpecSpaceStateClient(
                base_url=f"http://127.0.0.1:{server.server_address[1]}",
                token=CONFIRMATION_TOKEN,
            )
            try:
                record = client.get_record(
                    workspace_id=WORKSPACE_ID,
                    record_key=RECORD_KEY,
                )
                consumed = client.consume_confirmation(
                    workspace_id=WORKSPACE_ID,
                    record_key=RECORD_KEY,
                    expected_revision=record["revision"],
                    expected_content_sha256=record["content_sha256"],
                    request_identity_sha256="5" * 64,
                )
                replay = client.consume_confirmation(
                    workspace_id=WORKSPACE_ID,
                    record_key=RECORD_KEY,
                    expected_revision=consumed["revision"],
                    expected_content_sha256=consumed["content_sha256"],
                    request_identity_sha256="5" * 64,
                )
                with self.assertRaises(client_module.SpecSpaceStateClientConflict):
                    client.consume_confirmation(
                        workspace_id=WORKSPACE_ID,
                        record_key=RECORD_KEY,
                        expected_revision=consumed["revision"],
                        expected_content_sha256=consumed["content_sha256"],
                        request_identity_sha256="6" * 64,
                    )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(record["content"], content())
        self.assertEqual(record["content_sha256"], created["record"]["content_sha256"])
        self.assertEqual(consumed["lifecycle_state"], "consumed")
        self.assertEqual(consumed["revision"], 2)
        self.assertEqual(replay, consumed)
        self.assertNotIn(CONFIRMATION_TOKEN, json.dumps(consumed))

    def test_client_rejects_credentials_in_service_url(self) -> None:
        with self.assertRaises(client_module.SpecSpaceStateClientError):
            client_module.SpecSpaceStateClient(
                base_url="https://user:password@example.test",
                token=TOKEN,
            )

    def test_client_requires_opt_in_for_private_plain_http(self) -> None:
        with self.assertRaisesRegex(
            client_module.SpecSpaceStateClientError,
            "private-network opt-in",
        ):
            client_module.SpecSpaceStateClient(
                base_url="http://specspace-state:8092",
                token=TOKEN,
            )

        loopback = client_module.SpecSpaceStateClient(
            base_url="http://127.0.0.1:8092",
            token=TOKEN,
        )
        private_network = client_module.SpecSpaceStateClient(
            base_url="http://specspace-state:8092",
            token=TOKEN,
            allow_insecure_private_http=True,
        )

        self.assertEqual(loopback.base_url, "http://127.0.0.1:8092")
        self.assertEqual(private_network.base_url, "http://specspace-state:8092")

    def test_client_rejects_authority_schema_drift(self) -> None:
        payload = {
            "authority_boundary": {
                **client_module.TRUSTED_AUTHORITY_BOUNDARY,
                "may_execute_platform": True,
            }
        }

        self.assertFalse(client_module._trusted_boundary(payload))


if __name__ == "__main__":
    unittest.main()
