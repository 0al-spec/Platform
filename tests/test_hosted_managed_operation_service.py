from __future__ import annotations

from http import HTTPStatus
import hashlib
import json
import os
from pathlib import Path
import subprocess
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
import hosted_managed_promotion_review as promotion_review
import specspace_state_client
import specspace_state_service
import specspace_state_store
from tests.test_hosted_managed_operation_executor import (
    BINDING_REF,
    ExecutorFixture,
    WORKSPACE_ID,
)


TOKEN = "hosted-test-token-0123456789abcdef"
STATE_CONFIRMATION_TOKEN = "state-confirmation-token-0123456789abcdef"


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

    def test_health_fails_without_exposing_queue_failure_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))

            def unavailable_queue():
                raise RuntimeError("private database failure")

            service = service_module.HostedManagedOperationService(
                queue_factory=unavailable_queue,
                adapter="postgresql",
                resolver=fixture.resolver(),
                now_epoch=lambda: 100.0,
                now_iso=lambda: "2026-07-10T00:00:00Z",
            )

            report = service.health()

        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "queue_unavailable")
        self.assertNotIn("private database failure", json.dumps(report))

    def test_operation_allowlist_is_reported_and_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = ExecutorFixture(temp)
            service = service_module.HostedManagedOperationService(
                database_path=temp / "queue.sqlite3",
                resolver=fixture.resolver(),
                now_epoch=lambda: 100.0,
                now_iso=lambda: "2026-07-10T00:00:00Z",
                allowed_operation_ids=frozenset({"review_status_execute"}),
            )
            health = service.health()
            payload = self.review_status_payload(fixture)
            payload["operation_id"] = "promotion_review_execute"

            with self.assertRaises(service_module.HostedServiceError) as error:
                service.enqueue(payload)

        self.assertEqual(health["operation_count"], 1)
        self.assertEqual(health["enabled_operation_ids"], ["review_status_execute"])
        self.assertIn("deployment allowlist", str(error.exception))

    def test_cli_requires_state_service_for_promotion_review_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = ExecutorFixture(temp)
            command = [
                sys.executable,
                str(REPO_ROOT / "scripts" / "platform.py"),
                "managed-operation",
                "serve",
                "--database",
                str(temp / "queue.sqlite3"),
                "--artifact-root",
                str(fixture.artifact_root),
                "--state-dir",
                str(fixture.state_dir),
                "--specgraph-dir",
                str(fixture.specgraph_dir),
                "--operation-allowlist",
                "promotion_review_execute",
            ]
            environment = os.environ.copy()
            environment["PLATFORM_MANAGED_OPERATION_TOKEN"] = TOKEN
            environment.pop("PLATFORM_SPECSPACE_CONFIRMATION_TOKEN", None)

            missing_url = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            missing_token = subprocess.run(
                [
                    *command,
                    "--specspace-state-service-url",
                    "http://127.0.0.1:8092",
                ],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(missing_url.returncode, 2)
        self.assertIn(
            "requires --specspace-state-service-url",
            missing_url.stderr,
        )
        self.assertEqual(missing_token.returncode, 2)
        self.assertIn("state service token is invalid", missing_token.stderr)

    def test_promotion_review_consumes_semantic_confirmation_before_enqueue(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = ExecutorFixture(temp)
            input_refs = [
                promotion_review.PROMOTION_REQUEST_REF,
                promotion_review.APPROVAL_DECISION_REF,
                promotion_review.EXECUTION_PLAN_REF,
            ]
            input_paths = {
                ref: fixture.write_input(ref, "promotion_review_execute", index)
                for index, ref in enumerate(input_refs)
            }
            input_digests = {
                ref: hashlib.sha256(path.read_bytes()).hexdigest()
                for ref, path in input_paths.items()
            }
            dry_run_fragment = "0123456789abcdef01234567"
            dry_run_request_id = (
                f"managed-operation://{WORKSPACE_ID}/"
                f"promotion_execute_dry_run/{dry_run_fragment}"
            )
            execution_ref = (
                "runs/managed-promotion-dry-runs/"
                f"{dry_run_fragment}."
                "product_candidate_promotion_execution_report.json"
            )
            git_ref = (
                "runs/managed-promotion-dry-runs/"
                f"{dry_run_fragment}.git_service_promotion_execution_report.json"
            )
            execution_path = fixture.path_for_ref(execution_ref)
            execution_path.parent.mkdir(parents=True, exist_ok=True)
            execution_path.write_text(
                json.dumps(
                    {
                        "artifact_kind": (
                            "platform_product_candidate_promotion_execution_report"
                        ),
                        "ok": True,
                        "dry_run": True,
                        "open_review_dry_run": True,
                        "workspace_id": WORKSPACE_ID,
                        "summary": {
                            "worktree_prepared": False,
                            "physical_worktree_created": False,
                            "commit_created": False,
                            "review_opened": False,
                            "read_model_published": False,
                        },
                        "authority_boundary": {
                            "specspace_direct_git_write": False,
                            "controlled_git_service_execution": False,
                            "creates_candidate_worktree_or_branch": False,
                            "creates_candidate_commit": False,
                            "opens_pull_requests": False,
                            "merges_pull_requests": False,
                            "publishes_read_models": False,
                            "canonical_spec_mutation_without_review": False,
                            "ontology_package_write": False,
                            "ontology_term_acceptance": False,
                            "private_artifact_publication": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            git_path = fixture.path_for_ref(git_ref)
            git_path.write_text(
                json.dumps(
                    {
                        "artifact_kind": (
                            "platform_git_service_promotion_execution_report"
                        ),
                        "ok": True,
                        "dry_run": True,
                        "open_review_dry_run": True,
                        "copied_materialized_files": [],
                        "operations": [
                            {"name": "prepare_worktree", "status": "dry_run"},
                            {
                                "name": "commit_candidate",
                                "status": "skipped_dry_run",
                            },
                            {
                                "name": "open_review",
                                "status": "skipped_dry_run",
                            },
                        ],
                        "authority_boundary": {
                            "specspace_direct_git_write": False,
                            "canonical_spec_mutation_without_review": False,
                            "ontology_package_write": False,
                            "auto_merge": False,
                            "private_artifact_publication": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            confirmation_key = (
                f"confirmations/{WORKSPACE_ID}/promotion_review_execute/"
                "0123456789abcdef0123456789abcdef.json"
            )
            binding_digest = hashlib.sha256(fixture.binding_path.read_bytes()).hexdigest()
            confirmation = {
                "artifact_kind": promotion_review.CONFIRMATION_KIND,
                "schema_version": 1,
                "contract_ref": promotion_review.CONFIRMATION_CONTRACT_REF,
                "confirmation_id": (
                    f"confirmation://{WORKSPACE_ID}/promotion_review_execute/"
                    "0123456789abcdef0123456789abcdef"
                ),
                "workspace_id": WORKSPACE_ID,
                "operation_id": "promotion_review_execute",
                "operator_ref": "operator://specspace-basic-session-a",
                "status": "ready",
                "confirmed": True,
                "issued_at": "2026-08-01T10:00:00Z",
                "expires_at": "2026-08-01T10:15:00Z",
                "workspace_binding": {
                    "binding_id": f"product-workspace-binding://{WORKSPACE_ID}",
                    "binding_revision_sha256": "1" * 64,
                    "source_sha256": binding_digest,
                },
                "inputs": {
                    name: {
                        "logical_ref": ref,
                        "sha256": input_digests[ref],
                    }
                    for name, ref in promotion_review.BOUND_INPUT_REFS.items()
                },
                "predecessor_dry_run": {
                    "request_id": dry_run_request_id,
                    "execution_report": {
                        "logical_ref": execution_ref,
                        "sha256": hashlib.sha256(
                            execution_path.read_bytes()
                        ).hexdigest(),
                    },
                    "git_service_report": {
                        "logical_ref": git_ref,
                        "sha256": hashlib.sha256(git_path.read_bytes()).hexdigest(),
                    },
                },
                "authority_boundary": dict(promotion_review.AUTHORITY_BOUNDARY),
            }
            state_database = temp / "state.sqlite3"
            state_service = specspace_state_service.SpecSpaceStateService(
                store_factory=lambda: specspace_state_store.SQLiteSpecSpaceStateStore(
                    state_database
                ),
                adapter="sqlite",
                mirror_root=fixture.state_dir,
                now_iso=lambda: "2026-08-01T10:05:00Z",
            )
            state_service.mutate(
                {
                    "workspace_id": WORKSPACE_ID,
                    "record_key": confirmation_key,
                    "expected_revision": 0,
                    "idempotency_key": "confirmation-create:pantry-control:0001",
                    "lifecycle_state": "active",
                    "content": confirmation,
                }
            )
            state_server = specspace_state_service.create_server(
                host="127.0.0.1",
                port=0,
                service=state_service,
                auth_token="state-primary-token-0123456789abcdef",
                confirmation_token=STATE_CONFIRMATION_TOKEN,
            )
            state_thread = threading.Thread(
                target=state_server.serve_forever,
                daemon=True,
            )
            state_thread.start()
            state_client = specspace_state_client.SpecSpaceStateClient(
                base_url=(
                    f"http://127.0.0.1:{state_server.server_address[1]}"
                ),
                token=STATE_CONFIRMATION_TOKEN,
            )
            service = service_module.HostedManagedOperationService(
                database_path=temp / "queue.sqlite3",
                resolver=fixture.resolver(),
                now_epoch=lambda: 100.0,
                now_iso=lambda: "2026-08-01T10:05:00Z",
                allowed_operation_ids=frozenset({"promotion_review_execute"}),
                state_client=state_client,
            )
            payload = {
                "operation_id": "promotion_review_execute",
                "workspace_id": WORKSPACE_ID,
                "workspace_binding_ref": BINDING_REF,
                "input_refs": input_refs,
                "operator_ref": "operator://specspace-basic-session-a",
                "confirmation_ref": f"specspace-state://{confirmation_key}",
            }
            try:
                first = service.enqueue(payload)
                service.now_iso = lambda: "2026-08-01T10:30:00Z"
                replay = service.enqueue(payload)
                (temp / "queue.sqlite3").unlink()
                with self.assertRaisesRegex(
                    service_module.HostedServiceError,
                    "reconciliation is required",
                ):
                    service.enqueue(payload)
                consumed = state_client.get_record(
                    workspace_id=WORKSPACE_ID,
                    record_key=confirmation_key,
                )
            finally:
                state_server.shutdown()
                state_thread.join(timeout=5)
                state_server.server_close()

        self.assertEqual(first["receipt"]["status"], "queued")
        self.assertEqual(first["summary"]["request_id"], replay["summary"]["request_id"])
        self.assertEqual(first["request"], replay["request"])
        self.assertEqual(first["request"]["confirmation"]["revision"], 2)
        self.assertEqual(
            first["request"]["confirmation"]["lifecycle_state"],
            "consumed",
        )
        self.assertEqual(consumed["lifecycle_state"], "consumed")
        self.assertEqual(consumed["revision"], 2)


if __name__ == "__main__":
    unittest.main()
