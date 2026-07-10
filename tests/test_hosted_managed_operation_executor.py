from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import hosted_managed_operation_executor as executor_module
import hosted_managed_operation_queue as queue_module
import hosted_managed_operations as contracts


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
        confirmation_ref = (
            "specspace-state://promotion-review-confirmation.json"
            if definition.requires_explicit_confirmation
            else None
        )
        confirmation_sha256 = None
        if confirmation_ref is not None:
            confirmation_path = self.path_for_ref(confirmation_ref)
            confirmation_path.write_text(
                json.dumps({"confirmed": True, "workspace_id": WORKSPACE_ID}),
                encoding="utf-8",
            )
            confirmation_sha256 = hashlib.sha256(
                confirmation_path.read_bytes()
            ).hexdigest()
        return contracts.build_request(
            operation_id=operation_id,
            workspace_binding=selected_binding,
            workspace_binding_ref=binding_ref,
            workspace_binding_source_sha256=hashlib.sha256(
                binding_path.read_bytes()
            ).hexdigest(),
            inputs=inputs,
            generated_at="2026-07-10T00:00:00Z",
            confirmation_ref=confirmation_ref,
            confirmation_sha256=confirmation_sha256,
        )

    def resolver(self) -> executor_module.FilesystemManagedOperationResolver:
        return executor_module.FilesystemManagedOperationResolver(
            artifact_root=self.artifact_root,
            state_dir=self.state_dir,
            specgraph_dir=self.specgraph_dir,
            binding_validator=lambda selected, workspace_id: []
            if selected.get("identity", {}).get("workspace_id") == workspace_id
            else ["workspace mismatch"],
        )


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
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
            confirmation_path = fixture.path_for_ref(
                "specspace-state://promotion-review-confirmation.json"
            )
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


if __name__ == "__main__":
    unittest.main()
