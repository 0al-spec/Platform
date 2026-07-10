from __future__ import annotations

import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.parse
import subprocess
import sys

from scripts import hosted_managed_operation_canary as canary
from scripts import hosted_managed_operation_executor as executor_module
from scripts import hosted_managed_operation_queue as queue_module
from scripts import hosted_managed_operation_service as service_module
from scripts import hosted_managed_operations as contracts
from tests.test_hosted_managed_operation_executor import (
    ExecutorFixture,
    RecordingRunner,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


TOKEN = "hosted-canary-test-token-0123456789abcdef"


class CanaryHTTPHandler(BaseHTTPRequestHandler):
    request_payload: dict | None = None
    status_calls = 0
    success_receipt: dict | None = None

    def log_message(self, format: str, *args: object) -> None:
        return

    def _write(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/v1/health":
            self._write(200, {"ok": True, "status": "ready"})
            return
        if parsed.path != "/v1/managed-operations/status":
            self._write(404, {"ok": False})
            return
        type(self).status_calls += 1
        status = "running" if type(self).status_calls == 1 else "succeeded"
        receipt = (
            type(self).success_receipt
            if status == "succeeded"
            else {"status": "running", "attempt": 1, "output_reports": []}
        )
        self._write(
            200,
            {
                "ok": True,
                "job": {"status": status, "attempt": 1, "receipt": receipt},
                "events": [],
            },
        )

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payload = json.loads(self.rfile.read(content_length))
        if set(type(self).request_payload) != {
            "operation_id",
            "workspace_id",
            "workspace_binding_ref",
            "input_refs",
        } and set(type(self).request_payload) != {
            "operation_id",
            "workspace_id",
            "workspace_binding_ref",
            "input_refs",
            "operator_ref",
        }:
            self._write(400, {"ok": False, "error": "enqueue_shape_invalid"})
            return
        receipt = {
            "status": "queued",
            "attempt": 0,
            "output_reports": [],
        }
        self._write(
            202,
            {
                "ok": True,
                "receipt": receipt,
                "summary": {"request_id": "managed-operation://remote/request-1"},
            },
        )


class HostedManagedOperationCanaryTests(unittest.TestCase):
    def setUp(self) -> None:
        CanaryHTTPHandler.request_payload = None
        CanaryHTTPHandler.status_calls = 0
        CanaryHTTPHandler.success_receipt = None

    def server(self) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
        server = ThreadingHTTPServer(("127.0.0.1", 0), CanaryHTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{server.server_address[1]}"

    def test_read_only_canary_verifies_authoritative_output_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("review_status_execute")
            output = fixture.path_for_ref(
                "runs/product_candidate_promotion_review_status_report.json"
            )
            output.write_text('{"ok":true}\n', encoding="utf-8")
            output_ref = "runs/product_candidate_promotion_review_status_report.json"
            output_digest = hashlib.sha256(output.read_bytes()).hexdigest()
            CanaryHTTPHandler.success_receipt = contracts.build_receipt(
                request=request,
                status="succeeded",
                generated_at="2026-07-10T00:00:02Z",
                attempt=1,
                output_reports=[{"logical_ref": output_ref, "sha256": output_digest}],
            )
            server, thread, service_url = self.server()
            try:
                report = canary.run_canary(
                    request=request,
                    service_url=service_url,
                    token=TOKEN,
                    poll_interval_seconds=0,
                    artifact_root=fixture.artifact_root,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertTrue(report["summary"]["ok"], report["diagnostics"])
        self.assertEqual(report["summary"]["profile"], "read_only")
        self.assertEqual(report["authoritative_outputs"]["verified_refs"], [output_ref])
        self.assertNotIn(TOKEN, json.dumps(report))
        self.assertNotIn(str(fixture.root), json.dumps(report))

    def test_canary_runs_against_real_hosted_service_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("review_status_execute")
            database = Path(temp_dir) / "queue.sqlite3"
            service = service_module.HostedManagedOperationService(
                database_path=database,
                resolver=fixture.resolver(),
                now_epoch=lambda: 100.0,
                now_iso=lambda: "2026-07-10T00:00:00Z",
            )
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
            self.assertTrue(service.health()["ok"])
            stop_worker = threading.Event()

            def process_one() -> None:
                queue = queue_module.SQLiteManagedOperationQueue(database)
                worker = queue_module.HostedManagedOperationWorker(
                    queue,
                    executor_module.PlatformManagedOperationExecutor(
                        resolver=fixture.resolver(),
                        platform_script=fixture.platform_script,
                        runner=RecordingRunner(),
                    ),
                    worker_id="canary-worker",
                )
                try:
                    while not stop_worker.is_set():
                        receipt = worker.run_once()
                        if receipt is not None:
                            return
                        time.sleep(0.01)
                finally:
                    queue.close()

            worker_thread = threading.Thread(target=process_one, daemon=True)
            worker_thread.start()
            try:
                report = canary.run_canary(
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
        self.assertTrue(
            report["request"]["request_id"].startswith("managed-operation://")
        )

    def test_canary_rejects_irreversible_operation_without_explicit_dry_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("promotion_review_execute")
            server, thread, service_url = self.server()
            try:
                report = canary.run_canary(
                    request=request,
                    service_url=service_url,
                    token=TOKEN,
                    poll_interval_seconds=0,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertFalse(report["summary"]["ok"])
        self.assertIn(
            "canary operation must be read-only", " ".join(report["diagnostics"])
        )
        self.assertIsNone(CanaryHTTPHandler.request_payload)

    def test_canary_requires_explicit_opt_in_for_registered_promotion_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("promotion_execute_dry_run")

            blocked_server, blocked_thread, blocked_service_url = self.server()
            try:
                blocked_report = canary.run_canary(
                    request=request,
                    service_url=blocked_service_url,
                    token=TOKEN,
                    poll_interval_seconds=0,
                    artifact_root=fixture.artifact_root,
                )
            finally:
                blocked_server.shutdown()
                blocked_thread.join(timeout=5)
                blocked_server.server_close()

            self.assertFalse(blocked_report["summary"]["ok"])
            self.assertIn(
                "canary operation must be read-only",
                " ".join(blocked_report["diagnostics"]),
            )
            self.assertIsNone(CanaryHTTPHandler.request_payload)

            output_reports = []
            for ref in request["expected_output_reports"]:
                output = fixture.path_for_ref(ref)
                output.write_text('{"dry_run":true}\n', encoding="utf-8")
                output_reports.append(
                    {
                        "logical_ref": ref,
                        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    }
                )
            CanaryHTTPHandler.success_receipt = contracts.build_receipt(
                request=request,
                status="succeeded",
                generated_at="2026-07-10T00:00:02Z",
                attempt=1,
                output_reports=output_reports,
            )
            server, thread, service_url = self.server()
            try:
                report = canary.run_canary(
                    request=request,
                    service_url=service_url,
                    token=TOKEN,
                    poll_interval_seconds=0,
                    allow_dry_run=True,
                    artifact_root=fixture.artifact_root,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertTrue(report["summary"]["ok"], report["diagnostics"])
        self.assertEqual(report["summary"]["profile"], "dry_run")
        self.assertFalse(report["authority_boundary"]["allows_irreversible_operations"])

    def test_cli_writes_durable_canary_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = ExecutorFixture(root)
            request = fixture.request("review_status_execute")
            request_path = root / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            output = fixture.path_for_ref(
                "runs/product_candidate_promotion_review_status_report.json"
            )
            output.write_text('{"ok":true}\n', encoding="utf-8")
            output_ref = "runs/product_candidate_promotion_review_status_report.json"
            output_digest = hashlib.sha256(output.read_bytes()).hexdigest()
            CanaryHTTPHandler.success_receipt = contracts.build_receipt(
                request=request,
                status="succeeded",
                generated_at="2026-07-10T00:00:02Z",
                attempt=1,
                output_reports=[{"logical_ref": output_ref, "sha256": output_digest}],
            )
            server, thread, service_url = self.server()
            report_path = root / "canary-report.json"
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "platform.py"),
                        "managed-operation",
                        "canary",
                        "--service-url",
                        service_url,
                        "--request",
                        str(request_path),
                        "--artifact-root",
                        str(fixture.artifact_root),
                        "--output",
                        str(report_path),
                        "--format",
                        "json",
                    ],
                    cwd=REPO_ROOT,
                    env={**os.environ, "PLATFORM_MANAGED_OPERATION_TOKEN": TOKEN},
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = json.loads(report_text)
        self.assertEqual(report["summary"]["status"], "hosted_managed_canary_passed")
        self.assertTrue(report_text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
