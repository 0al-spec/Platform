from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import hosted_managed_operation_executor as executor_module
import hosted_managed_operation_queue as queue_module
import hosted_managed_operations as contracts
import hosted_managed_promotion_review as promotion_review
import specspace_state_service
import specspace_state_store as state_contracts
from scripts import platform


WORKSPACE_ID = "pantry-control"
BINDING_REF = (
    f"runs/{WORKSPACE_ID}/platform_product_workspace_initialization_execution_report.json"
)


def binding(status: str = "ready") -> dict:
    return {
        "artifact_kind": "platform_product_workspace_binding",
        "schema_version": 1,
        "contract_ref": "platform.product-workspace.binding.v1",
        "binding_id": f"product-workspace-binding://{WORKSPACE_ID}",
        "binding_revision_sha256": "1" * 64,
        "status": status,
        "identity": {"workspace_id": WORKSPACE_ID, "route": f"/{WORKSPACE_ID}"},
    }


class ExecutorFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.artifact_root = root / "artifacts"
        self.state_dir = root / "state"
        self.specgraph_dir = root / "SpecGraph"
        self.platform_script = root / "Platform" / "scripts" / "platform.py"
        self.workspace_runs = self.artifact_root / "runs" / WORKSPACE_ID
        self.workspace_runs.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)
        self.specgraph_dir.mkdir(parents=True)
        (self.specgraph_dir / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        self.platform_script.parent.mkdir(parents=True)
        self.platform_script.write_text("# fake\n", encoding="utf-8")
        self.binding_path = self.artifact_root / BINDING_REF
        self.binding_path.parent.mkdir(parents=True, exist_ok=True)
        self.binding_path.write_text(
            json.dumps({"workspace_binding": binding()}),
            encoding="utf-8",
        )
        self.confirmation_records: dict[str, dict] = {}

    def path_for_ref(self, ref: str) -> Path:
        if ref.startswith("specspace-state://"):
            return self.state_dir / ref.removeprefix("specspace-state://")
        if ref.startswith("runs/"):
            return self.workspace_runs / ref.removeprefix("runs/").replace(
                "<workspace-id>", WORKSPACE_ID
            )
        if ref.startswith("dist/"):
            return self.specgraph_dir / ref.replace("<workspace-id>", WORKSPACE_ID)
        raise AssertionError(ref)

    def write_input(self, ref: str, operation_id: str, index: int) -> Path:
        if ref == "runs/platform_product_workspace_initialization_execution_report.json":
            return self.binding_path
        path = self.path_for_ref(ref)
        if ref.startswith("dist/"):
            path.mkdir(parents=True, exist_ok=True)
            (path / "artifact_manifest.json").write_text("{}", encoding="utf-8")
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict = {"artifact_kind": f"test_{operation_id}_{index}"}
        if ref == "runs/repaired_idea_to_spec_promotion_gate.json":
            payload["promotion_request"] = {
                "paths": ["specs/nodes/pantry-control.spec.yaml"]
            }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_promotion_review_confirmation(
        self,
        *,
        inputs: dict[str, Path],
        binding_source_sha256: str,
        operator_ref: str,
    ) -> tuple[str, str]:
        request_fragment = "0123456789abcdef01234567"
        execution_ref = (
            "runs/managed-promotion-dry-runs/"
            f"{request_fragment}.product_candidate_promotion_execution_report.json"
        )
        git_ref = (
            "runs/managed-promotion-dry-runs/"
            f"{request_fragment}.git_service_promotion_execution_report.json"
        )
        execution_path = self.path_for_ref(execution_ref)
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
        git_path = self.path_for_ref(git_ref)
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
                        {"name": "commit_candidate", "status": "skipped_dry_run"},
                        {"name": "open_review", "status": "skipped_dry_run"},
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
        confirmation_fragment = "0123456789abcdef0123456789abcdef"
        confirmation_ref = (
            "specspace-state://confirmations/"
            f"{WORKSPACE_ID}/promotion_review_execute/{confirmation_fragment}.json"
        )
        confirmation_path = self.path_for_ref(confirmation_ref)
        confirmation_path.parent.mkdir(parents=True, exist_ok=True)
        confirmation_path.write_text(
            json.dumps(
                {
                    "artifact_kind": promotion_review.CONFIRMATION_KIND,
                    "schema_version": 1,
                    "contract_ref": promotion_review.CONFIRMATION_CONTRACT_REF,
                    "confirmation_id": (
                        f"confirmation://{WORKSPACE_ID}/promotion_review_execute/"
                        "0123456789abcdef0123456789abcdef"
                    ),
                    "workspace_id": WORKSPACE_ID,
                    "operation_id": "promotion_review_execute",
                    "operator_ref": operator_ref,
                    "status": "ready",
                    "confirmed": True,
                    "issued_at": "2026-07-10T00:00:00Z",
                    "expires_at": "2026-07-10T00:15:00Z",
                    "workspace_binding": {
                        "binding_id": f"product-workspace-binding://{WORKSPACE_ID}",
                        "binding_revision_sha256": "1" * 64,
                        "source_sha256": binding_source_sha256,
                    },
                    "inputs": {
                        name: {
                            "logical_ref": ref,
                            "sha256": hashlib.sha256(inputs[ref].read_bytes()).hexdigest(),
                        }
                        for name, ref in promotion_review.BOUND_INPUT_REFS.items()
                    },
                    "predecessor_dry_run": {
                        "request_id": (
                            f"managed-operation://{WORKSPACE_ID}/"
                            "promotion_execute_dry_run/"
                            f"{request_fragment}"
                        ),
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
            ),
            encoding="utf-8",
        )
        return (
            confirmation_ref,
            state_contracts.content_sha256(
                json.loads(confirmation_path.read_text(encoding="utf-8"))
            ),
        )

    def request(self, operation_id: str) -> dict:
        definition = contracts.operation_by_id(operation_id)
        assert definition is not None
        if operation_id == "workspace_initialization_execute":
            planned = binding("planned")
            input_ref = definition.input_refs[0]
            input_path = self.path_for_ref(input_ref)
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_path.write_text(
                json.dumps({"workspace_binding": planned}), encoding="utf-8"
            )
            binding_path = input_path
            selected_binding = planned
            binding_ref = f"runs/{WORKSPACE_ID}/{input_path.name}"
            inputs = {input_ref: input_path}
        else:
            selected_binding = binding()
            binding_path = self.binding_path
            binding_ref = BINDING_REF
            inputs = {
                ref: self.write_input(ref, operation_id, index)
                for index, ref in enumerate(definition.input_refs)
                if ref not in definition.conditional_input_refs
            }
        operator_ref = (
            "operator://tests-executor"
            if definition.requires_explicit_confirmation
            else None
        )
        confirmation_ref = None
        confirmation_sha256 = None
        binding_source_sha256 = hashlib.sha256(binding_path.read_bytes()).hexdigest()
        if definition.requires_explicit_confirmation:
            confirmation_ref, confirmation_sha256 = (
                self.write_promotion_review_confirmation(
                    inputs=inputs,
                    binding_source_sha256=binding_source_sha256,
                    operator_ref=str(operator_ref),
                )
            )
        request = contracts.build_request(
            operation_id=operation_id,
            workspace_binding=selected_binding,
            workspace_binding_ref=binding_ref,
            workspace_binding_source_sha256=binding_source_sha256,
            inputs=inputs,
            generated_at="2026-07-10T00:00:00Z",
            operator_ref=operator_ref,
            confirmation_ref=confirmation_ref,
            confirmation_sha256=confirmation_sha256,
            confirmation_revision=2 if confirmation_ref is not None else None,
            confirmation_lifecycle_state=(
                "consumed" if confirmation_ref is not None else None
            ),
        )
        if confirmation_ref is not None:
            confirmation_path = self.path_for_ref(confirmation_ref)
            record_key = confirmation_ref.removeprefix("specspace-state://")
            self.confirmation_records[record_key] = {
                "workspace_id": WORKSPACE_ID,
                "record_key": record_key,
                "revision": 2,
                "content_sha256": confirmation_sha256,
                "lifecycle_state": "consumed",
                "idempotency_key": (
                    "promotion-review-consume:" + request["idempotency_key"]
                ),
                "content": json.loads(
                    confirmation_path.read_text(encoding="utf-8")
                ),
            }
        return request

    def resolver(
        self,
        *,
        now_iso: str = "2026-07-10T00:05:00Z",
    ) -> executor_module.FilesystemManagedOperationResolver:
        return executor_module.FilesystemManagedOperationResolver(
            artifact_root=self.artifact_root,
            state_dir=self.state_dir,
            specgraph_dir=self.specgraph_dir,
            binding_validator=lambda selected, workspace_id: []
            if selected.get("identity", {}).get("workspace_id") == workspace_id
            else ["workspace mismatch"],
            now_iso=lambda: now_iso,
            confirmation_record_reader=lambda workspace_id, record_key: (
                self.confirmation_records[record_key]
            ),
        )


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.timeouts: list[int] = []

    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        self.timeouts.append(timeout_seconds)
        output_flags = {"--output", "--output-gate", "--gate-output", "--decision-output", "--git-service-output"}
        for index, item in enumerate(command[:-1]):
            if item not in output_flags:
                continue
            path = Path(command[index + 1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"artifact_kind": f"test_output_{path.stem}", "ok": True}),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")


class HostedManagedOperationExecutorTests(unittest.TestCase):
    def test_fixed_command_adapter_covers_all_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(),
                platform_script=fixture.platform_script,
            )
            command_families = {}
            for definition in contracts.MANAGED_OPERATIONS:
                request = fixture.request(definition.operation_id)
                self.assertEqual(request["status"], "ready", request["diagnostics"])
                resolved = fixture.resolver().resolve(request)
                commands = executor.build_commands(resolved)
                command_families[definition.operation_id] = commands
                self.assertTrue(commands)
                self.assertTrue(
                    all(
                        command[:2]
                        == [sys.executable, str(fixture.platform_script.resolve())]
                        for command in commands
                    )
                )

        self.assertEqual(set(command_families), {item.operation_id for item in contracts.MANAGED_OPERATIONS})
        self.assertIn("--dry-run", command_families["promotion_execute_dry_run"][0])
        self.assertNotIn("--dry-run", command_families["promotion_review_execute"][0])
        dry_run_command = command_families["promotion_execute_dry_run"][0]
        plan_index = dry_run_command.index("--plan")
        self.assertEqual(
            Path(dry_run_command[plan_index + 1]).name,
            "graph_repository_execution_plan.json",
        )
        self.assertIn(
            "runs/graph_repository_execution_plan.json",
            contracts.operation_by_id("promotion_execute_dry_run").input_refs,
        )
        output_path = Path(
            dry_run_command[dry_run_command.index("--output") + 1]
        )
        git_service_output_path = Path(
            dry_run_command[dry_run_command.index("--git-service-output") + 1]
        )
        self.assertEqual(output_path.parent.name, "managed-promotion-dry-runs")
        self.assertEqual(
            git_service_output_path.parent,
            output_path.parent,
        )
        self.assertRegex(
            output_path.name,
            r"^[0-9a-f]{24}\.product_candidate_promotion_execution_report\.json$",
        )
        self.assertRegex(
            git_service_output_path.name,
            r"^[0-9a-f]{24}\.git_service_promotion_execution_report\.json$",
        )
        review_command = command_families["promotion_review_execute"][0]
        self.assertEqual(
            Path(review_command[review_command.index("--output") + 1]).name,
            "product_candidate_promotion_execution_report.json",
        )
        self.assertEqual(len(command_families["repair_rerun_execute"]), 2)

    def test_worker_executes_fixed_wrapper_and_pins_output_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("review_status_execute")
            runner = RecordingRunner()
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(),
                platform_script=fixture.platform_script,
                runner=runner,
            )
            leased = queue_module.LeasedOperation(
                request_id=request["request_id"],
                request=request,
                attempt=1,
                lease_owner="worker-a",
                lease_expires_at=200,
            )

            result = executor.execute(leased)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(result.output_reports), 1)
        self.assertEqual(len(runner.commands), 1)
        self.assertEqual(
            result.output_reports[0]["logical_ref"],
            "runs/product_candidate_promotion_review_status_report.json",
        )

    def test_review_status_passes_optional_review_object_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            definition = contracts.operation_by_id("review_status_execute")
            assert definition is not None
            execution_ref = "runs/product_candidate_promotion_execution_report.json"
            evidence_ref = (
                "runs/product_candidate_promotion_review_object_evidence.json"
            )
            execution_path = fixture.write_input(execution_ref, "review_status_execute", 0)
            evidence_path = fixture.write_input(evidence_ref, "review_status_execute", 1)
            request = contracts.build_request(
                operation_id="review_status_execute",
                workspace_binding=binding(),
                workspace_binding_ref=BINDING_REF,
                workspace_binding_source_sha256=hashlib.sha256(
                    fixture.binding_path.read_bytes()
                ).hexdigest(),
                inputs={execution_ref: execution_path, evidence_ref: evidence_path},
                generated_at="2026-07-10T00:00:00Z",
            )
            runner = RecordingRunner()
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(),
                platform_script=fixture.platform_script,
                runner=runner,
            )
            result = executor.execute(
                queue_module.LeasedOperation(
                    request_id=request["request_id"],
                    request=request,
                    attempt=1,
                    lease_owner="worker-a",
                    lease_expires_at=200,
                )
            )

        self.assertEqual(result.status, "succeeded")
        self.assertIn("--review-object-evidence", runner.commands[0])

    def test_worker_window_caps_request_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("review_status_execute")
            runner = RecordingRunner()
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(),
                platform_script=fixture.platform_script,
                runner=runner,
                maximum_timeout_seconds=60,
            )
            leased = queue_module.LeasedOperation(
                request_id=request["request_id"],
                request=request,
                attempt=1,
                lease_owner="bounded-worker-a",
                lease_expires_at=1000,
            )

            result = executor.execute(leased)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(runner.timeouts, [60])

    def test_input_digest_drift_is_quarantined_before_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("review_status_execute")
            input_path = fixture.path_for_ref(
                "runs/product_candidate_promotion_execution_report.json"
            )
            input_path.write_text('{"changed": true}', encoding="utf-8")
            runner = RecordingRunner()
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(),
                platform_script=fixture.platform_script,
                runner=runner,
            )
            leased = queue_module.LeasedOperation(
                request_id=request["request_id"],
                request=request,
                attempt=1,
                lease_owner="worker-a",
                lease_expires_at=200,
            )

            result = executor.execute(leased)

        self.assertEqual(result.status, "quarantined")
        self.assertEqual(runner.commands, [])
        self.assertNotIn(str(input_path), json.dumps(result.diagnostics))

    def test_binding_digest_drift_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("review_status_execute")
            fixture.binding_path.write_text("{}", encoding="utf-8")
            runner = RecordingRunner()
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(),
                platform_script=fixture.platform_script,
                runner=runner,
            )
            leased = queue_module.LeasedOperation(
                request_id=request["request_id"],
                request=request,
                attempt=1,
                lease_owner="worker-a",
                lease_expires_at=200,
            )

            result = executor.execute(leased)

        self.assertEqual(result.status, "quarantined")
        self.assertEqual(runner.commands, [])

    def test_confirmation_digest_drift_blocks_git_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("promotion_review_execute")
            confirmation_ref = request["confirmation"]["logical_ref"]
            confirmation_path = fixture.path_for_ref(confirmation_ref)
            confirmation_path.write_text('{"confirmed": false}', encoding="utf-8")
            runner = RecordingRunner()
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(),
                platform_script=fixture.platform_script,
                runner=runner,
            )
            leased = queue_module.LeasedOperation(
                request_id=request["request_id"],
                request=request,
                attempt=1,
                lease_owner="worker-a",
                lease_expires_at=200,
            )

            result = executor.execute(leased)

        self.assertEqual(result.status, "quarantined")
        self.assertEqual(runner.commands, [])

    def test_semantically_invalid_pinned_confirmation_blocks_git_review(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("promotion_review_execute")
            confirmation_ref = request["confirmation"]["logical_ref"]
            confirmation_path = fixture.path_for_ref(confirmation_ref)
            confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
            confirmation["confirmed"] = False
            confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")
            definition = contracts.operation_by_id("promotion_review_execute")
            assert definition is not None
            rebuilt_request = contracts.build_request(
                operation_id=definition.operation_id,
                workspace_binding=binding(),
                workspace_binding_ref=BINDING_REF,
                workspace_binding_source_sha256=hashlib.sha256(
                    fixture.binding_path.read_bytes()
                ).hexdigest(),
                inputs={
                    ref: fixture.path_for_ref(ref)
                    for ref in definition.input_refs
                },
                generated_at="2026-07-10T00:00:00Z",
                operator_ref="operator://tests-executor",
                confirmation_ref=confirmation_ref,
                confirmation_sha256=state_contracts.content_sha256(
                    confirmation
                ),
                confirmation_revision=2,
                confirmation_lifecycle_state="consumed",
            )
            self.assertEqual(rebuilt_request["status"], "ready")
            record_key = confirmation_ref.removeprefix("specspace-state://")
            fixture.confirmation_records[record_key] = {
                **fixture.confirmation_records[record_key],
                "content_sha256": rebuilt_request["confirmation"]["sha256"],
                "idempotency_key": (
                    "promotion-review-consume:"
                    + rebuilt_request["idempotency_key"]
                ),
                "content": confirmation,
            }
            runner = RecordingRunner()
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(),
                platform_script=fixture.platform_script,
                runner=runner,
            )
            leased = queue_module.LeasedOperation(
                request_id=rebuilt_request["request_id"],
                request=rebuilt_request,
                attempt=1,
                lease_owner="worker-a",
                lease_expires_at=200,
            )

            result = executor.execute(leased)

        self.assertEqual(result.status, "quarantined")
        self.assertEqual(runner.commands, [])

    def test_forged_consumed_request_without_state_cas_blocks_git_review(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("promotion_review_execute")
            record_key = str(request["confirmation"]["logical_ref"]).removeprefix(
                "specspace-state://"
            )
            fixture.confirmation_records[record_key]["lifecycle_state"] = "active"
            runner = RecordingRunner()
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(),
                platform_script=fixture.platform_script,
                runner=runner,
            )
            leased = queue_module.LeasedOperation(
                request_id=request["request_id"],
                request=request,
                attempt=1,
                lease_owner="worker-a",
                lease_expires_at=200,
            )

            result = executor.execute(leased)

        self.assertEqual(result.status, "quarantined")
        self.assertEqual(runner.commands, [])

    def test_confirmation_expired_while_queued_blocks_git_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ExecutorFixture(Path(temp_dir))
            request = fixture.request("promotion_review_execute")
            runner = RecordingRunner()
            executor = executor_module.PlatformManagedOperationExecutor(
                resolver=fixture.resolver(now_iso="2026-07-10T00:16:00Z"),
                platform_script=fixture.platform_script,
                runner=runner,
            )
            leased = queue_module.LeasedOperation(
                request_id=request["request_id"],
                request=request,
                attempt=1,
                lease_owner="worker-a",
                lease_expires_at=200,
            )

            result = executor.execute(leased)

        self.assertEqual(result.status, "quarantined")
        self.assertEqual(runner.commands, [])

    def test_cli_worker_reports_idle_without_executing_platform(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            artifact_root = temp / "artifacts"
            state_dir = temp / "state"
            specgraph_dir = temp / "SpecGraph"
            artifact_root.mkdir()
            state_dir.mkdir()
            specgraph_dir.mkdir()
            (specgraph_dir / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
            database = temp / "queue.sqlite3"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "platform.py"),
                    "managed-operation",
                    "worker-once",
                    "--database",
                    str(database),
                    "--artifact-root",
                    str(artifact_root),
                    "--state-dir",
                    str(state_dir),
                    "--specgraph-dir",
                    str(specgraph_dir),
                    "--worker-id",
                    "worker-test",
                    "--operation-allowlist",
                    "review_status_execute",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(
            report["summary"]["status"],
            "hosted_managed_operation_worker_idle",
        )
        self.assertFalse(report["summary"]["operation_processed"])

    def test_cli_worker_requires_state_service_for_promotion_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            artifact_root = temp / "artifacts"
            state_dir = temp / "state"
            specgraph_dir = temp / "SpecGraph"
            artifact_root.mkdir()
            state_dir.mkdir()
            specgraph_dir.mkdir()
            (specgraph_dir / "Makefile").write_text(
                "test:\n\t@true\n",
                encoding="utf-8",
            )
            database = temp / "queue.sqlite3"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "platform.py"),
                    "managed-operation",
                    "worker-once",
                    "--database",
                    str(database),
                    "--artifact-root",
                    str(artifact_root),
                    "--state-dir",
                    str(state_dir),
                    "--specgraph-dir",
                    str(specgraph_dir),
                    "--worker-id",
                    "worker-test",
                    "--operation-allowlist",
                    "promotion_review_execute",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn(
            "requires --specspace-state-service-url",
            completed.stderr,
        )
        self.assertFalse(database.exists())

    def test_worker_resolver_reads_consumed_confirmation_over_state_service(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fixture = ExecutorFixture(temp)
            request = fixture.request("promotion_review_execute")
            confirmation_ref = request["confirmation"]["logical_ref"]
            confirmation_key = confirmation_ref.removeprefix(
                "specspace-state://"
            )
            confirmation = json.loads(
                fixture.path_for_ref(confirmation_ref).read_text(encoding="utf-8")
            )
            state_service = specspace_state_service.SpecSpaceStateService(
                store_factory=lambda: state_contracts.SQLiteSpecSpaceStateStore(
                    temp / "state.sqlite3"
                ),
                adapter="sqlite",
                mirror_root=fixture.state_dir,
                now_iso=lambda: "2026-07-10T00:05:00Z",
            )
            created = state_service.mutate(
                {
                    "workspace_id": WORKSPACE_ID,
                    "record_key": confirmation_key,
                    "expected_revision": 0,
                    "idempotency_key": "confirmation-create:worker-http:0001",
                    "lifecycle_state": "active",
                    "content": confirmation,
                }
            )
            state_service.consume_confirmation(
                {
                    "workspace_id": WORKSPACE_ID,
                    "record_key": confirmation_key,
                    "expected_revision": 1,
                    "expected_content_sha256": created["record"][
                        "content_sha256"
                    ],
                    "operation_id": "promotion_review_execute",
                    "request_identity_sha256": request["idempotency_key"],
                }
            )
            confirmation_token = "worker-confirmation-token-0123456789abcdef"
            server = specspace_state_service.create_server(
                host="127.0.0.1",
                port=0,
                service=state_service,
                auth_token="worker-primary-state-token-0123456789abcdef",
                confirmation_token=confirmation_token,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            args = SimpleNamespace(
                artifact_root=str(fixture.artifact_root),
                state_dir=str(fixture.state_dir),
                specgraph_dir=str(fixture.specgraph_dir),
                specspace_state_service_url=(
                    f"http://127.0.0.1:{server.server_address[1]}"
                ),
                specspace_state_confirmation_token_env=(
                    "PLATFORM_TEST_SPECSPACE_CONFIRMATION_TOKEN"
                ),
                specspace_state_confirmation_token_file=None,
                specspace_state_timeout_seconds=5.0,
                allow_insecure_specspace_state_http=False,
            )
            try:
                with (
                    mock.patch.dict(
                        os.environ,
                        {
                            "PLATFORM_TEST_SPECSPACE_CONFIRMATION_TOKEN": (
                                confirmation_token
                            )
                        },
                    ),
                    mock.patch.object(
                        platform,
                        "product_workspace_binding_diagnostics",
                        return_value=[],
                    ),
                ):
                    executor = platform._managed_operation_executor(
                        args,
                        allowed_operation_ids=frozenset(
                            {"promotion_review_execute"}
                        ),
                    )
                    executor.resolver.now_iso = lambda: "2026-07-10T00:05:00Z"
                    resolved = executor.resolver.resolve(request)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(resolved.workspace_id, WORKSPACE_ID)
        self.assertEqual(
            resolved.confirmation_path.name,
            confirmation_key.rsplit("/", 1)[1],
        )

    def test_continuous_worker_writes_non_secret_health_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            artifact_root = temp / "artifacts"
            state_dir = temp / "state"
            specgraph_dir = temp / "SpecGraph"
            artifact_root.mkdir()
            state_dir.mkdir()
            specgraph_dir.mkdir()
            (specgraph_dir / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
            database = temp / "queue.sqlite3"
            health_file = temp / "worker-health.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "platform.py"),
                    "managed-operation",
                    "worker",
                    "--database",
                    str(database),
                    "--artifact-root",
                    str(artifact_root),
                    "--state-dir",
                    str(state_dir),
                    "--specgraph-dir",
                    str(specgraph_dir),
                    "--worker-id",
                    "worker-test",
                    "--operation-allowlist",
                    "review_status_execute",
                    "--max-cycles",
                    "1",
                    "--health-file",
                    str(health_file),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            health = json.loads(health_file.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(health["ok"])
        self.assertEqual(health["adapter"], "sqlite")
        self.assertGreaterEqual(health["heartbeat_sequence"], 2)
        self.assertNotIn(str(database), json.dumps(health))

    def test_worker_heartbeat_advances_while_cycle_is_busy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            health_file = Path(temp_dir) / "worker-health.json"
            args = SimpleNamespace(
                health_file=str(health_file),
                worker_id="worker-test",
                queue_adapter="postgresql",
            )
            heartbeat = platform._ManagedOperationWorkerHeartbeat(
                args,
                interval_seconds=0.01,
            )
            heartbeat.start()
            time.sleep(0.055)
            heartbeat.stop()
            health = json.loads(health_file.read_text(encoding="utf-8"))

        self.assertGreaterEqual(health["heartbeat_sequence"], 3)
        self.assertEqual(
            health["last_cycle_status"],
            "hosted_managed_operation_worker_starting",
        )


if __name__ == "__main__":
    unittest.main()
