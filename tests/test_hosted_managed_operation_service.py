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

import hosted_managed_operation_service as service_module
from tests.test_hosted_managed_operation_executor import (
    BINDING_REF,
    ExecutorFixture,
    WORKSPACE_ID,
)


TOKEN = "hosted-test-token-0123456789abcdef"


class HostedManagedOperationServiceTests(unittest.TestCase):
    def build_service(
        self, fixture: ExecutorFixture, database: Path
    ) -> service_module.HostedManagedOperationService:
        return service_module.HostedManagedOperationService(
            database_path=database,
            resolver=fixture.resolver(),
            now_epoch=lambda: 100.0,
            now_iso=lambda: "2026-07-10T00:00:00Z",
        )

    def review_status_payload(self, fixture: ExecutorFixture) -> dict:
        fixture.write_input(
            "runs/product_candidate_promotion_execution_report.json",
            "review_status_execute",
            0,
        )
        return {
            "operation_id": "review_status_execute",
            "workspace_id": WORKSPACE_ID,
            "workspace_binding_ref": BINDING_REF,
            "input_refs": [
                "runs/product_candidate_promotion_execution_report.json"
            ],
            "operator_ref": "operator://specspace-local",
        }

    def test_service_materializes_and_enqueues_without_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = ExecutorFixture(temp)
            service = self.build_service(fixture, temp / "queue.sqlite3")

            report = service.enqueue(self.review_status_payload(fixture))
            status = service.status(
                report["summary"]["request_id"], include_events=True
            )

        self.assertEqual(report["receipt"]["status"], "queued")
        self.assertEqual(status["summary"]["status"], "queued")
        self.assertEqual(len(status["events"]), 1)
        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn(temp_dir, serialized)
        self.assertNotIn("lease_owner", json.dumps(status))

    def test_service_rejects_unknown_fields_and_missing_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = ExecutorFixture(temp)
            service = self.build_service(fixture, temp / "queue.sqlite3")
            payload = self.review_status_payload(fixture)
            payload["raw_idea"] = "private"

            with self.assertRaises(service_module.HostedServiceError):
                service.enqueue(payload)
            payload.pop("raw_idea")
            payload["input_refs"] = []
            with self.assertRaises(service_module.HostedServiceError):
                service.enqueue(payload)

    def test_http_api_requires_bearer_token_and_returns_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = ExecutorFixture(temp)
            service = self.build_service(fixture, temp / "queue.sqlite3")
            server = service_module.create_server(
                host="127.0.0.1",
                port=0,
                service=service,
                auth_token=TOKEN,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            payload = self.review_status_payload(fixture)
            data = json.dumps(payload).encode("utf-8")
            try:
                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    urllib.request.urlopen(
                        urllib.request.Request(
                            f"{base_url}/v1/managed-operations",
                            data=data,
                            headers={"Content-Type": "application/json"},
                        )
                    )
                self.assertEqual(unauthorized.exception.code, HTTPStatus.UNAUTHORIZED)

                enqueue_request = urllib.request.Request(
                    f"{base_url}/v1/managed-operations",
                    data=data,
                    headers={
                        "Authorization": f"Bearer {TOKEN}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(enqueue_request) as response:
                    self.assertEqual(response.status, HTTPStatus.ACCEPTED)
                    enqueue_report = json.loads(response.read())
                request_id = enqueue_report["summary"]["request_id"]
                status_url = (
                    f"{base_url}/v1/managed-operations/status?"
                    + urllib.parse.urlencode(
                        {"request_id": request_id, "include_events": "true"}
                    )
                )
                with urllib.request.urlopen(
                    urllib.request.Request(
                        status_url,
                        headers={"Authorization": f"Bearer {TOKEN}"},
                    )
                ) as response:
                    status_report = json.loads(response.read())
                self.assertEqual(status_report["summary"]["status"], "queued")
                self.assertEqual(len(status_report["events"]), 1)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_health_does_not_require_or_expose_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = ExecutorFixture(temp)
            server = service_module.create_server(
                host="127.0.0.1",
                port=0,
                service=self.build_service(fixture, temp / "queue.sqlite3"),
                auth_token=TOKEN,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_address[1]}/v1/health"
                ) as response:
                    payload = json.loads(response.read())
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertTrue(payload["ok"])
        self.assertNotIn(TOKEN, json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
