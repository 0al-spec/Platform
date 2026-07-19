from __future__ import annotations

from copy import deepcopy
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

import hosted_managed_operations as hosted
from scripts import platform


def ready_binding() -> dict[str, object]:
    return {
        "artifact_kind": "platform_product_workspace_binding",
        "schema_version": 1,
        "contract_ref": "platform.product-workspace.binding.v1",
        "binding_id": "product-workspace-binding://pantry-control",
        "binding_revision_sha256": "1" * 64,
        "status": "ready",
        "identity": {
            "workspace_id": "pantry-control",
            "route": "/pantry-control",
        },
    }


def planned_binding() -> dict[str, object]:
    binding = ready_binding()
    binding["status"] = "planned"
    return binding


class HostedManagedOperationContractTests(unittest.TestCase):
    def test_registry_covers_all_managed_operations(self) -> None:
        payload = hosted.registry_payload()
        operation_ids = [item["operation_id"] for item in payload["operations"]]

        self.assertEqual(payload["contract_ref"], hosted.REGISTRY_CONTRACT_REF)
        self.assertEqual(len(operation_ids), 12)
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertEqual(payload["delivery_semantics"], "at_least_once")
        self.assertTrue(
            all(
                item["side_effect_class"] in hosted.SIDE_EFFECT_CLASSES
                and item["lock_scopes"]
                and item["output_reports"]
                for item in payload["operations"]
            )
        )
        approval = hosted.operation_by_id("candidate_approval_execute")
        self.assertIn(
            "runs/repaired_candidate_promotion_handoff_report.json",
            approval.conditional_input_refs,
        )
        initialization = hosted.operation_by_id("workspace_initialization_execute")
        self.assertEqual(initialization.binding_requirement, "planned_or_ready")
        repair = hosted.operation_by_id("repair_rerun_execute")
        self.assertEqual(
            repair.platform_command,
            ("product-repair-rerun", "execute"),
        )
        promotion_dry_run = hosted.operation_by_id("promotion_execute_dry_run")
        promotion_review = hosted.operation_by_id("promotion_review_execute")
        self.assertEqual(
            promotion_dry_run.output_reports,
            (
                hosted.PROMOTION_DRY_RUN_EXECUTION_OUTPUT_REF,
                hosted.PROMOTION_DRY_RUN_GIT_SERVICE_OUTPUT_REF,
            ),
        )
        self.assertTrue(
            set(promotion_dry_run.output_reports).isdisjoint(
                promotion_review.output_reports
            )
        )
        self.assertTrue(
            all(
                operation.binding_requirement == "ready"
                for operation in hosted.MANAGED_OPERATIONS
                if operation.operation_id != "workspace_initialization_execute"
            )
        )

    def test_only_workspace_initialization_accepts_planned_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            initialization_input = temp / "initialization-request.json"
            initialization_input.write_text("{}", encoding="utf-8")
            initialization = hosted.build_request(
                operation_id="workspace_initialization_execute",
                workspace_binding=planned_binding(),
                workspace_binding_ref="runs/product_workspace_initialization_execution_request.json",
                workspace_binding_source_sha256="2" * 64,
                inputs={
                    "runs/product_workspace_initialization_execution_request.json": initialization_input
                },
                generated_at="2026-07-10T00:00:00Z",
            )
            review_input = temp / "review.json"
            review_input.write_text("{}", encoding="utf-8")
            review = hosted.build_request(
                operation_id="review_status_execute",
                workspace_binding=planned_binding(),
                workspace_binding_ref="runs/product_workspace_initialization_execution_request.json",
                workspace_binding_source_sha256="2" * 64,
                inputs={
                    "runs/product_candidate_promotion_execution_report.json": review_input
                },
                generated_at="2026-07-10T00:00:00Z",
            )

        self.assertEqual(initialization["status"], "ready")
        self.assertEqual(hosted.request_diagnostics(initialization), [])
        self.assertEqual(review["status"], "blocked")
        self.assertIn(
            "workspace binding status does not satisfy the operation requirement",
            review["diagnostics"],
        )

    def test_request_pins_inputs_without_exposing_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "execution.json"
            input_path.write_text(
                json.dumps(
                    {
                        "artifact_kind": "platform_product_repair_rerun_execution_report",
                        "ok": True,
                    }
                ),
                encoding="utf-8",
            )
            payload = hosted.build_request(
                operation_id="repair_rerun_publish",
                workspace_binding=ready_binding(),
                workspace_binding_ref="runs/platform_product_workspace_initialization_execution_report.json",
                workspace_binding_source_sha256="2" * 64,
                inputs={
                    "runs/platform_product_repair_rerun_execution_report.json": input_path
                },
                generated_at="2026-07-10T00:00:00Z",
                operator_ref="operator://specspace-local",
            )

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(hosted.request_diagnostics(payload), [])
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(temp_dir, serialized)
        self.assertNotIn(str(input_path), serialized)
        self.assertEqual(payload["inputs"][0]["media_type"], "application/json")
        self.assertEqual(
            payload["inputs"][0]["artifact_kind"],
            "platform_product_repair_rerun_execution_report",
        )

    def test_operator_ref_distinguishes_only_replay_safe_execution_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            review_input = temp / "promotion.json"
            review_input.write_text("{}", encoding="utf-8")
            review_inputs = {
                "runs/product_candidate_promotion_execution_report.json": review_input
            }
            first_review = hosted.build_request(
                operation_id="review_status_execute",
                workspace_binding=ready_binding(),
                workspace_binding_ref="runs/initialization.json",
                workspace_binding_source_sha256="2" * 64,
                inputs=review_inputs,
                generated_at="2026-07-10T00:00:00Z",
                operator_ref="operator://specspace-action-a",
            )
            second_review = hosted.build_request(
                operation_id="review_status_execute",
                workspace_binding=ready_binding(),
                workspace_binding_ref="runs/initialization.json",
                workspace_binding_source_sha256="2" * 64,
                inputs=review_inputs,
                generated_at="2026-07-10T00:00:01Z",
                operator_ref="operator://specspace-action-b",
            )

            intake_inputs: dict[str, Path] = {}
            for index, ref in enumerate(
                hosted.operation_by_id("real_idea_intake_execute").input_refs
            ):
                path = temp / f"intake-{index}.json"
                path.write_text("{}", encoding="utf-8")
                intake_inputs[ref] = path
            first_intake = hosted.build_request(
                operation_id="real_idea_intake_execute",
                workspace_binding=ready_binding(),
                workspace_binding_ref="runs/initialization.json",
                workspace_binding_source_sha256="2" * 64,
                inputs=intake_inputs,
                generated_at="2026-07-10T00:00:00Z",
                operator_ref="operator://specspace-action-a",
            )
            second_intake = hosted.build_request(
                operation_id="real_idea_intake_execute",
                workspace_binding=ready_binding(),
                workspace_binding_ref="runs/initialization.json",
                workspace_binding_source_sha256="2" * 64,
                inputs=intake_inputs,
                generated_at="2026-07-10T00:00:01Z",
                operator_ref="operator://specspace-action-b",
            )

        self.assertNotEqual(
            first_review["idempotency_key"], second_review["idempotency_key"]
        )
        self.assertEqual(hosted.request_diagnostics(first_review), [])
        self.assertEqual(hosted.request_diagnostics(second_review), [])
        self.assertEqual(
            first_intake["idempotency_key"], second_intake["idempotency_key"]
        )

    def test_promotion_dry_run_request_materializes_request_scoped_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            inputs: dict[str, Path] = {}
            definition = hosted.operation_by_id("promotion_execute_dry_run")
            assert definition is not None
            for index, ref in enumerate(definition.input_refs):
                path = temp / f"input-{index}.json"
                path.write_text("{}", encoding="utf-8")
                inputs[ref] = path
            request = hosted.build_request(
                operation_id="promotion_execute_dry_run",
                workspace_binding=ready_binding(),
                workspace_binding_ref="runs/initialization.json",
                workspace_binding_source_sha256="2" * 64,
                inputs=inputs,
                generated_at="2026-07-10T00:00:00Z",
                operator_ref="operator://specspace-dry-run",
            )

        request_fragment = request["request_id"].rsplit("/", 1)[-1]
        self.assertEqual(
            request["expected_output_reports"],
            [
                "runs/managed-promotion-dry-runs/"
                f"{request_fragment}."
                "product_candidate_promotion_execution_report.json",
                "runs/managed-promotion-dry-runs/"
                f"{request_fragment}."
                "git_service_promotion_execution_report.json",
            ],
        )
        self.assertNotIn(
            "runs/product_candidate_promotion_execution_report.json",
            request["expected_output_reports"],
        )

    def test_request_rejects_registry_and_idempotency_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "execution.json"
            input_path.write_text("{}", encoding="utf-8")
            payload = hosted.build_request(
                operation_id="repair_rerun_publish",
                workspace_binding=ready_binding(),
                workspace_binding_ref="runs/initialization.json",
                workspace_binding_source_sha256="2" * 64,
                inputs={
                    "runs/platform_product_repair_rerun_execution_report.json": input_path
                },
                generated_at="2026-07-10T00:00:00Z",
            )

        tampered = deepcopy(payload)
        tampered["operation"]["platform_command"] = ["workspace", "init"]
        tampered["idempotency_key"] = "3" * 64
        diagnostics = hosted.request_diagnostics(tampered)

        self.assertIn(
            "request operation definition does not match the operation registry",
            diagnostics,
        )
        self.assertIn(
            "request idempotency key does not match pinned inputs",
            diagnostics,
        )

    def test_irreversible_operation_requires_confirmation_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            inputs = {}
            for ref in hosted.operation_by_id("promotion_review_execute").input_refs:
                path = temp / f"{len(inputs)}.json"
                path.write_text("{}", encoding="utf-8")
                inputs[ref] = path
            payload = hosted.build_request(
                operation_id="promotion_review_execute",
                workspace_binding=ready_binding(),
                workspace_binding_ref="runs/initialization.json",
                workspace_binding_source_sha256="2" * 64,
                inputs=inputs,
                generated_at="2026-07-10T00:00:00Z",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertIn(
            "operation requires digest-pinned confirmation evidence",
            payload["diagnostics"],
        )

    def test_request_rejects_extra_authority_and_private_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "execution.json"
            input_path.write_text("{}", encoding="utf-8")
            payload = hosted.build_request(
                operation_id="repair_rerun_publish",
                workspace_binding=ready_binding(),
                workspace_binding_ref="runs/initialization.json",
                workspace_binding_source_sha256="2" * 64,
                inputs={
                    "runs/platform_product_repair_rerun_execution_report.json": input_path
                },
                generated_at="2026-07-10T00:00:00Z",
            )

        payload["raw_idea"] = "private text"
        payload["nested"] = {"may_execute_platform": True}
        diagnostics = hosted.request_diagnostics(payload)
        self.assertTrue(
            any("outside the v1 contract" in item for item in diagnostics)
        )
        self.assertTrue(any("expands authority" in item for item in diagnostics))

    def test_transport_receipt_does_not_replace_platform_evidence(self) -> None:
        request = {
            "request_id": "managed-operation://pantry-control/review_status_execute/abc",
            "idempotency_key": "4" * 64,
            "operation": {"operation_id": "review_status_execute"},
            "workspace": {"workspace_id": "pantry-control"},
        }
        receipt = hosted.build_receipt(
            request=request,
            status="succeeded",
            generated_at="2026-07-10T00:00:00Z",
            attempt=1,
            output_reports=(
                {
                    "logical_ref": "runs/product_candidate_promotion_review_status_report.json",
                    "sha256": "5" * 64,
                },
            ),
        )

        self.assertEqual(hosted.receipt_diagnostics(receipt), [])
        self.assertFalse(
            receipt["authority_boundary"]["transport_status_is_lifecycle_evidence"]
        )
        self.assertTrue(
            receipt["authority_boundary"]["platform_output_reports_are_authoritative"]
        )

    def test_succeeded_receipt_requires_the_registered_output_report_set(self) -> None:
        request = {
            "request_id": "managed-operation://pantry-control/repair_rerun_execute/abc",
            "idempotency_key": "4" * 64,
            "operation": {"operation_id": "repair_rerun_execute"},
            "workspace": {"workspace_id": "pantry-control"},
        }
        receipt = hosted.build_receipt(
            request=request,
            status="succeeded",
            generated_at="2026-07-10T00:00:00Z",
            attempt=1,
            output_reports=(
                {
                    "logical_ref": "runs/platform_product_repair_rerun_execution_report.json",
                    "sha256": "5" * 64,
                },
                {
                    "logical_ref": "runs/unrelated.json",
                    "sha256": "6" * 64,
                },
            ),
        )

        diagnostics = hosted.receipt_diagnostics(receipt)

        self.assertIn(
            "succeeded receipt is missing expected output report: "
            "runs/managed_repair_rerun_plans/<request-id>."
            "platform_product_repair_rerun_execution_plan.json",
            diagnostics,
        )
        self.assertIn(
            "succeeded receipt cites unexpected output report: runs/unrelated.json",
            diagnostics,
        )

        receipt["output_reports"][1] = {
            "logical_ref": (
                "runs/managed_repair_rerun_plans/request-42."
                "platform_product_repair_rerun_execution_plan.json"
            ),
            "sha256": "6" * 64,
        }
        self.assertEqual(hosted.receipt_diagnostics(receipt), [])

    def test_queued_receipt_has_no_execution_attempt_yet(self) -> None:
        request = {
            "request_id": "managed-operation://pantry-control/review_status_execute/abc",
            "idempotency_key": "4" * 64,
            "operation": {"operation_id": "review_status_execute"},
            "workspace": {"workspace_id": "pantry-control"},
        }
        receipt = hosted.build_receipt(
            request=request,
            status="queued",
            generated_at="2026-07-10T00:00:00Z",
            attempt=0,
        )

        self.assertEqual(hosted.receipt_diagnostics(receipt), [])

    def test_cli_exposes_versioned_registry(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "platform.py"),
                "managed-operation",
                "contract",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["operation_count"], 12)
        self.assertEqual(payload["contract_ref"], hosted.REGISTRY_CONTRACT_REF)

    def test_cli_materializes_queue_safe_request_from_ready_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            binding = platform.product_workspace_initialization_binding(
                workspace_id="pantry-control",
                display_name="Pantry Control",
                route="/pantry-control",
                workspace_root=temp / "PantryControl",
                governance_profile="product_workspace",
                artifact_base_url="https://specgraph.tech",
                status="ready",
                plan_ref="runs/pantry-control/initialization-plan.json",
                plan_sha256="1" * 64,
                specgraph_initialization_report_ref=(
                    "runs/pantry-control/product_workspace_initialization.json"
                ),
                specgraph_initialization_report_sha256="2" * 64,
            )
            binding_path = temp / "initialization.json"
            binding_path.write_text(
                json.dumps({"workspace_binding": binding}),
                encoding="utf-8",
            )
            input_path = temp / "execution.json"
            input_path.write_text(
                json.dumps(
                    {
                        "artifact_kind": "platform_product_repair_rerun_execution_report"
                    }
                ),
                encoding="utf-8",
            )
            output_path = temp / "request.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "platform.py"),
                    "managed-operation",
                    "request",
                    "--operation-id",
                    "repair_rerun_publish",
                    "--workspace-binding",
                    str(binding_path),
                    "--workspace-binding-ref",
                    "runs/platform_product_workspace_initialization_execution_report.json",
                    "--input",
                    (
                        "runs/platform_product_repair_rerun_execution_report.json="
                        f"{input_path}"
                    ),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(hosted.request_diagnostics(payload), [])
            self.assertNotIn(temp_dir, json.dumps(payload))

    def test_cli_materializes_initialization_request_from_planned_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            binding = platform.product_workspace_initialization_binding(
                workspace_id="pantry-control",
                display_name="Pantry Control",
                route="/pantry-control",
                workspace_root=temp / "PantryControl",
                governance_profile="product_workspace",
                artifact_base_url="https://specgraph.tech",
                status="planned",
                plan_ref="runs/pantry-control/initialization-plan.json",
                plan_sha256="1" * 64,
            )
            binding_path = temp / "initialization-plan.json"
            binding_path.write_text(
                json.dumps({"workspace_binding": binding}),
                encoding="utf-8",
            )
            execution_request = temp / "initialization-request.json"
            execution_request.write_text("{}", encoding="utf-8")
            output_path = temp / "hosted-request.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "platform.py"),
                    "managed-operation",
                    "request",
                    "--operation-id",
                    "workspace_initialization_execute",
                    "--workspace-binding",
                    str(binding_path),
                    "--workspace-binding-ref",
                    "runs/product_workspace_initialization_execution_plan.json",
                    "--input",
                    (
                        "runs/product_workspace_initialization_execution_request.json="
                        f"{execution_request}"
                    ),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(payload["workspace_binding"]["status"], "planned")
            self.assertEqual(hosted.request_diagnostics(payload), [])

    def test_missing_input_diagnostic_does_not_expose_local_path(self) -> None:
        missing_path = Path("/Users/private/raw-idea.json")
        payload = hosted.build_request(
            operation_id="repair_rerun_publish",
            workspace_binding=ready_binding(),
            workspace_binding_ref="runs/initialization.json",
            workspace_binding_source_sha256="2" * 64,
            inputs={
                "runs/platform_product_repair_rerun_execution_report.json": missing_path
            },
            generated_at="2026-07-10T00:00:00Z",
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertNotIn("/Users/private", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
