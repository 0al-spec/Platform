import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from tests.platform_fixtures import workspace_creation_request


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "platform.py"


CATALOG = """\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "${ORG_ROOT}"
workspaces:
  - project_id: specgraph-core
    display_name: SpecGraph Core
    kind: core_repository
    status: active
    path: "${ORG_ROOT}/SpecGraph"
    governance_profile: self_hosted_bootstrap
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
  - project_id: product-a
    display_name: Product A
    kind: product_workspace
    status: archived
    path: "${ORG_ROOT}/ProductA"
    governance_profile: product_workspace
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
      proposals_root: docs/proposals
"""


class PlatformCliTests(unittest.TestCase):
    def run_cli(
        self,
        *args: str,
        env_overrides: dict[str, str | None] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for key, value in (env_overrides or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value

        return subprocess.run(
            [sys.executable, str(CLI), *args],
            check=False,
            cwd=cwd or REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_workspace_initialize_from_request_writes_report_only_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "workspaces.yaml"
            request_path = root / "product_workspace_creation_requests.json"
            output_path = root / "runs" / "product_workspace_initialization_plan.json"
            workspace_root = root / "PantryRotation"
            catalog_path.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                f"organization_root: {json.dumps(str(root))}\n"
                "workspaces: []\n",
                encoding="utf-8",
            )
            request_path.write_text(
                json.dumps(workspace_creation_request(), indent=2),
                encoding="utf-8",
            )

            result = self.run_cli(
                "workspace",
                "initialize-from-request",
                "--creation-request",
                str(request_path),
                "--catalog",
                str(catalog_path),
                "--path",
                str(workspace_root),
                "--artifact-base-url",
                "https://specgraph.tech",
                "--product-artifact-base-url",
                " https://cdn.example/pantry/ ",
                "--output",
                str(output_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_workspace_initialization_plan",
            )
            self.assertEqual(
                payload["summary"]["status"],
                "workspace_initialization_planned",
            )
            self.assertEqual(payload["workspace"]["workspace_id"], "pantry-rotation")
            self.assertEqual(
                payload["workspace_binding"]["platform_default_run_dir_ref"],
                "runs/pantry-rotation",
            )
            self.assertEqual(
                payload["workspace_binding"]["specspace_state_namespace_ref"],
                "specspace-state://workspace/pantry-rotation",
            )
            self.assertEqual(
                payload["workspace_binding"]["product_artifact_manifest_ref"],
                "workspaces/pantry-rotation/artifact_manifest.json",
            )
            self.assertEqual(
                payload["workspace_binding"]["product_artifact_base_url"],
                "https://cdn.example/pantry",
            )
            self.assertEqual(
                payload["workspace_binding"]["product_artifact_manifest_url"],
                "https://cdn.example/pantry/artifact_manifest.json",
            )
            self.assertFalse(
                payload["workspace_binding"]["binding_authority"]["may_write_catalog"]
            )
            self.assertEqual(
                payload["pending_catalog_entry"]["project_id"],
                "pantry-rotation",
            )
            self.assertFalse(payload["summary"]["catalog_written"])
            self.assertFalse(payload["summary"]["workspace_files_created"])
            self.assertFalse(payload["authority_boundary"]["updates_workspace_catalog"])
            self.assertTrue(output_path.is_file())

    def test_workspace_request_initialization_execution_writes_request_only_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "workspaces.yaml"
            request_path = root / "product_workspace_creation_requests.json"
            plan_path = root / "runs" / "product_workspace_initialization_plan.json"
            execution_request_path = (
                root / "runs" / "product_workspace_initialization_execution_request.json"
            )
            workspace_root = root / "PantryRotation"
            catalog_path.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                f"organization_root: {json.dumps(str(root))}\n"
                "workspaces: []\n",
                encoding="utf-8",
            )
            request_path.write_text(
                json.dumps(workspace_creation_request(), indent=2),
                encoding="utf-8",
            )
            plan_result = self.run_cli(
                "workspace",
                "initialize-from-request",
                "--creation-request",
                str(request_path),
                "--catalog",
                str(catalog_path),
                "--path",
                str(workspace_root),
                "--artifact-base-url",
                "https://specgraph.tech",
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(
                plan_result.returncode,
                0,
                plan_result.stderr + plan_result.stdout,
            )

            result = self.run_cli(
                "workspace",
                "request-initialization-execution",
                "--plan",
                str(plan_path),
                "--operator-ref",
                "operator://local-smoke",
                "--output",
                str(execution_request_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_workspace_initialization_execution_request",
            )
            self.assertTrue(payload["request_only"])
            self.assertEqual(
                payload["requested_operation"],
                "workspace.execute-initialization-plan",
            )
            self.assertEqual(payload["workspace"]["workspace_id"], "pantry-rotation")
            self.assertEqual(
                payload["workspace_binding"]["product_artifact_manifest_url"],
                "https://specgraph.tech/workspaces/pantry-rotation/artifact_manifest.json",
            )
            self.assertEqual(
                payload["summary"]["status"],
                "workspace_initialization_execution_requested",
            )
            self.assertTrue(payload["summary"]["ready_for_managed_execution"])
            self.assertEqual(payload["operator_ref"], "operator://local-smoke")
            self.assertRegex(payload["plan_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(payload["idempotency_key"], r"^[0-9a-f]{64}$")
            for key, value in payload["authority_boundary"].items():
                with self.subTest(key=key):
                    self.assertFalse(value)
            self.assertTrue(execution_request_path.is_file())

    def test_workspace_request_initialization_execution_blocks_unready_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            output_path = root / "request.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "artifact_kind": "platform_product_workspace_initialization_plan",
                        "schema_version": 1,
                        "ok": False,
                        "summary": {
                            "ready_for_platform_initialization": False,
                        },
                        "authority_boundary": {},
                        "workspace": {
                            "workspace_id": "pantry-rotation",
                            "display_name": "Pantry Rotation",
                            "workspace_root": str(root / "PantryRotation"),
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                "workspace",
                "request-initialization-execution",
                "--plan",
                str(plan_path),
                "--output",
                str(output_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(
                payload["summary"]["status"],
                "workspace_initialization_execution_request_blocked",
            )
            self.assertFalse(payload["summary"]["ready_for_managed_execution"])
            self.assertTrue(output_path.is_file())

    def test_workspace_initialize_from_request_blocks_duplicate_catalog_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "workspaces.yaml"
            request_path = root / "product_workspace_creation_requests.json"
            catalog_path.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                f"organization_root: {json.dumps(str(root))}\n"
                "workspaces:\n"
                "  - project_id: pantry-rotation\n"
                "    display_name: Pantry Rotation\n"
                "    kind: product_workspace\n"
                "    status: active\n"
                "    path: /tmp/pantry-rotation\n"
                "    governance_profile: product_workspace\n",
                encoding="utf-8",
            )
            request_path.write_text(
                json.dumps(workspace_creation_request(), indent=2),
                encoding="utf-8",
            )

            result = self.run_cli(
                "workspace",
                "initialize-from-request",
                "--creation-request",
                str(request_path),
                "--catalog",
                str(catalog_path),
                "--path",
                str(root / "PantryRotation"),
                "--format",
                "json",
            )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn(
            "product_workspace_creation_catalog_duplicate",
            {item["code"] for item in payload["diagnostics"]},
        )

    def test_workspace_initialize_from_request_blocks_authority_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "workspaces.yaml"
            request_path = root / "product_workspace_creation_requests.json"
            catalog_path.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                f"organization_root: {json.dumps(str(root))}\n"
                "workspaces: []\n",
                encoding="utf-8",
            )
            request_path.write_text(
                json.dumps(
                    workspace_creation_request(authority_expanded=True),
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                "workspace",
                "initialize-from-request",
                "--creation-request",
                str(request_path),
                "--catalog",
                str(catalog_path),
                "--path",
                str(root / "PantryRotation"),
                "--format",
                "json",
            )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn(
            "product_workspace_creation_request_authority_expanded",
            {item["code"] for item in payload["diagnostics"]},
        )

    def test_workspace_initialize_from_request_blocks_authority_state_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "workspaces.yaml"
            request_path = root / "product_workspace_creation_requests.json"
            catalog_path.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                f"organization_root: {json.dumps(str(root))}\n"
                "workspaces: []\n",
                encoding="utf-8",
            )
            request = workspace_creation_request()
            request["authority_boundary"][
                "product_workspace_creation_request_state_is_authority"
            ] = True
            request["requests"][0]["authority_boundary"][
                "product_workspace_creation_request_state_is_authority"
            ] = True
            request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")

            result = self.run_cli(
                "workspace",
                "initialize-from-request",
                "--creation-request",
                str(request_path),
                "--catalog",
                str(catalog_path),
                "--path",
                str(root / "PantryRotation"),
                "--format",
                "json",
            )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        subjects = {item["subject"] for item in payload["diagnostics"]}
        self.assertIn(
            "creation_request.authority_boundary.product_workspace_creation_request_state_is_authority",
            subjects,
        )
        self.assertIn(
            "creation_request.requests[].authority_boundary.product_workspace_creation_request_state_is_authority",
            subjects,
        )

    def test_workspace_initialize_from_request_blocks_report_authority_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "workspaces.yaml"
            request_path = root / "product_workspace_creation_requests.json"
            catalog_path.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                f"organization_root: {json.dumps(str(root))}\n"
                "workspaces: []\n",
                encoding="utf-8",
            )
            request = workspace_creation_request()
            request["requests"][0]["authority_boundary"]["updates_workspace_catalog"] = True
            request["requests"][0]["authority_boundary"]["creates_git_commits"] = True
            request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")

            result = self.run_cli(
                "workspace",
                "initialize-from-request",
                "--creation-request",
                str(request_path),
                "--catalog",
                str(catalog_path),
                "--path",
                str(root / "PantryRotation"),
                "--format",
                "json",
            )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        subjects = {item["subject"] for item in payload["diagnostics"]}
        self.assertIn(
            "creation_request.requests[].authority_boundary.updates_workspace_catalog",
            subjects,
        )
        self.assertIn(
            "creation_request.requests[].authority_boundary.creates_git_commits",
            subjects,
        )

    def test_workspace_initialize_from_request_rejects_non_product_workspace_id(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "workspaces.yaml"
            request_path = root / "product_workspace_creation_requests.json"
            catalog_path.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                f"organization_root: {json.dumps(str(root))}\n"
                "workspaces: []\n",
                encoding="utf-8",
            )
            request_path.write_text(
                json.dumps(
                    workspace_creation_request(workspace_id="pantry_rotation"),
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                "workspace",
                "initialize-from-request",
                "--creation-request",
                str(request_path),
                "--catalog",
                str(catalog_path),
                "--path",
                str(root / "PantryRotation"),
                "--format",
                "json",
            )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertIn(
            "product_workspace_creation_workspace_id_invalid",
            {item["code"] for item in payload["diagnostics"]},
        )

    def test_workspace_initialize_from_request_avoids_spurious_duplicate_for_invalid_id(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "workspaces.yaml"
            request_path = root / "product_workspace_creation_requests.json"
            catalog_path.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                f"organization_root: {json.dumps(str(root))}\n"
                "workspaces:\n"
                "  - display_name: Missing Project Id\n",
                encoding="utf-8",
            )
            request = workspace_creation_request()
            request["requests"][0]["workspace_id"] = None
            request["requests"][0]["route"] = None
            request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")

            result = self.run_cli(
                "workspace",
                "initialize-from-request",
                "--creation-request",
                str(request_path),
                "--catalog",
                str(catalog_path),
                "--path",
                str(root / "PantryRotation"),
                "--format",
                "json",
            )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        codes = {item["code"] for item in payload["diagnostics"]}
        self.assertIn("product_workspace_creation_workspace_id_invalid", codes)
        self.assertNotIn("product_workspace_creation_catalog_duplicate", codes)

    def test_workspace_initialize_from_request_rejects_output_inside_workspace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "workspaces.yaml"
            request_path = root / "product_workspace_creation_requests.json"
            workspace_root = root / "PantryRotation"
            output_path = workspace_root / "runs" / "product_workspace_initialization_plan.json"
            catalog_path.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                f"organization_root: {json.dumps(str(root))}\n"
                "workspaces: []\n",
                encoding="utf-8",
            )
            request_path.write_text(
                json.dumps(workspace_creation_request(), indent=2),
                encoding="utf-8",
            )

            result = self.run_cli(
                "workspace",
                "initialize-from-request",
                "--creation-request",
                str(request_path),
                "--catalog",
                str(catalog_path),
                "--path",
                str(workspace_root),
                "--output",
                str(output_path),
                "--format",
                "json",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(workspace_root.exists())
        payload = json.loads(result.stdout)
        self.assertIn(
            "product_workspace_initialization_output_inside_workspace",
            {item["code"] for item in payload["diagnostics"]},
        )

    def write_graph_repository_run_artifacts(
        self,
        runs_dir: Path,
        *,
        candidate_authority_expanded: bool = False,
        candidate_ready: bool = True,
        repair_ready: bool = True,
        context_required_count: int = 0,
        clarification_answers_ready: bool = True,
        ontology_decisions_ready: bool = True,
        rerun_input_ready: bool = True,
        rerun_preview_ready: bool = True,
        rerun_materialization_ready: bool = True,
        repair_session_ready: bool = True,
        repair_session_intermediate_ready: bool | None = None,
        repair_session_ready_for_candidate_approval: bool | None = None,
        repair_session_authority_expanded: bool = False,
        repair_session_privacy_expanded: bool = False,
        repair_session_stale_source_ref: bool = False,
        unresolved_ontology_gap_count: object = 0,
        include_unresolved_ontology_gap_count: bool = True,
    ) -> None:
        unresolved_count_is_clear = (
            include_unresolved_ontology_gap_count
            and isinstance(unresolved_ontology_gap_count, int)
            and unresolved_ontology_gap_count == 0
        )
        if repair_session_intermediate_ready is None:
            repair_session_intermediate_ready = all(
                (
                    clarification_answers_ready,
                    ontology_decisions_ready,
                    rerun_input_ready,
                    rerun_preview_ready,
                    rerun_materialization_ready,
                )
            )
        if repair_session_ready_for_candidate_approval is None:
            repair_session_ready_for_candidate_approval = all(
                (
                    candidate_ready,
                    repair_ready,
                    context_required_count == 0,
                    repair_session_intermediate_ready,
                    unresolved_count_is_clear,
                )
            )
        repair_session_blockers: list[str] = []
        if not candidate_ready:
            repair_session_blockers.append("candidate_not_ready")
        if not repair_ready:
            repair_session_blockers.append("repair_loop_not_ready")
        if context_required_count:
            repair_session_blockers.append("repair_context_required")
        if not clarification_answers_ready:
            repair_session_blockers.append("clarification_answers_not_ready")
        if not ontology_decisions_ready:
            repair_session_blockers.append("ontology_gap_decisions_not_ready")
        if not rerun_input_ready:
            repair_session_blockers.append("rerun_input_not_ready")
        if not rerun_preview_ready:
            repair_session_blockers.append("rerun_preview_not_ready")
        if not rerun_materialization_ready:
            repair_session_blockers.append("rerun_materialization_not_ready")
        if not unresolved_count_is_clear:
            repair_session_blockers.append("unresolved_ontology_gaps")
        if (
            not repair_session_ready_for_candidate_approval
            and not repair_session_blockers
        ):
            repair_session_blockers.append(
                "repair_session_not_ready_for_candidate_approval"
            )
        rerun_preview_summary: dict[str, object] = {
            "resolved_ontology_gap_count": 1,
        }
        rerun_materialization_summary: dict[str, object] = {
            "removed_gap_count": 1,
            "resolved_ontology_gap_count": 1,
        }
        if include_unresolved_ontology_gap_count:
            rerun_preview_summary["unresolved_ontology_gap_count"] = (
                unresolved_ontology_gap_count
            )
            rerun_materialization_summary["unresolved_ontology_gap_count"] = (
                unresolved_ontology_gap_count
            )
        repair_session_source_refs = {
            "active_candidate": "runs/active_idea_to_spec_candidate.json",
            "clarification_requests": "runs/idea_to_spec_clarification_requests.json",
            "clarification_answers": "runs/idea_to_spec_clarification_answers.json",
            "ontology_decisions": "runs/product_ontology_gap_review_decisions.json",
            "rerun_input": "runs/idea_to_spec_answer_rerun_input.json",
            "rerun_preview": "runs/idea_to_spec_rerun_preview.json",
            "rerun_materialization": "runs/idea_to_spec_rerun_materialization.json",
            "promotion_gate": "runs/idea_to_spec_promotion_gate.json",
        }
        if repair_session_stale_source_ref:
            repair_session_source_refs["rerun_preview"] = "runs/stale_preview.json"
        repair_session_source_artifacts = {
            key: {
                "artifact_key": key,
                "source_ref": source_ref,
                "artifact_kind": key,
                "readiness": {
                    "ready": True,
                    "review_state": "ready",
                },
            }
            for key, source_ref in repair_session_source_refs.items()
        }
        artifacts = {
            "idea_event_storming_intake.json": {
                "schema_version": 1,
                "artifact_kind": "idea_event_storming_intake",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "review_state": "review_ready",
            },
            "candidate_spec_graph.json": {
                "schema_version": 1,
                "artifact_kind": "candidate_spec_graph",
                "canonical_mutations_allowed": candidate_authority_expanded,
                "tracked_artifacts_written": False,
                "pre_sib_readiness": {
                    "ready": candidate_ready,
                    "review_state": "ready",
                },
            },
            "pre_sib_coherence_report.json": {
                "schema_version": 1,
                "artifact_kind": "pre_sib_coherence_report",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": True,
                    "review_state": "ready",
                },
            },
            "candidate_repair_loop_report.json": {
                "schema_version": 1,
                "artifact_kind": "candidate_repair_loop_report",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": repair_ready,
                    "review_state": "ready" if repair_ready else "context_required",
                },
                "summary": {
                    "context_required_count": context_required_count,
                },
            },
            "idea_to_spec_clarification_requests.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_clarification_requests",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": False,
                    "review_state": "clarification_required",
                },
                "summary": {
                    "request_count": 1,
                    "blocking_request_count": 1,
                },
            },
            "idea_to_spec_clarification_answers.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_clarification_answers",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": clarification_answers_ready,
                    "review_state": "answers_ready_for_rerun"
                    if clarification_answers_ready
                    else "answers_blocked",
                },
                "summary": {
                    "accepted_answer_count": 1 if clarification_answers_ready else 0,
                    "unresolved_blocking_count": 0
                    if clarification_answers_ready
                    else 1,
                },
            },
            "product_ontology_gap_review_decisions.json": {
                "schema_version": 1,
                "artifact_kind": "product_ontology_gap_review_decisions",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": ontology_decisions_ready,
                    "review_state": "ontology_gap_decisions_ready"
                    if ontology_decisions_ready
                    else "ontology_gap_decisions_blocked",
                },
                "summary": {
                    "decision_count": 1 if ontology_decisions_ready else 0,
                },
            },
            "idea_to_spec_answer_rerun_input.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_answer_rerun_input",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": rerun_input_ready,
                    "review_state": "rerun_input_ready"
                    if rerun_input_ready
                    else "rerun_input_blocked",
                },
                "summary": {
                    "ontology_decision_count": 1 if ontology_decisions_ready else 0,
                },
            },
            "idea_to_spec_rerun_preview.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_rerun_preview",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": rerun_preview_ready,
                    "review_state": "rerun_preview_ready"
                    if rerun_preview_ready
                    else "rerun_preview_blocked",
                },
                "summary": rerun_preview_summary,
            },
            "idea_to_spec_rerun_materialization.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_rerun_materialization",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": rerun_materialization_ready,
                    "review_state": "rerun_materialization_ready"
                    if rerun_materialization_ready
                    else "rerun_materialization_blocked",
                },
                "summary": rerun_materialization_summary,
            },
            "idea_to_spec_repair_session.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_repair_session_journal",
                "contract_ref": "specgraph.idea-to-spec.repair-session-journal.v0.1",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "authority_boundary": {
                    "may_accept_ontology_terms": False,
                    "may_apply_answers_to_source_artifacts": False,
                    "may_apply_decisions_to_source_artifacts": False,
                    "may_create_branch_or_commit": repair_session_authority_expanded,
                    "may_execute_prompt_agent": False,
                    "may_mark_candidate_graph_accepted": False,
                    "may_mutate_candidate_source_artifacts": False,
                    "may_mutate_canonical_specs": False,
                    "may_open_pull_request": False,
                    "may_publish_read_model": False,
                    "may_write_ontology_lockfile": False,
                    "may_write_ontology_package": False,
                },
                "privacy_boundary": {
                    "raw_idea_text_published": repair_session_privacy_expanded,
                    "raw_model_output_published": False,
                    "raw_operator_note_published": False,
                    "raw_prompt_published": False,
                    "static_flags_are_asserted_invariants": True,
                },
                "session": {
                    "candidate_id": "idea-alpha",
                    "workflow_lane": "product_idea_to_spec",
                    "target_repository_role": "product_spec_workspace",
                    "workspace_route": "/idea-alpha",
                },
                "readiness": {
                    "ready": repair_session_ready,
                    "review_state": "repair_session_journal_ready"
                    if repair_session_ready
                    else "repair_session_journal_blocked",
                },
                "readiness_impact": {
                    "blocked_by": repair_session_blockers,
                    "intermediate_artifacts_ready": repair_session_intermediate_ready,
                    "ready_for_candidate_approval": (
                        repair_session_ready_for_candidate_approval
                    ),
                    "ready_for_platform_promotion": False,
                    "unresolved_ontology_gap_count": (
                        unresolved_ontology_gap_count
                        if include_unresolved_ontology_gap_count
                        else None
                    ),
                },
                "source_artifacts": repair_session_source_artifacts,
                "summary": {
                    "candidate_id": "idea-alpha",
                    "workflow_lane": "product_idea_to_spec",
                    "ready_for_candidate_approval": (
                        repair_session_ready_for_candidate_approval
                    ),
                    "unresolved_ontology_gap_count": (
                        unresolved_ontology_gap_count
                        if include_unresolved_ontology_gap_count
                        else None
                    ),
                    "source_artifact_count": len(repair_session_source_artifacts),
                },
            },
        }
        for filename, payload in artifacts.items():
            (runs_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def write_graph_repository_repaired_run_artifacts(
        self,
        runs_dir: Path,
        *,
        stale_handoff_ref: bool = False,
    ) -> None:
        source_refs = {
            "active_candidate": "runs/repaired_active_idea_to_spec_candidate.json",
            "clarification_requests": "runs/idea_to_spec_clarification_requests.json",
            "clarification_answers": "runs/idea_to_spec_clarification_answers.json",
            "ontology_decisions": "runs/product_ontology_gap_review_decisions.json",
            "rerun_input": "runs/idea_to_spec_answer_rerun_input.json",
            "rerun_preview": "runs/idea_to_spec_rerun_preview.json",
            "rerun_materialization": "runs/idea_to_spec_rerun_materialization.json",
            "promotion_gate": "runs/repaired_idea_to_spec_promotion_gate.json",
        }
        repaired_active = {
            "schema_version": 1,
            "artifact_kind": "active_idea_to_spec_candidate",
            "contract_ref": "specgraph.idea-to-spec.active-candidate-source.v0.1",
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "readiness": {
                "ready": True,
                "review_state": "active_candidate_ready",
                "blocked_by": [],
            },
            "summary": {
                "candidate_id": "idea-alpha",
                "workspace_route": "/idea-alpha",
                "status": "active_candidate_ready",
                "promotion_path_count": 1,
            },
        }
        repaired_repair_session = {
            "schema_version": 1,
            "artifact_kind": "idea_to_spec_repair_session_journal",
            "contract_ref": "specgraph.idea-to-spec.repair-session-journal.v0.1",
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "authority_boundary": {
                "may_accept_ontology_terms": False,
                "may_apply_answers_to_source_artifacts": False,
                "may_apply_decisions_to_source_artifacts": False,
                "may_create_branch_or_commit": False,
                "may_execute_prompt_agent": False,
                "may_mark_candidate_graph_accepted": False,
                "may_mutate_candidate_source_artifacts": False,
                "may_mutate_canonical_specs": False,
                "may_open_pull_request": False,
                "may_publish_read_model": False,
                "may_write_ontology_lockfile": False,
                "may_write_ontology_package": False,
            },
            "privacy_boundary": {
                "raw_idea_text_published": False,
                "raw_model_output_published": False,
                "raw_operator_note_published": False,
                "raw_prompt_published": False,
                "static_flags_are_asserted_invariants": True,
            },
            "session": {
                "candidate_id": "idea-alpha",
                "workflow_lane": "product_idea_to_spec",
                "target_repository_role": "product_spec_workspace",
                "workspace_route": "/idea-alpha",
            },
            "readiness": {
                "ready": True,
                "review_state": "repair_session_journal_ready",
                "blocked_by": [],
            },
            "readiness_impact": {
                "blocked_by": [],
                "intermediate_artifacts_ready": True,
                "ready_for_candidate_approval": True,
                "ready_for_platform_promotion": False,
                "unresolved_ontology_gap_count": 0,
            },
            "source_artifacts": {
                key: {
                    "artifact_key": key,
                    "source_ref": source_ref,
                    "artifact_kind": key,
                    "readiness": {"ready": True, "review_state": "ready"},
                }
                for key, source_ref in source_refs.items()
            },
            "summary": {
                "candidate_id": "idea-alpha",
                "workflow_lane": "product_idea_to_spec",
                "ready_for_candidate_approval": True,
                "unresolved_ontology_gap_count": 0,
                "source_artifact_count": len(source_refs),
            },
        }
        repaired_promotion_gate = {
            "schema_version": 1,
            "artifact_kind": "idea_to_spec_promotion_gate",
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "readiness": {
                "ready": True,
                "review_state": "ready_for_platform_promotion_request",
                "blocked_by": [],
            },
            "summary": {
                "status": "ready_for_platform_promotion_request",
                "promotion_path_count": 1,
                "materialized_file_count": 1,
                "finding_count": 0,
            },
            "promotion_request": {
                "paths": ["runs/repaired_materialized_candidate_specs/IDEA-ALPHA.yaml"],
                "path_argument": "--path",
                "platform_artifact_kind": "platform_graph_repository_promotion_request",
            },
            "authority_boundary": {
                "may_create_branch_or_commit": False,
                "may_mutate_canonical_specs": False,
                "may_open_pull_request": False,
                "may_write_ontology_package": False,
            },
        }
        repaired_handoff = {
            "schema_version": 1,
            "artifact_kind": "repaired_candidate_promotion_handoff_report",
            "contract_ref": (
                "specgraph.idea-to-spec.repaired-candidate-promotion-handoff.v0.1"
            ),
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "readiness": {
                "ready": True,
                "review_state": "repaired_candidate_promotion_handoff_ready",
                "blocked_by": [],
            },
            "summary": {
                "status": "repaired_candidate_promotion_handoff_ready",
                "ready_for_candidate_approval": True,
                "ready_for_platform_promotion": False,
                "unresolved_candidate_gap_count": 0,
                "unresolved_ontology_gap_count": 0,
                "resolved_candidate_gap_count": 1,
                "resolved_ontology_gap_count": 1,
                "removed_gap_count": 2,
            },
            "output_artifacts": {
                "repaired_active_candidate": {
                    "artifact_kind": "active_idea_to_spec_candidate",
                    "source_ref": "runs/active_idea_to_spec_candidate.json"
                    if stale_handoff_ref
                    else "runs/repaired_active_idea_to_spec_candidate.json",
                    "summary": repaired_active["summary"],
                },
                "repaired_repair_session": {
                    "artifact_kind": "idea_to_spec_repair_session_journal",
                    "source_ref": "runs/repaired_idea_to_spec_repair_session.json",
                    "summary": repaired_repair_session["summary"],
                },
                "repaired_promotion_gate": {
                    "artifact_kind": "idea_to_spec_promotion_gate",
                    "source_ref": "runs/repaired_idea_to_spec_promotion_gate.json",
                    "summary": repaired_promotion_gate["summary"],
                },
            },
            "authority_boundary": {
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_execute_prompt_agent": False,
                "may_mark_candidate_graph_accepted": False,
                "may_materialize_candidate_approval_decision": False,
                "may_mutate_candidate_source_artifacts": False,
                "may_mutate_canonical_specs": False,
                "may_open_pull_request": False,
                "may_publish_read_model": False,
                "may_write_ontology_lockfile": False,
                "may_write_ontology_package": False,
            },
        }
        artifacts = {
            "repaired_active_idea_to_spec_candidate.json": repaired_active,
            "repaired_idea_to_spec_repair_session.json": repaired_repair_session,
            "repaired_idea_to_spec_promotion_gate.json": repaired_promotion_gate,
            "repaired_candidate_promotion_handoff_report.json": repaired_handoff,
        }
        for filename, payload in artifacts.items():
            (runs_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def write_product_repair_rerun_artifacts(
        self,
        specgraph_dir: Path,
        *,
        request_authority_expanded: bool = False,
        import_preview_ready: bool = True,
        request_gate_ready: bool = True,
    ) -> None:
        runs_dir = specgraph_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        self.write_graph_repository_run_artifacts(runs_dir)
        selected_request_id = "rerun-request-1"
        candidate_id = "idea-alpha"
        workspace_id = "idea-alpha-workspace"
        request_state = {
            "schema_version": 1,
            "artifact_kind": "specspace_idea_to_spec_repair_rerun_request_state",
            "state_owner": "SpecSpace",
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "consumer_boundary": {
                "specgraph_execution_authority": False,
                "git_service_authority": False,
            },
            "authority_boundary": {
                "may_execute_specgraph": False,
                "may_run_make_target": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
                "may_execute_git_service_operation": False,
            },
            "requests": [
                {
                    "id": selected_request_id,
                    "status": "requested",
                    "requested_action": "prepare_repair_draft_rerun",
                    "workspace_id": workspace_id,
                    "candidate_id": candidate_id,
                    "repair_session_id": "repair-session-1",
                    "may_execute_specgraph": False,
                    "may_run_make_target": False,
                    "may_mutate_canonical_specs": False,
                    "may_write_ontology_package": request_authority_expanded,
                    "may_accept_ontology_terms": False,
                    "may_create_branch_or_commit": False,
                    "may_open_pull_request": False,
                    "may_execute_git_service_operation": False,
                    "canonical_mutations_allowed": False,
                    "tracked_artifacts_written": False,
                }
            ],
        }
        import_preview = {
            "schema_version": 1,
            "artifact_kind": "specspace_repair_draft_import_preview",
            "contract_ref": (
                "specgraph.idea-to-spec.specspace-repair-draft-import-preview.v0.1"
            ),
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "authority_boundary": {
                "may_execute_specgraph": False,
                "may_run_make_target": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
                "may_execute_git_service_operation": False,
            },
            "session": {
                "workspace_id": workspace_id,
                "candidate_id": candidate_id,
            },
            "readiness": {
                "ready": import_preview_ready,
                "review_state": "ready" if import_preview_ready else "blocked",
            },
            "summary": {
                "accepted_for_rerun_count": 1 if import_preview_ready else 0,
            },
        }
        request_gate = {
            "schema_version": 1,
            "artifact_kind": "specspace_repair_rerun_request_gate",
            "contract_ref": (
                "specgraph.idea-to-spec.specspace-repair-rerun-request-gate.v0.1"
            ),
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "authority_boundary": {
                "may_execute_specgraph_from_request": False,
                "may_run_make_target_from_request": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
                "may_execute_git_service_operation": False,
            },
            "readiness": {
                "ready": request_gate_ready,
                "review_state": "ready" if request_gate_ready else "blocked",
            },
            "summary": {
                "selected_request_id": selected_request_id,
                "workspace_id": workspace_id,
                "candidate_id": candidate_id,
            },
            "resolved_inputs": {
                "workspace_id": workspace_id,
                "candidate_id": candidate_id,
            },
            "recommended_invocation": {
                "make_target": "product-workspace-requested-repair-draft-rerun",
            },
        }
        artifacts = {
            "idea_to_spec_repair_rerun_requests.json": request_state,
            "specspace_repair_draft_import_preview.json": import_preview,
            "specspace_repair_rerun_request_gate.json": request_gate,
        }
        for filename, payload in artifacts.items():
            (runs_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def write_workspace_state_hygiene_artifact(
        self,
        specgraph_dir: Path,
        *,
        stale_state_count: int = 1,
    ) -> Path:
        runs_dir = specgraph_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / "workspace_state_hygiene_report.json"
        payload = {
            "api_version": "v1",
            "artifact_kind": "specspace_idea_to_spec_workspace_state_hygiene",
            "schema_version": 1,
            "workspace_id": "idea-alpha-workspace",
            "candidate_id": "idea-alpha",
            "repair_session_id": "repair-session-1",
            "repair_session_ref": "runs/idea_to_spec_repair_session.json",
            "summary": {
                "status": "blocked" if stale_state_count else "ready",
                "usable_state_count": 2,
                "missing_state_count": 0,
                "stale_state_count": stale_state_count,
                "invalid_state_count": 0,
                "blocking_state_count": stale_state_count,
                "next_action": (
                    "Replace the rerun request for the current workspace and repair session."
                    if stale_state_count
                    else "Continue with the current idea-to-spec workflow."
                ),
                "recommended_action_count": 1 if stale_state_count else 0,
                "enabled_recommended_action_count": 0,
            },
            "recommended_actions": [
                {
                    "id": "workspace_state.recreate_repair_rerun_request",
                    "label": "Recreate repair rerun request",
                    "target_state": "repair_rerun_request",
                    "target_section": "idea-to-spec-repair-review",
                    "requires_current_repair_session": True,
                    "workspace_id": "idea-alpha-workspace",
                    "candidate_id": "idea-alpha",
                    "repair_session_id": "repair-session-1",
                    "repair_session_ref": "runs/idea_to_spec_repair_session.json",
                    "enabled": False,
                    "blockers": ["Rebuild repair draft import preview first."],
                    "ui_intent": "create_repair_rerun_request",
                    "command_hint": None,
                    "evidence_refs": [
                        "specspace-state://idea_to_spec_repair_rerun_requests.json",
                        "runs/idea_to_spec_repair_session.json",
                    ],
                    "authority_boundary": {
                        "inspect_only": True,
                        "operator_intent_only": True,
                        "may_execute_specgraph": False,
                        "may_execute_platform": False,
                        "may_execute_git_service": False,
                        "may_apply_answers": False,
                        "may_apply_decisions": False,
                        "may_mutate_candidate_artifacts": False,
                        "may_mutate_canonical_specs": False,
                        "may_write_ontology_package": False,
                        "may_accept_ontology_terms": False,
                        "may_clear_state": False,
                        "may_apply_state": False,
                        "may_delete_state": False,
                        "may_create_branch_or_commit": False,
                        "may_open_pull_request": False,
                    },
                }
            ]
            if stale_state_count
            else [],
            "states": [
                {
                    "kind": "repair_rerun_request",
                    "status": "stale" if stale_state_count else "usable",
                    "reason": "workspace_id_mismatch" if stale_state_count else "current_workspace_session_state_present",
                    "stored_workspace_id": "local-subscription-control"
                    if stale_state_count
                    else "idea-alpha-workspace",
                    "current_workspace_id": "idea-alpha-workspace",
                    "blocks": ["repair_rerun_smoke", "repair_rerun_execution"],
                    "next_action": "Replace the rerun request for the current workspace and repair session.",
                }
            ],
            "authority_boundary": {
                "workspace_state_hygiene_is_authority": False,
                "may_execute_specgraph": False,
                "may_execute_platform": False,
                "may_execute_git_service": False,
                "may_apply_answers": False,
                "may_apply_decisions": False,
                "may_mutate_candidate_artifacts": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
            },
            "action_boundary": {
                "inspect_only": True,
                "acknowledge_only": True,
                "may_clear_state": False,
                "may_apply_state": False,
                "may_delete_state": False,
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_idea_maturity_artifacts(
        self,
        specgraph_dir: Path,
        *,
        validation_status: str = "ok",
        authority_expanded: bool = False,
        include_privacy_boundary: bool = True,
        include_contract_metadata: bool = True,
    ) -> None:
        runs_dir = specgraph_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        metrics_report = {
            "schema_version": 1,
            "artifact_kind": "idea_maturity_metrics_report",
            "contract_ref": "specgraph.idea-to-spec.maturity-metrics-report.v0.1",
            "metric_pack_id": "idea_to_spec_maturity",
            "metric_pack_ref": "metrics.idea_to_spec_maturity.v0.1",
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "authority_boundary": {
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_execute_prompt_agent": False,
                "may_merge_pull_request": False,
                "may_mutate_canonical_specs": authority_expanded,
                "may_open_pull_request": False,
                "may_publish_read_model": False,
                "may_write_ontology_package": False,
            },
            "candidate": {
                "candidate_id": "idea-alpha",
                "workflow_lane": "product_idea_to_spec",
                "target_repository_role": "product_spec_workspace",
            },
            "derived_state": {
                "blockers": ["remaining_blockers"],
                "candidate_approval_state": "blocked",
                "lifecycle_state": "promotion_requested",
                "platform_promotion_state": "dry_run",
                "read_model_publication_state": "not_reached",
                "review_status": "not_available",
            },
            "groups": {
                "answer_materialization": {
                    "accepted_answer_count": 3,
                    "per_gap_materialized_answer_count": 2,
                    "aggregate_answer_count": 1,
                    "dismissed_answer_count": 0,
                    "closure_evidence_answer_count": 3,
                    "ordinary_unmaterialized_answer_count": 0,
                },
                "ontology_grounding": {
                    "project_local_ontology_review": {
                        "status": "project_local_ontology_decision_effect_ready",
                        "accepted_decision_count": 2,
                        "maturity_evidence_decision_count": 2,
                        "keep_project_local_count": 1,
                        "bind_existing_count": 1,
                        "alias_count": 0,
                        "request_promotion_count": 0,
                        "reject_count": 0,
                        "deferred_count": 0,
                        "invalid_decision_count": 0,
                        "missing_decision_count": 0,
                        "blocking_decision_count": 0,
                        "follow_up_decision_count": 0,
                        "effect_count": 2,
                        "ready_for_maturity": True,
                        "evidence_refs": [
                            "runs/project_local_ontology_review_decisions.json"
                        ],
                    }
                },
                "workflow_friction": {
                    "dry_run_count": 1,
                    "failed_gate_count": 1,
                    "stale_ref_count": 0,
                },
                "promotion_readiness": {
                    "candidate_approval_state": "blocked",
                    "platform_promotion_state": "dry_run",
                },
                "review_publication": {
                    "read_model_publication_state": "not_reached",
                    "review_status": "not_available",
                },
            },
            "metrics": {
                "dry_run_count": 1,
                "failed_gate_count": 1,
                "stale_ref_count": 0,
                "accepted_answer_count": 3,
                "per_gap_materialized_answer_count": 2,
                "aggregate_answer_count": 1,
                "dismissed_answer_count": 0,
                "closure_evidence_answer_count": 3,
                "ordinary_unmaterialized_answer_count": 0,
                "project_local_ontology_review_status": (
                    "project_local_ontology_decision_effect_ready"
                ),
                "project_local_ontology_accepted_decision_count": 2,
                "project_local_ontology_keep_local_count": 1,
                "project_local_ontology_bind_existing_count": 1,
                "project_local_ontology_alias_count": 0,
                "project_local_ontology_request_promotion_count": 0,
                "project_local_ontology_reject_count": 0,
                "project_local_ontology_deferred_decision_count": 0,
                "project_local_ontology_invalid_decision_count": 0,
                "project_local_ontology_missing_decision_count": 0,
                "project_local_ontology_blocking_decision_count": 0,
            },
            "readiness_explainers": [
                {
                    "id": "readiness-explainer.pre-sib-ontology-coverage-gap",
                    "proposal_id": "0180",
                    "kind": "pre_sib_finding",
                    "source": "repaired_pre_sib",
                    "severity": "high",
                    "blocks": ["pre_sib_review", "candidate_approval"],
                    "message": "Ontology coverage is incomplete for the candidate graph.",
                    "next_action": (
                        "Inspect Pre-SIB coherence findings and close the referenced "
                        "candidate graph condition."
                    ),
                    "evidence_refs": [
                        "runs/repaired_pre_sib_coherence_report.json#findings.pre-sib-ontology-coverage-gap"
                    ],
                }
            ],
            "source_artifacts": [
                "runs/idea_to_spec_repair_session.json",
                "runs/platform_product_repair_rerun_publication_report.json",
            ],
        }
        if include_contract_metadata:
            metrics_report["contract"] = {
                "schema_version": 1,
                "schema_ref": "schemas/idea_maturity_metrics_report.schema.json",
                "validation_report_schema_ref": (
                    "schemas/idea_maturity_metrics_validation_report.schema.json"
                ),
                "validator_id": "metrics.idea_maturity_metrics.validator.v0.1",
                "validator_version": "0.1.0",
                "compatibility_policy": "additive_v1",
                "compatibility_policy_ref": (
                    "VALIDATOR_CONTRACT.md#compatibility-policy"
                ),
                "metrics_rfc_ref": "Metrics/IDEA_MATURITY_METRICS.md",
                "proposal_id": "0181",
            }
        if include_privacy_boundary:
            metrics_report["privacy_boundary"] = {
                "contains_human_operator_identity": False,
                "join_to_identity_allowed": False,
                "raw_prompt_or_operator_text_included": False,
            }
        validation_report = {
            "schema_version": 1,
            "artifact_kind": "idea_maturity_metrics_validation_report",
            "metric_pack_id": "idea_to_spec_maturity",
            "summary": {
                "status": validation_status,
                "report_count": 1,
                "valid_count": 1 if validation_status == "ok" else 0,
                "invalid_count": 0 if validation_status == "ok" else 1,
            },
            "authority_boundary": {
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_execute_prompt_agent": False,
                "may_merge_pull_request": False,
                "may_mutate_canonical_specs": False,
                "may_open_pull_request": False,
                "may_publish_read_model": False,
                "may_write_ontology_package": False,
            },
            "reports": [
                {
                    "path": str(runs_dir / "idea_maturity_metrics_report.json"),
                    "status": validation_status,
                    "diagnostics": [],
                }
            ],
        }
        if include_contract_metadata:
            validation_report["validator"] = {
                "id": "metrics.idea_maturity_metrics.validator.v0.1",
                "version": "0.1.0",
                "rfc_ref": "IDEA_MATURITY_METRICS.md",
                "schema_ref": "schemas/idea_maturity_metrics_report.schema.json",
                "validation_report_schema_ref": (
                    "schemas/idea_maturity_metrics_validation_report.schema.json"
                ),
                "script_ref": "scripts/metrics.py",
                "compatibility_policy_ref": (
                    "VALIDATOR_CONTRACT.md#compatibility-policy"
                ),
            }
        (runs_dir / "idea_maturity_metrics_report.json").write_text(
            json.dumps(metrics_report),
            encoding="utf-8",
        )
        (runs_dir / "idea_maturity_metrics_validation_report.json").write_text(
            json.dumps(validation_report),
            encoding="utf-8",
        )

    def write_product_candidate_approval_intent_state(
        self,
        specgraph_dir: Path,
    ) -> None:
        runs_dir = specgraph_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        intent_state = {
            "artifact_kind": "specspace_idea_to_spec_candidate_approval_intent_state",
            "schema_version": 1,
            "state_owner": "SpecSpace",
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "source_artifacts": {
                "idea_to_spec_repair_session": (
                    "runs/repaired_idea_to_spec_repair_session.json"
                ),
                "idea_to_spec_promotion_gate": (
                    "runs/repaired_idea_to_spec_promotion_gate.json"
                ),
            },
            "intents": [
                {
                    "id": "candidate-approval-intent.idea-alpha.20260627T100000Z",
                    "status": "requested",
                    "requested_action": "approve_candidate_for_promotion_review",
                    "workspace_id": "idea-alpha",
                    "candidate_id": "idea-alpha",
                    "repair_session_id": "repair-session.idea-alpha",
                    "repair_session_ref": (
                        "runs/repaired_idea_to_spec_repair_session.json"
                    ),
                    "promotion_gate_ref": (
                        "runs/repaired_idea_to_spec_promotion_gate.json"
                    ),
                    "requested_by": "operator://specspace-local",
                    "reason": "Ready for promotion review.",
                    "created_at": "2026-06-27T10:00:00Z",
                    "updated_at": "2026-06-27T10:00:00Z",
                    "ready_for_candidate_approval": True,
                    "ready_for_platform_promotion": False,
                    "blocked_by": [],
                    "canonical_mutations_allowed": False,
                    "tracked_artifacts_written": False,
                    "may_execute_specgraph": False,
                    "may_execute_prompt_agent": False,
                    "may_apply_to_specgraph": False,
                    "may_mutate_candidate_source_artifacts": False,
                    "may_mutate_canonical_specs": False,
                    "may_write_ontology_package": False,
                    "may_accept_ontology_terms": False,
                    "may_mark_candidate_accepted": False,
                    "may_mark_candidate_graph_accepted": False,
                    "may_create_branch_or_commit": False,
                    "may_open_pull_request": False,
                    "may_execute_git_service_operation": False,
                }
            ],
            "summary": {
                "status": "candidate_approval_intent_recorded",
                "intent_count": 1,
                "active_intent_count": 1,
                "workspace_count": 1,
            },
            "consumer_boundary": {
                "specspace_owned_state": True,
                "for_product_approval_workflow": True,
                "may_execute_specgraph": False,
                "may_execute_prompt_agent": False,
                "may_apply_to_specgraph": False,
                "may_mutate_candidate_source_artifacts": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_mark_candidate_graph_accepted": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
                "may_execute_git_service_operation": False,
            },
            "authority_boundary": {
                "candidate_approval_intent_state_is_authority": False,
                "candidate_approval_decision_authority": False,
                "specgraph_artifact_authority": False,
                "ontology_authority": False,
                "git_service_authority": False,
                "canonical_mutations_allowed": False,
            },
        }
        (runs_dir / "idea_to_spec_candidate_approval_intents.json").write_text(
            json.dumps(intent_state),
            encoding="utf-8",
        )

    def write_product_candidate_approval_artifacts(
        self,
        specgraph_dir: Path,
        *,
        intent_authority_expanded: object = False,
        promotion_gate_authority_value: object = False,
        intent_repair_session_ref: str = "runs/idea_to_spec_repair_session.json",
        intent_promotion_gate_ref: str = "runs/idea_to_spec_promotion_gate.json",
        repair_session_ready_for_candidate_approval: bool = True,
        include_repaired_handoff: bool = False,
        repaired_handoff_stale_ref: bool = False,
        repaired_handoff_stale_repair_session_ref: bool = False,
        execution_ok: bool = True,
        execution_dry_run: bool = False,
        publication_ok: bool = True,
        publication_dry_run: bool = False,
    ) -> None:
        runs_dir = specgraph_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        self.write_graph_repository_run_artifacts(
            runs_dir,
            repair_session_ready_for_candidate_approval=(
                repair_session_ready_for_candidate_approval
            ),
        )
        candidate_id = "idea-alpha"
        workspace_id = "idea-alpha"
        intent_state = {
            "artifact_kind": "specspace_idea_to_spec_candidate_approval_intent_state",
            "schema_version": 1,
            "state_owner": "SpecSpace",
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "source_artifacts": {
                "idea_to_spec_repair_session": "runs/idea_to_spec_repair_session.json",
                "idea_to_spec_promotion_gate": "runs/idea_to_spec_promotion_gate.json",
            },
            "intents": [
                {
                    "id": "candidate-approval-intent.idea-alpha.20260626T100000Z",
                    "status": "requested",
                    "requested_action": "approve_candidate_for_promotion_review",
                    "workspace_id": workspace_id,
                    "candidate_id": candidate_id,
                    "repair_session_id": "repair-session.idea-alpha",
                    "repair_session_ref": intent_repair_session_ref,
                    "promotion_gate_ref": intent_promotion_gate_ref,
                    "requested_by": "operator://specspace-local",
                    "reason": "Ready for promotion review.",
                    "created_at": "2026-06-26T10:00:00Z",
                    "updated_at": "2026-06-26T10:00:00Z",
                    "ready_for_candidate_approval": True,
                    "ready_for_platform_promotion": False,
                    "blocked_by": [],
                    "canonical_mutations_allowed": False,
                    "tracked_artifacts_written": False,
                    "may_execute_specgraph": False,
                    "may_execute_prompt_agent": False,
                    "may_apply_to_specgraph": False,
                    "may_mutate_candidate_source_artifacts": False,
                    "may_mutate_canonical_specs": False,
                    "may_write_ontology_package": False,
                    "may_accept_ontology_terms": False,
                    "may_mark_candidate_accepted": intent_authority_expanded,
                    "may_mark_candidate_graph_accepted": False,
                    "may_create_branch_or_commit": False,
                    "may_open_pull_request": False,
                    "may_execute_git_service_operation": False,
                }
            ],
            "summary": {
                "status": "candidate_approval_intent_recorded",
                "intent_count": 1,
                "active_intent_count": 1,
                "workspace_count": 1,
            },
            "consumer_boundary": {
                "specspace_owned_state": True,
                "for_product_approval_workflow": True,
                "may_execute_specgraph": False,
                "may_execute_prompt_agent": False,
                "may_apply_to_specgraph": False,
                "may_mutate_candidate_source_artifacts": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_mark_candidate_graph_accepted": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
                "may_execute_git_service_operation": False,
            },
            "authority_boundary": {
                "candidate_approval_intent_state_is_authority": False,
                "candidate_approval_decision_authority": False,
                "specgraph_artifact_authority": False,
                "ontology_authority": False,
                "git_service_authority": False,
                "canonical_mutations_allowed": False,
            },
        }
        promotion_gate = {
            "artifact_kind": "idea_to_spec_promotion_gate",
            "schema_version": 1,
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "authority_boundary": {
                "may_create_branch_or_commit": False,
                "may_open_pull_request": promotion_gate_authority_value,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
            },
            "summary": {
                "workspace_id": workspace_id,
                "candidate_id": candidate_id,
                "promotion_path_count": 1,
            },
        }
        execution_report = {
            "artifact_kind": "platform_product_repair_rerun_execution_report",
            "schema_version": 1,
            "ok": execution_ok,
            "dry_run": execution_dry_run,
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "specgraph_dir": str(specgraph_dir),
            "authority_boundary": {
                "executes_specgraph_make_target": not execution_dry_run,
                "executes_git_commands": False,
                "opens_pull_requests": False,
                "merges_pull_requests": False,
                "writes_ontology_packages": False,
                "accepts_ontology_terms": False,
                "mutates_canonical_specs": False,
                "publishes_private_artifacts": False,
            },
            "summary": {
                "status": "completed" if execution_ok else "failed",
                "error_count": 0 if execution_ok else 1,
                "repair_session_digest": "0" * 64,
                "rerun_report_digest": "1" * 64,
            },
        }
        publication_report = {
            "artifact_kind": "platform_product_repair_rerun_publication_report",
            "schema_version": 1,
            "ok": publication_ok,
            "dry_run": publication_dry_run,
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "specgraph_dir": str(specgraph_dir),
            "authority_boundary": {
                "executes_specgraph_make_target": not publication_dry_run,
                "executes_git_commands": False,
                "opens_pull_requests": False,
                "merges_pull_requests": False,
                "writes_ontology_packages": False,
                "accepts_ontology_terms": False,
                "mutates_canonical_specs": False,
                "publishes_private_artifacts": False,
            },
            "manifest": {
                "path": str(
                    specgraph_dir / "dist" / "specgraph-public" / "artifact_manifest.json"
                ),
                "present": publication_ok and not publication_dry_run,
                "sha256": "2" * 64 if publication_ok and not publication_dry_run else None,
            },
            "summary": {
                "status": "published" if publication_ok else "failed",
                "error_count": 0 if publication_ok else 1,
                "published_artifact_count": 4 if publication_ok else 0,
                "missing_artifact_count": 0 if publication_ok else 1,
            },
        }
        artifacts = {
            "idea_to_spec_candidate_approval_intents.json": intent_state,
            "idea_to_spec_promotion_gate.json": promotion_gate,
            "platform_product_repair_rerun_execution_report.json": execution_report,
            "platform_product_repair_rerun_publication_report.json": publication_report,
        }
        if include_repaired_handoff:
            active_candidate = {
                "artifact_kind": "active_idea_to_spec_candidate",
                "schema_version": 1,
                "contract_ref": "specgraph.idea-to-spec.active-candidate-source.v0.1",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "authority_boundary": {
                    "may_create_branch_or_commit": False,
                    "may_execute_prompt_agent": False,
                    "may_mark_candidate_graph_accepted": False,
                    "may_mutate_candidate_source_artifacts": False,
                    "may_mutate_canonical_specs": False,
                    "may_open_pull_request": False,
                    "may_publish_read_model": False,
                    "may_write_ontology_lockfile": False,
                    "may_write_ontology_package": False,
                },
                "readiness": {
                    "ready": True,
                    "review_state": "active_candidate_ready",
                    "blocked_by": [],
                },
                "summary": {
                    "candidate_id": candidate_id,
                    "workspace_route": f"/{workspace_id}",
                    "status": "active_candidate_ready",
                    "promotion_path_count": 1,
                },
            }
            repaired_promotion_gate = {
                **promotion_gate,
                "readiness": {
                    "ready": True,
                    "review_state": "ready_for_platform_promotion_request",
                    "blocked_by": [],
                },
            }
            repaired_repair_session = json.loads(
                (runs_dir / "idea_to_spec_repair_session.json").read_text(
                    encoding="utf-8"
                )
            )
            repaired_repair_session["source_artifacts"]["active_candidate"] = {
                "source_ref": "runs/repaired_active_idea_to_spec_candidate.json"
            }
            repaired_repair_session["source_artifacts"]["promotion_gate"] = {
                "source_ref": "runs/repaired_idea_to_spec_promotion_gate.json"
            }
            handoff_active_ref = (
                "runs/active_idea_to_spec_candidate.json"
                if repaired_handoff_stale_ref
                else "runs/repaired_active_idea_to_spec_candidate.json"
            )
            repaired_handoff = {
                "artifact_kind": "repaired_candidate_promotion_handoff_report",
                "schema_version": 1,
                "contract_ref": (
                    "specgraph.idea-to-spec.repaired-candidate-promotion-handoff.v0.1"
                ),
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": True,
                    "review_state": "repaired_candidate_promotion_handoff_ready",
                    "blocked_by": [],
                },
                "summary": {
                    "status": "repaired_candidate_promotion_handoff_ready",
                    "ready_for_candidate_approval": True,
                    "ready_for_platform_promotion": False,
                    "unresolved_candidate_gap_count": 0,
                    "unresolved_ontology_gap_count": 0,
                    "resolved_candidate_gap_count": 1,
                    "resolved_ontology_gap_count": 1,
                    "removed_gap_count": 2,
                },
                "output_artifacts": {
                    "repaired_active_candidate": {
                        "artifact_kind": "active_idea_to_spec_candidate",
                        "source_ref": handoff_active_ref,
                        "summary": active_candidate["summary"],
                    },
                    "repaired_repair_session": {
                        "artifact_kind": "idea_to_spec_repair_session_journal",
                        "source_ref": (
                            "runs/idea_to_spec_repair_session.json"
                            if repaired_handoff_stale_repair_session_ref
                            else "runs/repaired_idea_to_spec_repair_session.json"
                        ),
                        "summary": repaired_repair_session["summary"],
                    },
                    "repaired_promotion_gate": {
                        "artifact_kind": "idea_to_spec_promotion_gate",
                        "source_ref": "runs/repaired_idea_to_spec_promotion_gate.json",
                        "summary": repaired_promotion_gate["summary"],
                    },
                },
                "authority_boundary": {
                    "may_accept_ontology_terms": False,
                    "may_create_branch_or_commit": False,
                    "may_execute_prompt_agent": False,
                    "may_mark_candidate_graph_accepted": False,
                    "may_materialize_candidate_approval_decision": False,
                    "may_mutate_candidate_source_artifacts": False,
                    "may_mutate_canonical_specs": False,
                    "may_open_pull_request": False,
                    "may_publish_read_model": False,
                    "may_write_ontology_lockfile": False,
                    "may_write_ontology_package": False,
                },
            }
            artifacts.update(
                {
                    "repaired_active_idea_to_spec_candidate.json": active_candidate,
                    "repaired_idea_to_spec_promotion_gate.json": repaired_promotion_gate,
                    "repaired_idea_to_spec_repair_session.json": repaired_repair_session,
                    "repaired_candidate_promotion_handoff_report.json": repaired_handoff,
                }
            )
        for filename, payload in artifacts.items():
            (runs_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def write_product_repair_makefile(self, specgraph_dir: Path) -> None:
        makefile = """\
SPECSPACE_REPAIR_DRAFT_RERUN_REPORT_OUTPUT ?= runs/specspace_repair_draft_rerun_report.json
IDEA_TO_SPEC_REPAIR_SESSION_OUTPUT ?= runs/idea_to_spec_repair_session.json
IDEA_TO_SPEC_RERUN_PREVIEW_OUTPUT ?= runs/idea_to_spec_rerun_preview.json
IDEA_TO_SPEC_RERUN_MATERIALIZATION_OUTPUT ?= runs/idea_to_spec_rerun_materialization.json
REPAIRED_CANDIDATE_PROMOTION_HANDOFF_ACTIVE_CANDIDATE_OUTPUT ?= runs/repaired_active_idea_to_spec_candidate.json
REPAIRED_CANDIDATE_PROMOTION_HANDOFF_CANDIDATE_GRAPH_OUTPUT ?= runs/repaired_candidate_spec_graph.json
REPAIRED_CANDIDATE_PROMOTION_HANDOFF_PRE_SIB_OUTPUT ?= runs/repaired_pre_sib_coherence_report.json
REPAIRED_CANDIDATE_PROMOTION_HANDOFF_REPAIR_LOOP_OUTPUT ?= runs/repaired_candidate_repair_loop_report.json
REPAIRED_CANDIDATE_PROMOTION_HANDOFF_MATERIALIZATION_OUTPUT ?= runs/repaired_candidate_spec_materialization_report.json
REPAIRED_CANDIDATE_PROMOTION_HANDOFF_PROMOTION_GATE_OUTPUT ?= runs/repaired_idea_to_spec_promotion_gate.json
REPAIRED_CANDIDATE_PROMOTION_HANDOFF_REPAIR_SESSION_OUTPUT ?= runs/repaired_idea_to_spec_repair_session.json
REPAIRED_CANDIDATE_PROMOTION_HANDOFF_OUTPUT ?= runs/repaired_candidate_promotion_handoff_report.json

specspace-repair-draft-import-preview:
\t@mkdir -p $$(dirname "$(SPECSPACE_REPAIR_DRAFT_IMPORT_OUTPUT)")
\t@printf '%s\\n' '{"artifact_kind":"specspace_repair_draft_import_preview","contract_ref":"specgraph.idea-to-spec.specspace-repair-draft-import-preview.v0.1","canonical_mutations_allowed":false,"tracked_artifacts_written":false,"readiness":{"ready":true,"review_state":"repair_draft_import_preview_ready","blocked_by":[]},"summary":{"status":"repair_draft_import_preview_ready","accepted_for_rerun_count":1},"authority_boundary":{"may_accept_ontology_terms":false,"may_apply_answers_to_source_artifacts":false,"may_apply_decisions_to_source_artifacts":false,"may_create_branch_or_commit":false,"may_execute_prompt_agent":false,"may_import_into_specgraph":false,"may_mark_candidate_graph_accepted":false,"may_mutate_candidate_source_artifacts":false,"may_mutate_canonical_specs":false,"may_open_pull_request":false,"may_publish_read_model":false,"may_write_ontology_lockfile":false,"may_write_ontology_package":false}}' > "$(SPECSPACE_REPAIR_DRAFT_IMPORT_OUTPUT)"

specspace-repair-rerun-request-gate:
\t@mkdir -p $$(dirname "$(SPECSPACE_REPAIR_RERUN_REQUEST_OUTPUT)")
\t@printf '%s\\n' '{"artifact_kind":"specspace_repair_rerun_request_gate","contract_ref":"specgraph.idea-to-spec.specspace-repair-rerun-request-gate.v0.1","canonical_mutations_allowed":false,"tracked_artifacts_written":false,"readiness":{"ready":true,"review_state":"ready","blocked_by":[]},"summary":{"selected_request_id":"repair-rerun-request.idea-alpha","workspace_id":"idea-alpha-workspace","candidate_id":"idea-alpha"},"resolved_inputs":{"workspace_id":"idea-alpha-workspace","candidate_id":"idea-alpha"},"recommended_invocation":{"make_target":"product-workspace-requested-repair-draft-rerun"},"authority_boundary":{"may_execute_specgraph_from_request":false,"may_run_make_target_from_request":false,"may_mutate_canonical_specs":false,"may_write_ontology_package":false,"may_accept_ontology_terms":false,"may_create_branch_or_commit":false,"may_open_pull_request":false,"may_execute_git_service_operation":false}}' > "$(SPECSPACE_REPAIR_RERUN_REQUEST_OUTPUT)"

product-workspace-requested-repair-draft-rerun:
\t@mkdir -p $$(dirname "$(SPECSPACE_REPAIR_DRAFT_RERUN_REPORT_OUTPUT)") $$(dirname "$(IDEA_TO_SPEC_REPAIR_SESSION_OUTPUT)") $$(dirname "$(IDEA_TO_SPEC_RERUN_PREVIEW_OUTPUT)") $$(dirname "$(IDEA_TO_SPEC_RERUN_MATERIALIZATION_OUTPUT)")
\t@printf '%s\\n' '{"artifact_kind":"specspace_repair_draft_rerun_report","contract_ref":"specgraph.idea-to-spec.specspace-repair-draft-rerun.v0.1","readiness":{"ready":true,"review_state":"repair_draft_rerun_ready"},"summary":{"status":"ready"}}' > "$(SPECSPACE_REPAIR_DRAFT_RERUN_REPORT_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_repair_session_journal","contract_ref":"specgraph.idea-to-spec.repair-session-journal.v0.1","readiness":{"ready":true,"review_state":"repair_session_journal_ready"},"summary":{"candidate_id":"idea-alpha","workflow_lane":"product_idea_to_spec","ready_for_candidate_approval":true},"readiness_impact":{"intermediate_artifacts_ready":true,"ready_for_candidate_approval":true,"ready_for_platform_promotion":false},"authority_boundary":{"may_accept_ontology_terms":false,"may_apply_answers_to_source_artifacts":false,"may_apply_decisions_to_source_artifacts":false,"may_create_branch_or_commit":false,"may_execute_prompt_agent":false,"may_mark_candidate_graph_accepted":false,"may_mutate_candidate_source_artifacts":false,"may_mutate_canonical_specs":false,"may_open_pull_request":false,"may_publish_read_model":false,"may_write_ontology_lockfile":false,"may_write_ontology_package":false},"privacy_boundary":{"raw_idea_text_published":false,"raw_model_output_published":false,"raw_operator_note_published":false,"raw_prompt_published":false,"static_flags_are_asserted_invariants":true},"session":{"candidate_id":"idea-alpha","workflow_lane":"product_idea_to_spec","target_repository_role":"product_spec_workspace"},"source_artifacts":{"active_candidate":{"source_ref":"runs/active_idea_to_spec_candidate.json"},"clarification_requests":{"source_ref":"runs/idea_to_spec_clarification_requests.json"},"clarification_answers":{"source_ref":"runs/idea_to_spec_clarification_answers.json"},"ontology_decisions":{"source_ref":"runs/product_ontology_gap_review_decisions.json"},"rerun_input":{"source_ref":"runs/idea_to_spec_answer_rerun_input.json"},"rerun_preview":{"source_ref":"runs/idea_to_spec_rerun_preview.json"},"rerun_materialization":{"source_ref":"runs/idea_to_spec_rerun_materialization.json"},"promotion_gate":{"source_ref":"runs/idea_to_spec_promotion_gate.json"}}}' > "$(IDEA_TO_SPEC_REPAIR_SESSION_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_rerun_preview"}' > "$(IDEA_TO_SPEC_RERUN_PREVIEW_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_rerun_materialization"}' > "$(IDEA_TO_SPEC_RERUN_MATERIALIZATION_OUTPUT)"

product-workspace-repaired-promotion-handoff:
\t@mkdir -p $$(dirname "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_ACTIVE_CANDIDATE_OUTPUT)") $$(dirname "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_CANDIDATE_GRAPH_OUTPUT)") $$(dirname "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_PRE_SIB_OUTPUT)") $$(dirname "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_REPAIR_LOOP_OUTPUT)") $$(dirname "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_MATERIALIZATION_OUTPUT)") $$(dirname "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_PROMOTION_GATE_OUTPUT)") $$(dirname "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_REPAIR_SESSION_OUTPUT)") $$(dirname "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_OUTPUT)")
\t@printf '%s\\n' '{"artifact_kind":"active_idea_to_spec_candidate","contract_ref":"specgraph.idea-to-spec.active-candidate-source.v0.1","canonical_mutations_allowed":false,"tracked_artifacts_written":false,"readiness":{"ready":true,"review_state":"active_candidate_ready","blocked_by":[]},"summary":{"candidate_id":"idea-alpha","workspace_route":"/idea-alpha","status":"active_candidate_ready","promotion_path_count":1},"authority_boundary":{"may_create_branch_or_commit":false,"may_execute_prompt_agent":false,"may_mark_candidate_graph_accepted":false,"may_mutate_candidate_source_artifacts":false,"may_mutate_canonical_specs":false,"may_open_pull_request":false,"may_publish_read_model":false,"may_write_ontology_lockfile":false,"may_write_ontology_package":false}}' > "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_ACTIVE_CANDIDATE_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"candidate_spec_graph","readiness":{"ready":true,"review_state":"ready_for_pre_sib","blocked_by":[]},"summary":{"status":"ready_for_pre_sib"}}' > "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_CANDIDATE_GRAPH_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"pre_sib_coherence_report","readiness":{"ready":true,"review_state":"pre_sib_ready","blocked_by":[]},"summary":{"status":"pre_sib_ready"}}' > "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_PRE_SIB_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"candidate_repair_loop_report","readiness":{"ready":true,"review_state":"repair_preview_ready","blocked_by":[]},"summary":{"status":"repair_preview_ready"}}' > "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_REPAIR_LOOP_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"candidate_spec_materialization_report","readiness":{"ready":true,"review_state":"materialized_candidate_review_ready","blocked_by":[]},"summary":{"status":"materialized_candidate_review_ready"}}' > "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_MATERIALIZATION_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_promotion_gate","canonical_mutations_allowed":false,"tracked_artifacts_written":false,"readiness":{"ready":true,"review_state":"ready_for_platform_promotion_request","blocked_by":[]},"promotion_request":{"paths":["specs/nodes/SG-SPEC-CANDIDATE.yaml"]},"summary":{"workspace_id":"idea-alpha","candidate_id":"idea-alpha","promotion_path_count":1},"authority_boundary":{"may_create_branch_or_commit":false,"may_open_pull_request":false,"may_mutate_canonical_specs":false,"may_write_ontology_package":false}}' > "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_PROMOTION_GATE_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_repair_session_journal","contract_ref":"specgraph.idea-to-spec.repair-session-journal.v0.1","readiness":{"ready":true,"review_state":"repair_session_journal_ready","blocked_by":[]},"summary":{"candidate_id":"idea-alpha","workflow_lane":"product_idea_to_spec","ready_for_candidate_approval":true,"ready_for_platform_promotion":false,"unresolved_ontology_gap_count":0,"unresolved_candidate_gap_count":0},"readiness_impact":{"intermediate_artifacts_ready":true,"ready_for_candidate_approval":true,"ready_for_platform_promotion":false},"authority_boundary":{"may_accept_ontology_terms":false,"may_apply_answers_to_source_artifacts":false,"may_apply_decisions_to_source_artifacts":false,"may_create_branch_or_commit":false,"may_execute_prompt_agent":false,"may_mark_candidate_graph_accepted":false,"may_mutate_candidate_source_artifacts":false,"may_mutate_canonical_specs":false,"may_open_pull_request":false,"may_publish_read_model":false,"may_write_ontology_lockfile":false,"may_write_ontology_package":false},"privacy_boundary":{"raw_idea_text_published":false,"raw_model_output_published":false,"raw_operator_note_published":false,"raw_prompt_published":false,"static_flags_are_asserted_invariants":true},"session":{"candidate_id":"idea-alpha","workflow_lane":"product_idea_to_spec","target_repository_role":"product_spec_workspace"},"source_artifacts":{"active_candidate":{"source_ref":"runs/repaired_active_idea_to_spec_candidate.json"},"clarification_requests":{"source_ref":"runs/idea_to_spec_clarification_requests.json"},"clarification_answers":{"source_ref":"runs/idea_to_spec_clarification_answers.json"},"ontology_decisions":{"source_ref":"runs/product_ontology_gap_review_decisions.json"},"rerun_input":{"source_ref":"runs/idea_to_spec_answer_rerun_input.json"},"rerun_preview":{"source_ref":"runs/idea_to_spec_rerun_preview.json"},"rerun_materialization":{"source_ref":"runs/idea_to_spec_rerun_materialization.json"},"promotion_gate":{"source_ref":"runs/repaired_idea_to_spec_promotion_gate.json"}}}' > "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_REPAIR_SESSION_OUTPUT)"
\t@printf '%s\\n' '{"artifact_kind":"repaired_candidate_promotion_handoff_report","contract_ref":"specgraph.idea-to-spec.repaired-candidate-promotion-handoff.v0.1","canonical_mutations_allowed":false,"tracked_artifacts_written":false,"readiness":{"ready":true,"review_state":"repaired_candidate_promotion_handoff_ready","blocked_by":[]},"summary":{"status":"repaired_candidate_promotion_handoff_ready","ready_for_candidate_approval":true,"ready_for_platform_promotion":false,"unresolved_candidate_gap_count":0,"unresolved_ontology_gap_count":0,"resolved_candidate_gap_count":1,"resolved_ontology_gap_count":1,"removed_gap_count":2},"output_artifacts":{"repaired_active_candidate":{"artifact_kind":"active_idea_to_spec_candidate","source_ref":"runs/repaired_active_idea_to_spec_candidate.json","summary":{"candidate_id":"idea-alpha","workspace_route":"/idea-alpha","status":"active_candidate_ready","promotion_path_count":1}},"repaired_repair_session":{"artifact_kind":"idea_to_spec_repair_session_journal","source_ref":"runs/repaired_idea_to_spec_repair_session.json","summary":{"candidate_id":"idea-alpha","workflow_lane":"product_idea_to_spec","ready_for_candidate_approval":true,"ready_for_platform_promotion":false,"unresolved_ontology_gap_count":0,"unresolved_candidate_gap_count":0}},"repaired_promotion_gate":{"artifact_kind":"idea_to_spec_promotion_gate","source_ref":"runs/repaired_idea_to_spec_promotion_gate.json","summary":{"workspace_id":"idea-alpha","candidate_id":"idea-alpha","promotion_path_count":1}}},"authority_boundary":{"may_accept_ontology_terms":false,"may_create_branch_or_commit":false,"may_execute_prompt_agent":false,"may_mark_candidate_graph_accepted":false,"may_materialize_candidate_approval_decision":false,"may_mutate_candidate_source_artifacts":false,"may_mutate_canonical_specs":false,"may_open_pull_request":false,"may_publish_read_model":false,"may_write_ontology_lockfile":false,"may_write_ontology_package":false}}' > "$(REPAIRED_CANDIDATE_PROMOTION_HANDOFF_OUTPUT)"

publish-bundle:
\t@mkdir -p dist/specgraph-public/runs
\t@printf '%s\\n' '{"artifact_kind":"artifact_manifest"}' > dist/specgraph-public/artifact_manifest.json
\t@cp runs/idea_to_spec_repair_session.json dist/specgraph-public/runs/idea_to_spec_repair_session.json
\t@cp runs/specspace_repair_draft_rerun_report.json dist/specgraph-public/runs/specspace_repair_draft_rerun_report.json
\t@cp runs/idea_to_spec_rerun_preview.json dist/specgraph-public/runs/idea_to_spec_rerun_preview.json
\t@cp runs/idea_to_spec_rerun_materialization.json dist/specgraph-public/runs/idea_to_spec_rerun_materialization.json
\t@test ! -f runs/repaired_candidate_promotion_handoff_report.json || cp runs/repaired_candidate_promotion_handoff_report.json dist/specgraph-public/runs/repaired_candidate_promotion_handoff_report.json
\t@test ! -f runs/repaired_active_idea_to_spec_candidate.json || cp runs/repaired_active_idea_to_spec_candidate.json dist/specgraph-public/runs/repaired_active_idea_to_spec_candidate.json
\t@test ! -f runs/repaired_candidate_spec_graph.json || cp runs/repaired_candidate_spec_graph.json dist/specgraph-public/runs/repaired_candidate_spec_graph.json
\t@test ! -f runs/repaired_pre_sib_coherence_report.json || cp runs/repaired_pre_sib_coherence_report.json dist/specgraph-public/runs/repaired_pre_sib_coherence_report.json
\t@test ! -f runs/repaired_candidate_repair_loop_report.json || cp runs/repaired_candidate_repair_loop_report.json dist/specgraph-public/runs/repaired_candidate_repair_loop_report.json
\t@test ! -f runs/repaired_candidate_spec_materialization_report.json || cp runs/repaired_candidate_spec_materialization_report.json dist/specgraph-public/runs/repaired_candidate_spec_materialization_report.json
\t@test ! -f runs/repaired_idea_to_spec_repair_session.json || cp runs/repaired_idea_to_spec_repair_session.json dist/specgraph-public/runs/repaired_idea_to_spec_repair_session.json
\t@test ! -f runs/repaired_idea_to_spec_promotion_gate.json || cp runs/repaired_idea_to_spec_promotion_gate.json dist/specgraph-public/runs/repaired_idea_to_spec_promotion_gate.json
\t@test ! -f runs/idea_maturity_metrics_report.json || cp runs/idea_maturity_metrics_report.json dist/specgraph-public/runs/idea_maturity_metrics_report.json
\t@test ! -f runs/idea_maturity_metrics_validation_report.json || cp runs/idea_maturity_metrics_validation_report.json dist/specgraph-public/runs/idea_maturity_metrics_validation_report.json
"""
        (specgraph_dir / "Makefile").write_text(makefile, encoding="utf-8")

    def write_real_idea_answer_continuation_makefile(self, specgraph_dir: Path) -> None:
        makefile = """\
real-idea-intake-continue-from-specspace-answers:
\t@mkdir -p $(REAL_IDEA_SMOKE_RUN_DIR)
\t@test -f $(SPECSPACE_REAL_IDEA_ANSWER_STATE)
\t@printf '%s\\n' '{"artifact_kind":"specspace_real_idea_answer_import_preview","contract_ref":"specgraph.idea-to-spec.specspace-real-idea-answer-import-preview.v0.1","readiness":{"ready":true,"review_state":"specspace_real_idea_answers_ready_for_continuation"},"summary":{"status":"specspace_real_idea_answers_ready_for_continuation","answer_count":1,"accepted_answer_count":1},"authority_boundary":{"may_execute_specgraph":false,"may_execute_platform":false,"may_apply_answers":false,"may_mutate_canonical_specs":false,"may_write_ontology_package":false,"may_accept_ontology_terms":false,"may_create_branch_or_commit":false},"privacy_boundary":{"raw_idea_text_published":false,"raw_prompt_published":false,"raw_model_output_published":false}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/specspace_real_idea_answer_import_preview.json
\t@printf '%s\\n' '{"artifact_kind":"real_idea_answer_continuation_report","contract_ref":"specgraph.idea-to-spec.real-idea-answer-continuation.v0.1","readiness":{"ready":true,"review_state":"real_idea_answer_continuation_ready"},"summary":{"status":"real_idea_answer_continuation_ready","answer_count":1,"accepted_answer_count":1},"authority_boundary":{"may_execute_specgraph":false,"may_execute_platform":false,"may_apply_answers":false,"may_mutate_canonical_specs":false,"may_write_ontology_package":false,"may_accept_ontology_terms":false,"may_create_branch_or_commit":false},"privacy_boundary":{"raw_idea_text_published":false,"raw_prompt_published":false,"raw_model_output_published":false},"outputs":{"validated_answers":"$(REAL_IDEA_SMOKE_RUN_DIR)/idea_intake_clarification_answers.json"}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/real_idea_answer_continuation_report.json
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_clarification_answer_set","answers":[{"request_id":"clarification.intake.domain","answer_kind":"answer_question","status":"accepted_for_candidate"}]}' > $(REAL_IDEA_SMOKE_RUN_DIR)/real_idea_answer_set.json
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_clarification_answers","readiness":{"ready":true,"review_state":"answers_ready_for_rerun"},"summary":{"accepted_answer_count":1}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/idea_intake_clarification_answers.json
\t@printf '%s\\n' '{"artifact_kind":"user_idea_intake_session","readiness":{"ready":true,"review_state":"ready_for_event_storming_intake"},"summary":{"status":"ready_for_event_storming_intake"}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/clarified_user_idea_intake_session.json
\t@printf '%s\\n' '{"artifact_kind":"intake_session_candidate_source_report","readiness":{"ready":true,"review_state":"candidate_source_ready"},"summary":{"status":"candidate_source_ready"}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/intake_session_candidate_source_report.json
\t@printf '%s\\n' '{"artifact_kind":"active_idea_to_spec_candidate","readiness":{"ready":false,"review_state":"active_candidate_review_required"},"summary":{"status":"active_candidate_review_required","candidate_id":"idea-alpha"}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/active_idea_to_spec_candidate.json
"""
        (specgraph_dir / "Makefile").write_text(makefile, encoding="utf-8")

    def write_real_idea_entry_intake_makefile(self, specgraph_dir: Path) -> None:
        makefile = """\
real-idea-intake-from-entry-request:
\t@mkdir -p $(REAL_IDEA_SMOKE_RUN_DIR)
\t@test -f $(SPECSPACE_REAL_IDEA_ENTRY_REQUESTS)
\t@printf '%s\\n' '{"artifact_kind":"specspace_real_idea_entry_request_import_preview","contract_ref":"specgraph.idea-to-spec.specspace-real-idea-entry-request-import-preview.v0.1","readiness":{"ready":true,"review_state":"real_idea_entry_request_ready_for_intake"},"summary":{"status":"real_idea_entry_request_ready_for_intake","request_selected":true},"authority_boundary":{"may_execute_specgraph":false,"may_execute_platform":false,"may_mutate_canonical_specs":false,"may_write_ontology_package":false,"may_accept_ontology_terms":false,"may_create_branch_or_commit":false},"privacy_boundary":{"raw_idea_text_published":false,"raw_prompt_published":false,"raw_model_output_published":false}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/specspace_real_idea_entry_request_import_preview.json
\t@printf '%s\\n' '{"artifact_kind":"real_idea_entry_request_intake_report","contract_ref":"specgraph.idea-to-spec.real-idea-entry-request-intake.v0.1","readiness":{"ready":true,"review_state":"real_idea_entry_request_intake_materialized"},"summary":{"status":"real_idea_entry_request_intake_materialized","candidate_id":"idea-alpha","intake_session_ready":false},"authority_boundary":{"may_execute_specgraph":false,"may_execute_platform":false,"may_mutate_user_intent":false,"may_mutate_canonical_specs":false,"may_write_ontology_package":false,"may_accept_ontology_terms":false,"may_create_branch_or_commit":false},"privacy_boundary":{"raw_idea_text_published":false,"raw_prompt_published":false,"raw_model_output_published":false}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/real_idea_entry_request_intake_report.json
\t@printf '%s\\n' '{"artifact_kind":"user_idea_raw_input","local_only":true,"privacy_boundary":{"raw_idea_text_local_only":true,"raw_idea_text_public_safe":false}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/local_operator_user_idea_raw_input.json
\t@printf '%s\\n' '{"artifact_kind":"user_idea_intake_session","readiness":{"ready":false,"review_state":"needs_clarification"},"summary":{"status":"needs_clarification","clarification_question_count":4},"privacy_boundary":{"raw_idea_text_published":false}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/user_idea_intake_session.json
\t@printf '%s\\n' '{"artifact_kind":"user_idea_intake_interview_report","summary":{"status":"needs_clarification"},"privacy_boundary":{"raw_idea_text_published_in_report":false}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/user_idea_intake_interview_report.json
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_clarification_requests","readiness":{"ready":true,"review_state":"clarification_requests_ready"},"summary":{"status":"clarification_requests_ready","request_count":4}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/idea_intake_clarification_requests.json
\t@printf '%s\\n' '{"artifact_kind":"real_idea_answer_template","contract_ref":"specgraph.real-idea.answer-template.v0.1","readiness":{"ready":true,"review_state":"answer_template_ready"},"summary":{"status":"answer_template_ready","target_count":4},"authority_boundary":{"may_execute_specgraph":false},"privacy_boundary":{"raw_idea_text_published":false}}' > $(REAL_IDEA_SMOKE_RUN_DIR)/real_idea_answer_template.json
"""
        (specgraph_dir / "Makefile").write_text(makefile, encoding="utf-8")

    def write_workspace_initialization_execution_report(
        self,
        path: Path,
        *,
        workspace_id: str = "pantry-rotation",
        display_name: str = "Pantry Rotation",
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "artifact_kind": "platform_product_workspace_initialization_execution_report",
                    "schema_version": 1,
                    "ok": True,
                    "dry_run": False,
                    "workspace": {
                        "workspace_id": workspace_id,
                        "display_name": display_name,
                        "route": f"/{workspace_id}",
                        "workspace_root": f"/tmp/{workspace_id}",
                        "governance_profile": "product_workspace",
                        "repository_role": "product_spec_workspace",
                    },
                    "catalog_ref": "runs/product_workspaces_catalog.json",
                    "specgraph_initialization_report_ref": (
                        f"runs/{workspace_id}/product_workspace_initialization.json"
                    ),
                    "authority_boundary": {
                        "creates_git_commits": False,
                        "opens_pull_requests": False,
                        "publishes_read_models": False,
                        "mutates_canonical_specs": False,
                        "writes_ontology_packages": False,
                        "accepts_ontology_terms": False,
                    },
                    "summary": {
                        "status": "workspace_initialization_executed",
                        "error_count": 0,
                        "specgraph_executed": True,
                        "catalog_written": True,
                        "workspace_files_created": True,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def write_real_idea_intake_execution_request_state(
        self,
        path: Path,
        *,
        workspace_id: str = "pantry-rotation",
        entry_request_id: str = "real-idea-entry.pantry-rotation.20260704.abcd12",
        workspace_initialization_ref: str = "runs/pantry-rotation/platform_product_workspace_initialization_execution_report.json",
        authority_expanded: bool = False,
        authority_value=None,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        may_execute_platform = (
            authority_value
            if authority_value is not None
            else True
            if authority_expanded
            else False
        )
        path.write_text(
            json.dumps(
                {
                    "artifact_kind": "specspace_real_idea_intake_execution_request_state",
                    "schema_version": 1,
                    "state_owner": "SpecSpace",
                    "workspace_id": workspace_id,
                    "canonical_mutations_allowed": False,
                    "tracked_artifacts_written": False,
                    "consumer_boundary": {
                        "may_execute_specgraph": False,
                        "may_execute_platform": may_execute_platform,
                        "may_execute_git_service": False,
                        "may_mutate_canonical_specs": False,
                        "may_write_ontology_package": False,
                        "may_accept_ontology_terms": False,
                        "may_create_branch_or_commit": False,
                        "may_open_pull_request": False,
                    },
                    "authority_boundary": {
                        "may_execute_specgraph": False,
                        "may_execute_platform": False,
                        "may_execute_git_service": False,
                        "may_mutate_canonical_specs": False,
                        "may_write_ontology_package": False,
                        "may_accept_ontology_terms": False,
                        "may_create_branch_or_commit": False,
                        "may_open_pull_request": False,
                    },
                    "requests": [
                        {
                            "request_id": "real-idea-intake-execution.pantry-rotation.20260704.abcd12",
                            "workspace_id": workspace_id,
                            "entry_request_id": entry_request_id,
                            "entry_requests_ref": "specspace-state://real_idea_entry_requests.json",
                            "workspace_initialization_ref": workspace_initialization_ref,
                            "status": "requested",
                            "consumer_boundary": {
                                "may_execute_specgraph": False,
                                "may_execute_platform": False,
                                "may_execute_git_service": False,
                                "may_mutate_canonical_specs": False,
                                "may_write_ontology_package": False,
                                "may_accept_ontology_terms": False,
                                "may_create_branch_or_commit": False,
                                "may_open_pull_request": False,
                            },
                            "authority_boundary": {
                                "may_execute_specgraph": False,
                                "may_execute_platform": False,
                                "may_execute_git_service": False,
                                "may_mutate_canonical_specs": False,
                                "may_write_ontology_package": False,
                                "may_accept_ontology_terms": False,
                                "may_create_branch_or_commit": False,
                                "may_open_pull_request": False,
                            },
                        }
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def write_real_idea_answer_continuation_execution_request_state(
        self,
        path: Path,
        *,
        workspace_id: str = "pantry-rotation",
        answer_state_ref: str = "specspace-state://idea_to_spec_intake_clarification_answers.json",
        workspace_initialization_ref: str = "runs/pantry-rotation/platform_product_workspace_initialization_execution_report.json",
        authority_expanded: bool = False,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        may_execute_platform = True if authority_expanded else False
        path.write_text(
            json.dumps(
                {
                    "artifact_kind": "specspace_real_idea_answer_continuation_execution_request_state",
                    "schema_version": 1,
                    "state_owner": "SpecSpace",
                    "canonical_mutations_allowed": False,
                    "tracked_artifacts_written": False,
                    "consumer_boundary": {
                        "may_execute_specgraph": False,
                        "may_execute_platform": may_execute_platform,
                        "may_apply_answers": False,
                        "may_mutate_canonical_specs": False,
                        "may_write_ontology_package": False,
                        "may_accept_ontology_terms": False,
                        "may_create_branch_or_commit": False,
                        "may_open_pull_request": False,
                    },
                    "authority_boundary": {
                        "may_execute_specgraph": False,
                        "may_execute_platform": False,
                        "may_mutate_canonical_specs": False,
                        "may_write_ontology_package": False,
                        "may_accept_ontology_terms": False,
                        "may_create_branch_or_commit": False,
                        "may_open_pull_request": False,
                    },
                    "requests": [
                        {
                            "request_id": "real-idea-answer-continuation-execute.pantry-rotation.20260704.abcd12",
                            "workspace_id": workspace_id,
                            "answer_state_ref": answer_state_ref,
                            "answer_template_ref": "runs/real_idea_smoke/real_idea_answer_template.json",
                            "intake_execution_ref": "runs/platform_real_idea_entry_intake_execution_report.json",
                            "workspace_initialization_ref": workspace_initialization_ref,
                            "status": "requested",
                            "consumer_boundary": {
                                "may_execute_specgraph": False,
                                "may_execute_platform": False,
                                "may_apply_answers": False,
                                "may_mutate_canonical_specs": False,
                                "may_write_ontology_package": False,
                                "may_accept_ontology_terms": False,
                                "may_create_branch_or_commit": False,
                                "may_open_pull_request": False,
                            },
                            "authority_boundary": {
                                "may_execute_specgraph": False,
                                "may_execute_platform": False,
                                "may_mutate_canonical_specs": False,
                                "may_write_ontology_package": False,
                                "may_accept_ontology_terms": False,
                                "may_create_branch_or_commit": False,
                                "may_open_pull_request": False,
                            },
                        }
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def write_real_idea_entry_intake_execution_report(
        self,
        path: Path,
        *,
        workspace_id: str = "pantry-rotation",
        authority_expanded: bool = False,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "artifact_kind": "platform_real_idea_entry_intake_execution_report",
                    "schema_version": 1,
                    "ok": True,
                    "dry_run": False,
                    "canonical_mutations_allowed": False,
                    "tracked_artifacts_written": False,
                    "authority_boundary": {
                        "executes_specgraph_make_target": True,
                        "executes_git_commands": False,
                        "opens_pull_requests": False,
                        "merges_pull_requests": False,
                        "writes_ontology_packages": authority_expanded,
                        "accepts_ontology_terms": False,
                        "mutates_canonical_specs": False,
                        "publishes_private_artifacts": False,
                    },
                    "summary": {
                        "status": "completed",
                        "workspace_id": workspace_id,
                        "intake_session_status": "needs_clarification",
                        "answer_template_status": "real_idea_answer_template_ready",
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def build_graph_repository_execution_plan(
        self,
        tmp_root: Path,
        *,
        repair_ready: bool = True,
        context_required_count: int = 0,
    ) -> Path:
        runs_dir = tmp_root / "runs"
        runs_dir.mkdir(parents=True)
        self.write_graph_repository_run_artifacts(
            runs_dir,
            repair_ready=repair_ready,
            context_required_count=context_required_count,
        )
        plan_path = tmp_root / "graph_repository_execution_plan.json"
        result = self.run_cli(
            "graph-repository",
            "plan",
            "--contract",
            "graph-repository-service.example.json",
            "--runs-dir",
            str(runs_dir),
            "--output",
            str(plan_path),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return plan_path

    def build_graph_repository_promotion_request(self, tmp_root: Path) -> Path:
        plan_path = self.build_graph_repository_execution_plan(tmp_root)
        output = tmp_root / "graph_repository_promotion_request.json"
        result = self.run_cli(
            "graph-repository",
            "promotion-request",
            "--plan",
            str(plan_path),
            "--candidate-id",
            "idea-alpha",
            "--path",
            "specs/nodes/SG-SPEC-CANDIDATE.yaml",
            "--title",
            "Add candidate spec graph",
            "--body",
            "Review materialized candidate graph from the idea-to-spec flow.",
            "--output",
            str(output),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return output

    def build_product_candidate_promotion_request(self, tmp_root: Path) -> tuple[Path, Path]:
        plan_path = self.build_graph_repository_execution_plan(tmp_root)
        approval_decision = self.write_candidate_approval_decision(tmp_root)
        output = tmp_root / "graph_repository_promotion_request.json"
        result = self.run_cli(
            "product-candidate-promotion",
            "request",
            "--plan",
            str(plan_path),
            "--approval-decision",
            str(approval_decision),
            "--output",
            str(output),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return output, approval_decision

    def write_candidate_approval_decision(
        self,
        tmp_root: Path,
        *,
        candidate_id: str = "idea-alpha",
        workflow_lane: str = "product_idea_to_spec",
        target_repository_role: str = "product_spec_workspace",
        decision_state: str = "approved",
        ready: bool = True,
        paths: list[str] | None = None,
    ) -> Path:
        tmp_root.mkdir(parents=True, exist_ok=True)
        approval_path = tmp_root / "candidate_approval_decision.json"
        promotion_paths = paths or ["specs/nodes/SG-SPEC-CANDIDATE.yaml"]
        approval_path.write_text(
            json.dumps(
                {
                    "artifact_kind": "candidate_approval_decision",
                    "schema_version": 1,
                    "contract_ref": (
                        "specgraph.idea-to-spec.candidate-approval-decision.v0.1"
                    ),
                    "canonical_mutations_allowed": False,
                    "ontology_writes_allowed": False,
                    "tracked_artifacts_written": False,
                    "workspace": {
                        "workspace_id": candidate_id,
                        "mode": workflow_lane,
                        "repository_role": target_repository_role,
                        "public_route": f"/{candidate_id}",
                    },
                    "candidate": {
                        "candidate_id": candidate_id,
                        "display_name": "Idea Alpha",
                        "active_candidate_ref": (
                            "runs/active_idea_to_spec_candidate.json"
                        ),
                        "promotion_gate_ref": (
                            "runs/idea_to_spec_promotion_gate.json"
                        ),
                    },
                    "decision": {
                        "requested_state": decision_state,
                        "state": decision_state,
                        "operator_ref": "operator://workspace-owner",
                        "reason": "Approve review-ready candidate promotion.",
                        "conditions": [],
                    },
                    "readiness": {
                        "ready": ready,
                        "review_state": "candidate_approval_ready"
                        if ready
                        else "candidate_approval_blocked",
                        "blocked_by": [] if ready else ["decision_not_approved"],
                    },
                    "promotion_request": {
                        "platform_artifact_kind": (
                            "platform_graph_repository_promotion_request"
                        ),
                        "paths": promotion_paths,
                        "requires_git_service_execution": True,
                    },
                    "source_artifacts": {
                        "candidate_approval_gate": (
                            "runs/platform_candidate_approval_intent_gate_report.json"
                        ),
                        "repair_session": "runs/idea_to_spec_repair_session.json",
                        "promotion_gate": "runs/idea_to_spec_promotion_gate.json",
                        "platform_repair_execution": (
                            "runs/platform_product_repair_rerun_execution_report.json"
                        ),
                        "platform_repair_publication": (
                            "runs/platform_product_repair_rerun_publication_report.json"
                        ),
                    },
                    "authority_boundary": {
                        "may_execute_prompt_agent": False,
                        "may_mutate_candidate_source_artifacts": False,
                        "may_mutate_canonical_specs": False,
                        "may_write_ontology_package": False,
                        "may_write_ontology_lockfile": False,
                        "may_mark_candidate_graph_accepted": False,
                        "may_create_branch_or_commit": False,
                        "may_open_pull_request": False,
                        "may_publish_read_model": False,
                        "may_execute_git_service_operation": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return approval_path

    def git_service_request(self) -> dict:
        return {
            "schema_version": 1,
            "artifact_kind": "platform_git_service_operation_request",
            "operation": "prepare_worktree",
            "request_id": "req-001",
            "correlation_id": "corr-001",
            "idempotency_key": "prepare:idea-alpha:graph-candidate/idea-alpha",
            "actor_ref": "specspace:user/operator",
            "repository_ref": "git@github.com:0al-spec/SpecGraph.git",
            "candidate_id": "idea-alpha",
            "candidate_ref": "graph-candidate/idea-alpha",
            "base_ref": "main",
            "requested_at": "2026-06-21T00:00:00Z",
            "dry_run": True,
            "inputs": {
                "promotion_request": "runs/graph_repository_promotion_request.json",
                "execution_plan": "runs/graph_repository_execution_plan.json",
                "candidate_approval_decision": "runs/candidate_approval_decision.json",
            },
            "authority_boundary": {
                "specspace_direct_git_write": False,
                "canonical_spec_mutation_without_review": False,
                "ontology_package_write": False,
                "auto_merge": False,
                "private_artifact_publication": False,
            },
        }

    def git_service_response(self) -> dict:
        return {
            "schema_version": 1,
            "artifact_kind": "platform_git_service_operation_response",
            "operation": "prepare_worktree",
            "request_id": "req-001",
            "response_id": "resp-001",
            "correlation_id": "corr-001",
            "idempotency_key": "prepare:idea-alpha:graph-candidate/idea-alpha",
            "status": "dry_run",
            "started_at": "2026-06-21T00:00:00Z",
            "completed_at": "2026-06-21T00:00:01Z",
            "outputs": {
                "candidate_ref": "graph-candidate/idea-alpha",
                "report": ".platform/graph_repository_worktree_prepare_report.json",
            },
            "audit_events": [
                {
                    "artifact_kind": "platform_git_service_audit_event",
                    "event_id": "audit-001",
                    "operation": "prepare_worktree",
                    "created_at": "2026-06-21T00:00:01Z",
                    "summary": "prepared candidate worktree in dry-run mode",
                }
            ],
            "writes": {
                "canonical_specs": False,
                "ontology_packages": False,
                "candidate_ref": True,
                "review": False,
                "read_model": False,
                "private_artifacts": False,
            },
        }

    def run_git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def create_graph_repository_checkout(self, tmp_root: Path) -> Path:
        source = tmp_root / "source"
        source.mkdir()
        self.run_git(source, "init")
        self.run_git(source, "config", "user.email", "test@example.com")
        self.run_git(source, "config", "user.name", "Platform Tests")
        (source / "README.md").write_text("# Test graph\n", encoding="utf-8")
        self.run_git(source, "add", "README.md")
        self.run_git(source, "commit", "-m", "Initial graph")
        self.run_git(source, "branch", "-M", "main")

        origin = tmp_root / "origin.git"
        subprocess.run(
            ["git", "clone", "--bare", str(source), str(origin)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        checkout = tmp_root / "checkout"
        subprocess.run(
            ["git", "clone", str(origin), str(checkout)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return checkout

    def prepare_graph_repository_worktree(self, tmp_root: Path) -> Path:
        plan_path = self.build_graph_repository_execution_plan(tmp_root)
        repository_dir = self.create_graph_repository_checkout(tmp_root)
        workspace_dir = tmp_root / "candidate-worktree"
        result = self.run_cli(
            "graph-repository",
            "prepare-worktree",
            "--plan",
            str(plan_path),
            "--repository-dir",
            str(repository_dir),
            "--candidate-id",
            "idea-alpha",
            "--workspace-dir",
            str(workspace_dir),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return workspace_dir

    def commit_graph_repository_candidate(self, tmp_root: Path) -> tuple[Path, Path]:
        workspace_dir = self.prepare_graph_repository_worktree(tmp_root)
        spec_path = workspace_dir / "specs" / "nodes" / "SG-SPEC-CANDIDATE.yaml"
        spec_path.parent.mkdir(parents=True)
        spec_path.write_text(
            "id: SG-SPEC-CANDIDATE\nsummary: Candidate spec\n",
            encoding="utf-8",
        )
        prepare_report = (
            workspace_dir
            / ".platform"
            / "graph_repository_worktree_prepare_report.json"
        )
        result = self.run_cli(
            "graph-repository",
            "commit-worktree",
            "--prepare-report",
            str(prepare_report),
            "--worktree-dir",
            str(workspace_dir),
            "--path",
            "specs/nodes/SG-SPEC-CANDIDATE.yaml",
            "--message",
            "Add candidate spec",
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return (
            workspace_dir,
            workspace_dir / ".platform" / "graph_repository_review_commit_report.json",
        )

    def write_fake_gh(self, tmp_root: Path) -> Path:
        fake_gh = tmp_root / "fake-gh"
        fake_gh.write_text(
            "#!/usr/bin/env sh\n"
            "printf '%s\\n' 'https://github.com/example/repo/pull/123'\n",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        return fake_gh

    def write_failing_fake_gh(self, tmp_root: Path) -> Path:
        fake_gh = tmp_root / "fake-gh-fail"
        fake_gh.write_text(
            "#!/usr/bin/env sh\n"
            "printf '%s\\n' 'simulated gh failure' >&2\n"
            "exit 1\n",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        return fake_gh

    def write_fake_gh_view(self, tmp_root: Path, payload: dict[str, object]) -> Path:
        fake_gh = tmp_root / "fake-gh-view"
        fake_gh.write_text(
            "#!/usr/bin/env sh\n"
            f"printf '%s\\n' {json.dumps(json.dumps(payload))}\n",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        return fake_gh

    def open_graph_repository_review(self, tmp_root: Path) -> tuple[Path, Path]:
        workspace_dir, commit_report = self.commit_graph_repository_candidate(tmp_root)
        fake_gh = self.write_fake_gh(tmp_root)
        result = self.run_cli(
            "graph-repository",
            "open-review",
            "--commit-report",
            str(commit_report),
            "--worktree-dir",
            str(workspace_dir),
            "--base",
            "main",
            "--title",
            "Add candidate spec",
            "--body",
            "Review candidate spec graph.",
            "--gh-bin",
            str(fake_gh),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return (
            workspace_dir,
            workspace_dir / ".platform" / "graph_repository_open_review_report.json",
        )

    def write_product_candidate_promotion_execution_report(
        self,
        tmp_root: Path,
        *,
        dry_run: bool = False,
        open_review_dry_run: bool = False,
    ) -> tuple[Path, Path, Path]:
        workspace_dir, open_review_report = self.open_graph_repository_review(tmp_root)
        report_path = tmp_root / "product_candidate_promotion_execution_report.json"
        payload = {
            "schema_version": 1,
            "artifact_kind": "platform_product_candidate_promotion_execution_report",
            "generated_at": "2026-06-21T16:00:00Z",
            "promotion_request_ref": str(
                tmp_root / "graph_repository_promotion_request.json"
            ),
            "approval_decision_ref": str(tmp_root / "candidate_approval_decision.json"),
            "deployment_profile_ref": str(
                REPO_ROOT / "deployment-profiles/product-idea-to-spec-workbench.json"
            ),
            "contract_ref": str(
                REPO_ROOT / "git-service-operation-contract.example.json"
            ),
            "graph_repository_plan_ref": str(
                tmp_root / "graph_repository_execution_plan.json"
            ),
            "git_service_execution_report_ref": str(
                workspace_dir / ".platform/git_service_promotion_execution_report.json"
            ),
            "ok": True,
            "dry_run": dry_run,
            "open_review_dry_run": open_review_dry_run,
            "workflow_lane": "product_idea_to_spec",
            "candidate_id": "idea-alpha",
            "candidate_branch": "graph-candidate/idea-alpha",
            "repository_dir": str(tmp_root / "checkout"),
            "workspace_dir": str(workspace_dir),
            "git_service_execution": {
                "artifact_kind": "platform_git_service_promotion_execution_report",
                "ok": True,
                "dry_run": dry_run,
                "open_review_dry_run": open_review_dry_run,
                "report_refs": {"open_review": str(open_review_report)},
                "operations": [
                    {"name": "prepare_worktree", "status": "succeeded"},
                    {"name": "commit_candidate", "status": "succeeded"},
                    {
                        "name": "open_review",
                        "status": "dry_run"
                        if open_review_dry_run
                        else "succeeded",
                    },
                ],
            },
            "operations": [],
            "authority_boundary": {
                "specspace_direct_git_write": False,
                "controlled_git_service_execution": True,
                "creates_candidate_worktree_or_branch": True,
                "creates_candidate_commit": True,
                "opens_pull_requests": not open_review_dry_run,
                "merges_pull_requests": False,
                "publishes_read_models": False,
                "canonical_spec_mutation_without_review": False,
                "ontology_package_write": False,
                "ontology_term_acceptance": False,
                "private_artifact_publication": False,
            },
            "diagnostics": [],
            "summary": {
                "status": "completed",
                "error_count": 0,
                "worktree_prepared": True,
                "commit_created": True,
                "review_opened": not open_review_dry_run,
                "read_model_published": False,
            },
        }
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        return report_path, workspace_dir, open_review_report

    def merged_graph_repository_review_status(self, tmp_root: Path) -> tuple[Path, Path]:
        workspace_dir, open_review_report = self.open_graph_repository_review(tmp_root)
        fake_gh = self.write_fake_gh_view(
            tmp_root,
            {
                "number": 123,
                "url": "https://github.com/example/repo/pull/123",
                "state": "MERGED",
                "isDraft": False,
                "mergedAt": "2026-06-21T16:00:00Z",
                "mergeCommit": {"oid": "abc123"},
                "headRefName": "graph-candidate/idea-alpha",
                "baseRefName": "main",
                "reviewDecision": "APPROVED",
            },
        )
        result = self.run_cli(
            "graph-repository",
            "review-status",
            "--open-review-report",
            str(open_review_report),
            "--worktree-dir",
            str(workspace_dir),
            "--gh-bin",
            str(fake_gh),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return (
            workspace_dir,
            workspace_dir / ".platform" / "graph_repository_review_status_report.json",
        )

    def write_public_read_model_bundle(self, tmp_root: Path) -> Path:
        bundle_dir = tmp_root / "public-bundle"
        bundle_dir.mkdir()
        (bundle_dir / "artifact_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "artifact_kind": "specgraph_public_artifact_manifest",
                    "files": ["runs/candidate_spec_graph.json"],
                }
            ),
            encoding="utf-8",
        )
        (bundle_dir / "runs").mkdir()
        (bundle_dir / "runs" / "candidate_spec_graph.json").write_text(
            json.dumps({"artifact_kind": "candidate_spec_graph"}),
            encoding="utf-8",
        )
        return bundle_dir

    def test_workspace_list_json(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write(CATALOG)
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "list",
                "--catalog",
                catalog.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["workspaces"]), 2)
        self.assertEqual(payload["workspaces"][0]["project_id"], "specgraph-core")
        self.assertEqual(payload["workspaces"][1]["status"], "archived")

    def test_workspace_list_filters_kind_and_status(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write(CATALOG)
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "list",
                "--catalog",
                catalog.name,
                "--kind",
                "product_workspace",
                "--status",
                "archived",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("product-a", result.stdout)
        self.assertNotIn("specgraph-core", result.stdout)

    def test_workspace_list_reports_malformed_yaml(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write("workspaces: [\n")
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "list",
                "--catalog",
                catalog.name,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("platform: error: cannot parse catalog", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_workspace_doctor_reports_malformed_yaml(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write("workspaces: [\n")
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "doctor",
                "--catalog",
                catalog.name,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("platform: error: cannot parse catalog", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_workspace_doctor_accepts_initialized_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / "ProductA"
            (workspace / "specs").mkdir(parents=True)
            (workspace / "runs").mkdir()
            (workspace / "docs" / "proposals").mkdir(parents=True)
            (workspace / "specgraph.project.yaml").write_text("project: product-a\n")
            catalog_text = f"""\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "{root}"
workspaces:
  - project_id: product-a
    display_name: Product A
    kind: product_workspace
    status: active
    path: "{workspace}"
    governance_profile: product_workspace
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
      proposals_root: docs/proposals
"""

            with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
                catalog.write(catalog_text)
                catalog.flush()

                result = self.run_cli(
                    "workspace",
                    "doctor",
                    "--catalog",
                    catalog.name,
                    "--format",
                    "json",
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["diagnostics"], [])

    def test_workspace_doctor_reports_catalog_misconfigurations(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            missing_workspace = Path(root) / "MissingProduct"
            catalog_text = f"""\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "{root}"
workspaces:
  - project_id: product-a
    display_name: Product A
    kind: product_workspace
    status: active
    path: "{missing_workspace}"
    governance_profile: self_hosted_bootstrap
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
    registry:
      registry_id: missing-registry
      import_policy: review_first
"""

            with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
                catalog.write(catalog_text)
                catalog.flush()

                result = self.run_cli(
                    "workspace",
                    "doctor",
                    "--catalog",
                    catalog.name,
                    "--format",
                    "json",
                )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("catalog_schema_invalid", codes)
        self.assertIn("workspace_profile_mismatch", codes)
        self.assertIn("unknown_registry_id", codes)
        self.assertIn("workspace_path_missing", codes)

    def test_workspace_doctor_reports_schema_errors_without_traceback(self) -> None:
        catalog_text = """\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "${ORG_ROOT}"
workspaces:
  - not-a-mapping
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write(catalog_text)
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "doctor",
                "--catalog",
                catalog.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("catalog_schema_invalid", codes)

    def test_workspace_doctor_sorts_multiple_schema_errors(self) -> None:
        catalog_text = """\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "${ORG_ROOT}"
workspaces:
  - project_id: "Has Space"
    display_name: ""
    kind: not_a_real_kind
    status: pending
    path: "relative/not/absolute"
    governance_profile: product_workspace
    specgraph_config: specgraph.project.yaml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write(catalog_text)
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "doctor",
                "--catalog",
                catalog.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(result.stdout)
        schema_diagnostics = [
            d for d in payload["diagnostics"] if d["code"] == "catalog_schema_invalid"
        ]
        self.assertGreater(len(schema_diagnostics), 1)

    def test_workspace_doctor_reports_specgraph_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / "ProductA"
            (workspace / "specs").mkdir(parents=True)
            (workspace / "runs").mkdir()
            (workspace / "docs" / "proposals").mkdir(parents=True)
            (workspace / "specgraph.project.yaml").mkdir()
            catalog_text = f"""\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "{root}"
workspaces:
  - project_id: product-a
    display_name: Product A
    kind: product_workspace
    status: active
    path: "{workspace}"
    governance_profile: product_workspace
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
      proposals_root: docs/proposals
"""

            with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
                catalog.write(catalog_text)
                catalog.flush()

                result = self.run_cli(
                    "workspace",
                    "doctor",
                    "--catalog",
                    catalog.name,
                    "--format",
                    "json",
                )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("path_wrong_type", codes)

    def test_workspace_doctor_warns_when_org_root_is_unresolved(self) -> None:
        result = self.run_cli(
            "workspace",
            "doctor",
            "--format",
            "json",
            env_overrides={"ORG_ROOT": None, "PLATFORM_WORKSPACES_CATALOG": None},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("org_root_unresolved", codes)
        self.assertIn("workspace_path_unresolved", codes)

    def test_graph_repository_validate_accepts_example_contract(self) -> None:
        result = self.run_cli(
            "graph-repository",
            "validate",
            "--contract",
            "graph-repository-service.example.json",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["summary"]["operation_count"], 6)

    def test_git_service_validate_accepts_example_contract(self) -> None:
        result = self.run_cli(
            "git-service",
            "validate-contract",
            "--contract",
            "git-service-operation-contract.example.json",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["summary"]["operation_count"], 5)

    def test_deployment_profile_validate_accepts_example_profiles(self) -> None:
        for profile, mode in (
            (
                "deployment-profile.product-idea-to-spec.example.json",
                "controlled_promotion",
            ),
            (
                "deployment-profile.specgraph-bootstrap-internal.example.json",
                "dry_run_only",
            ),
        ):
            result = self.run_cli(
                "deployment-profile",
                "validate",
                "--profile",
                profile,
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["diagnostics"], [])
            self.assertEqual(payload["summary"]["git_service_mode"], mode)

    def test_deployment_profile_validate_rejects_product_bootstrap_leak(
        self,
    ) -> None:
        profile = json.loads(
            (
                REPO_ROOT / "deployment-profile.product-idea-to-spec.example.json"
            ).read_text(encoding="utf-8")
        )
        profile["hides"].remove("specgraph_bootstrap")
        profile["authority_boundary"]["exposes_bootstrap_surfaces"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(profile, handle)
            handle.flush()

            result = self.run_cli(
                "deployment-profile",
                "validate",
                "--profile",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("deployment_profile_product_surface_leaks_bootstrap", codes)
        self.assertIn("deployment_profile_product_exposes_bootstrap", codes)

    def test_deployment_profile_validate_rejects_extra_product_repository_role(
        self,
    ) -> None:
        profile = json.loads(
            (
                REPO_ROOT / "deployment-profile.product-idea-to-spec.example.json"
            ).read_text(encoding="utf-8")
        )
        profile["git_service"]["allowed_target_repository_roles"].append(
            "specgraph_bootstrap"
        )
        profile["git_service"]["denied_target_repository_roles"] = []
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(profile, handle)
            handle.flush()

            result = self.run_cli(
                "deployment-profile",
                "validate",
                "--profile",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("deployment_profile_product_repository_role_expanded", codes)

    def test_git_service_validate_rejects_missing_operation(self) -> None:
        contract = json.loads(
            (REPO_ROOT / "git-service-operation-contract.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["operations"] = [
            operation
            for operation in contract["operations"]
            if operation["name"] != "publish_read_model"
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "git-service",
                "validate-contract",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_operation_missing", codes)

    def test_git_service_validate_rejects_lock_scope_mismatch(self) -> None:
        contract = json.loads(
            (REPO_ROOT / "git-service-operation-contract.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["operations"][0]["lock_scopes"] = ["review_ref"]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "git-service",
                "validate-contract",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_lock_scope_missing", codes)

    def test_git_service_validate_rejects_missing_approval_contract_input(
        self,
    ) -> None:
        contract = json.loads(
            (REPO_ROOT / "git-service-operation-contract.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["operations"][0]["required_inputs"].remove(
            "candidate_approval_decision"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "git-service",
                "validate-contract",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_required_input_missing", codes)

    def test_git_service_validate_accepts_request_and_response(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json") as request_handle:
            json.dump(self.git_service_request(), request_handle)
            request_handle.flush()

            request_result = self.run_cli(
                "git-service",
                "validate-request",
                "--request",
                request_handle.name,
                "--format",
                "json",
            )

        with tempfile.NamedTemporaryFile("w", suffix=".json") as response_handle:
            json.dump(self.git_service_response(), response_handle)
            response_handle.flush()

            response_result = self.run_cli(
                "git-service",
                "validate-response",
                "--response",
                response_handle.name,
                "--format",
                "json",
            )

        self.assertEqual(request_result.returncode, 0, request_result.stderr)
        self.assertEqual(response_result.returncode, 0, response_result.stderr)
        request_payload = json.loads(request_result.stdout)
        response_payload = json.loads(response_result.stdout)
        self.assertTrue(request_payload["ok"])
        self.assertTrue(response_payload["ok"])
        self.assertEqual(request_payload["summary"]["operation"], "prepare_worktree")
        self.assertEqual(response_payload["summary"]["operation"], "prepare_worktree")

    def test_git_service_validate_rejects_authority_expansion_request(self) -> None:
        request = self.git_service_request()
        request["authority_boundary"]["auto_merge"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(request, handle)
            handle.flush()

            result = self.run_cli(
                "git-service",
                "validate-request",
                "--request",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_operation_request_schema_invalid", codes)

    def test_git_service_validate_rejects_missing_approval_request_input(
        self,
    ) -> None:
        request = self.git_service_request()
        del request["inputs"]["candidate_approval_decision"]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(request, handle)
            handle.flush()

            result = self.run_cli(
                "git-service",
                "validate-request",
                "--request",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_operation_request_input_missing", codes)

    def test_git_service_execute_promotion_dry_run_plans_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            approval_decision = self.write_candidate_approval_decision(tmp_root)
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"
            output = tmp_root / "git_service_promotion_execution_report.json"

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--dry-run",
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_git_service_promotion_execution_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["workflow_lane"], "product_idea_to_spec")
            self.assertEqual(
                payload["deployment_profile"]["profile_id"],
                "product_idea_to_spec_workbench",
            )
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["operation_count"], 3)
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["prepare_worktree"], "dry_run")
            self.assertEqual(statuses["commit_candidate"], "skipped_dry_run")
            self.assertEqual(statuses["open_review"], "skipped_dry_run")
            self.assertFalse(workspace_dir.exists())
            self.assertTrue(output.is_file())

    def test_git_service_execute_promotion_runs_local_adapter_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            approval_decision = self.write_candidate_approval_decision(tmp_root)
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            materialized_source = tmp_root / "materialized"
            spec_path = materialized_source / "specs" / "nodes" / "SG-SPEC-CANDIDATE.yaml"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text(
                "id: SG-SPEC-CANDIDATE\nsummary: Candidate spec\n",
                encoding="utf-8",
            )
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--materialized-source-dir",
                str(materialized_source),
                "--open-review-dry-run",
                "--repo",
                "0al-spec/SpecGraph",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertFalse(payload["dry_run"])
            self.assertTrue(payload["open_review_dry_run"])
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["prepare_worktree"], "succeeded")
            self.assertEqual(statuses["commit_candidate"], "succeeded")
            self.assertEqual(statuses["open_review"], "dry_run")
            self.assertEqual(len(payload["copied_materialized_files"]), 1)
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "git_service_promotion_execution_report.json"
                ).is_file()
            )
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_worktree_prepare_report.json"
                ).is_file()
            )
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_review_commit_report.json"
                ).is_file()
            )
            self.assertTrue((workspace_dir / "specs/nodes/SG-SPEC-CANDIDATE.yaml").is_file())
            subject = self.run_git(
                workspace_dir,
                "log",
                "-1",
                "--pretty=%s",
            ).stdout.strip()
            self.assertEqual(subject, "Add candidate spec graph")

    def test_git_service_execute_promotion_rejects_not_ok_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request_path = self.build_graph_repository_promotion_request(
                tmp_root
            )
            approval_decision = self.write_candidate_approval_decision(tmp_root)
            promotion_request = json.loads(
                promotion_request_path.read_text(encoding="utf-8")
            )
            promotion_request["ok"] = False
            promotion_request_path.write_text(
                json.dumps(promotion_request),
                encoding="utf-8",
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request_path),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(tmp_root / "missing"),
                "--workspace-dir",
                str(tmp_root / "candidate-worktree"),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_promotion_request_not_ok", codes)

    def test_git_service_execute_promotion_requires_approved_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                decision_state="rejected",
                ready=False,
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(tmp_root / "missing"),
                "--workspace-dir",
                str(tmp_root / "candidate-worktree"),
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_candidate_approval_not_approved", codes)
        self.assertIn("git_service_candidate_approval_not_ready", codes)
        self.assertEqual(payload["operations"], [])

    def test_git_service_execute_promotion_rejects_approval_candidate_mismatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                candidate_id="other-idea",
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(tmp_root / "missing"),
                "--workspace-dir",
                str(tmp_root / "candidate-worktree"),
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_candidate_approval_candidate_mismatch", codes)
        self.assertEqual(payload["operations"], [])

    def test_git_service_execute_promotion_rejects_approval_path_mismatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                paths=["docs/proposals/OTHER.md"],
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(tmp_root / "missing"),
                "--workspace-dir",
                str(tmp_root / "candidate-worktree"),
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_candidate_approval_paths_mismatch", codes)
        self.assertEqual(payload["operations"], [])

    def test_git_service_execute_promotion_rejects_bootstrap_target_under_product_profile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request_path = self.build_graph_repository_promotion_request(
                tmp_root
            )
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                workflow_lane="specgraph_bootstrap",
                target_repository_role="specgraph_bootstrap",
            )
            promotion_request = json.loads(
                promotion_request_path.read_text(encoding="utf-8")
            )
            promotion_request["workflow_lane"] = "specgraph_bootstrap"
            promotion_request["target_repository_role"] = "specgraph_bootstrap"
            promotion_request["authority_profile"] = "maintainer_bootstrap_controlled"
            promotion_request_path.write_text(
                json.dumps(promotion_request),
                encoding="utf-8",
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request_path),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(tmp_root / "missing"),
                "--workspace-dir",
                str(tmp_root / "candidate-worktree"),
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("deployment_profile_workflow_lane_denied", codes)
        self.assertIn("deployment_profile_target_repository_role_denied", codes)
        self.assertIn("deployment_profile_authority_profile_denied", codes)

    def test_git_service_execute_promotion_rejects_bootstrap_internal_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request_path = self.build_graph_repository_promotion_request(
                tmp_root
            )
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                workflow_lane="specgraph_bootstrap",
                target_repository_role="specgraph_bootstrap",
            )
            promotion_request = json.loads(
                promotion_request_path.read_text(encoding="utf-8")
            )
            promotion_request["workflow_lane"] = "specgraph_bootstrap"
            promotion_request["deployment_profile_id"] = "specgraph_bootstrap_internal"
            promotion_request["target_repository_role"] = "specgraph_bootstrap"
            promotion_request["authority_profile"] = "maintainer_bootstrap_controlled"
            promotion_request_path.write_text(
                json.dumps(promotion_request),
                encoding="utf-8",
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request_path),
                "--approval-decision",
                str(approval_decision),
                "--deployment-profile",
                "deployment-profile.specgraph-bootstrap-internal.example.json",
                "--repository-dir",
                str(tmp_root / "missing"),
                "--workspace-dir",
                str(tmp_root / "candidate-worktree"),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("deployment_profile_git_service_dry_run_only", codes)

    def test_git_service_finalize_promotion_publishes_read_model_after_merge(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "git-service",
                "finalize-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_git_service_promotion_finalization_report",
            )
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertEqual(payload["review_state"], "merged")
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["review_status"], "succeeded")
            self.assertEqual(statuses["publish_read_model"], "succeeded")
            self.assertTrue(payload["summary"]["read_model_published"])
            self.assertTrue((output_dir / "artifact_manifest.json").is_file())
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "git_service_promotion_finalization_report.json"
                ).is_file()
            )

    def test_git_service_finalize_promotion_resolves_relative_review_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, _open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "git-service",
                "finalize-promotion",
                "--contract",
                str(REPO_ROOT / "git-service-operation-contract.example.json"),
                "--open-review-report",
                ".platform/graph_repository_open_review_report.json",
                "--worktree-dir",
                ".",
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
                cwd=workspace_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertEqual(payload["review_state"], "merged")
            self.assertTrue(output_dir.joinpath("artifact_manifest.json").is_file())

    def test_git_service_finalize_promotion_rejects_unmerged_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "OPEN",
                    "isDraft": False,
                    "mergedAt": None,
                    "mergeCommit": None,
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "git-service",
                "finalize-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["review_state"], "open")
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("git_service_review_not_merged", codes)
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["publish_read_model"], "skipped_review_not_merged")
            self.assertFalse(output_dir.exists())

    def test_graph_repository_validate_rejects_auto_merge(self) -> None:
        contract = json.loads(
            (REPO_ROOT / "graph-repository-service.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["promotion_policy"]["auto_merge_allowed"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "graph-repository",
                "validate",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_auto_merge_not_allowed", codes)

    def test_graph_repository_validate_rejects_non_commit_canonical_write(
        self,
    ) -> None:
        contract = json.loads(
            (REPO_ROOT / "graph-repository-service.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["supported_operations"][0]["writes_canonical_store"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "graph-repository",
                "validate",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "graph_repository_operation_canonical_write_mismatch",
            codes,
        )

    def test_graph_repository_validate_rejects_empty_validation_gate(self) -> None:
        contract = json.loads(
            (REPO_ROOT / "graph-repository-service.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["validation_gates"]["required_before_branch"] = []
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "graph-repository",
                "validate",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_contract_schema_invalid", codes)
        self.assertIn("graph_repository_validation_gate_empty", codes)

    def test_graph_repository_validate_requires_repair_session_branch_gate(
        self,
    ) -> None:
        contract = json.loads(
            (REPO_ROOT / "graph-repository-service.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["validation_gates"]["required_before_branch"].remove(
            "idea_to_spec_repair_session"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "graph-repository",
                "validate",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_repair_session_gate_missing", codes)

    def test_graph_repository_plan_builds_readonly_execution_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            output = runs_dir / "graph_repository_execution_plan.json"
            self.write_graph_repository_run_artifacts(runs_dir)

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                str(Path("graph-repository-service.example.json").resolve()),
                "--runs-dir",
                str(runs_dir),
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_execution_plan",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["read_only"])
            self.assertTrue(payload["ready_for_branch"])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertEqual(payload["write_actions_executed"], [])
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            operations = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(operations["prepare_branch"], "ready")
            self.assertEqual(
                operations["create_commit"],
                "blocked_until_prepare_branch",
            )

    def test_graph_repository_plan_rejects_missing_required_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(runs_dir)
            (runs_dir / "candidate_repair_loop_report.json").unlink()

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                str(Path("graph-repository-service.example.json").resolve()),
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_artifact_missing", codes)
        self.assertFalse(payload["ok"])

    def test_graph_repository_plan_requires_repair_session_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(runs_dir)
            (runs_dir / "idea_to_spec_repair_session.json").unlink()

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        missing = [
            diagnostic
            for diagnostic in payload["diagnostics"]
            if diagnostic["code"] == "graph_repository_artifact_missing"
        ]
        self.assertTrue(
            any(
                "idea_to_spec_repair_session.json" in diagnostic["subject"]
                for diagnostic in missing
            )
        )
        self.assertFalse(payload["ok"])

    def test_graph_repository_plan_blocks_when_repair_session_not_approval_ready(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                repair_session_ready_for_candidate_approval=False,
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        operations = {
            operation["name"]: operation for operation in payload["operations"]
        }
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["ready_for_branch"])
        blockers = set(operations["prepare_branch"]["reason"].split(","))
        self.assertIn("repair_session_not_ready_for_candidate_approval", blockers)

    def test_graph_repository_plan_rejects_stale_repair_session_source_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                repair_session_stale_source_ref=True,
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_repair_session_source_ref_stale", codes)
        self.assertFalse(payload["ok"])

    def test_graph_repository_plan_rejects_write_capable_repair_session(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                repair_session_authority_expanded=True,
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_repair_session_authority_expanded", codes)
        self.assertFalse(payload["ok"])

    def test_graph_repository_plan_blocks_when_candidate_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                candidate_ready=False,
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        operations = {
            operation["name"]: operation for operation in payload["operations"]
        }
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["ready_for_branch"])
        self.assertEqual(operations["prepare_branch"]["status"], "blocked")
        self.assertEqual(operations["prepare_branch"]["reason"], "candidate_not_ready")

    def test_graph_repository_plan_accepts_repaired_handoff_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                candidate_ready=False,
                repair_session_ready_for_candidate_approval=False,
            )
            self.write_graph_repository_repaired_run_artifacts(runs_dir)

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--repaired-handoff",
                "repaired_candidate_promotion_handoff_report.json",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        operations = {
            operation["name"]: operation for operation in payload["operations"]
        }
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source_mode"], "repaired_handoff")
        self.assertTrue(payload["ready_for_branch"])
        self.assertEqual(operations["validate_candidate_graph"]["status"], "ready")
        self.assertEqual(operations["prepare_branch"]["status"], "ready")
        source_keys = {artifact["key"] for artifact in payload["source_artifacts"]}
        self.assertIn("repaired_handoff", source_keys)
        self.assertIn("repaired_active_candidate", source_keys)
        self.assertIn("repaired_repair_session", source_keys)
        self.assertIn("repaired_promotion_gate", source_keys)

    def test_graph_repository_plan_accepts_repaired_handoff_filesystem_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                candidate_ready=False,
                repair_session_ready_for_candidate_approval=False,
            )
            self.write_graph_repository_repaired_run_artifacts(runs_dir)

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--repaired-handoff",
                str(runs_dir / "repaired_candidate_promotion_handoff_report.json"),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["ready_for_branch"])
        self.assertEqual(payload["runs_dir"], str(runs_dir.resolve()))
        repaired_handoff = next(
            artifact
            for artifact in payload["source_artifacts"]
            if artifact["key"] == "repaired_handoff"
        )
        self.assertTrue(repaired_handoff["available"])
        self.assertEqual(
            repaired_handoff["source_ref"],
            "runs/repaired_candidate_promotion_handoff_report.json",
        )

    def test_graph_repository_plan_accepts_isolated_repaired_source_refs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            runs_dir = specgraph_dir / "runs" / "ui-started-smoke"
            runs_dir.mkdir(parents=True)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                candidate_ready=False,
                repair_session_ready_for_candidate_approval=False,
            )
            self.write_graph_repository_repaired_run_artifacts(runs_dir)
            active_ref = "runs/ui-started-smoke/repaired_active_idea_to_spec_candidate.json"
            session_ref = "runs/ui-started-smoke/repaired_idea_to_spec_repair_session.json"
            gate_ref = "runs/ui-started-smoke/repaired_idea_to_spec_promotion_gate.json"
            repair_session_path = runs_dir / "repaired_idea_to_spec_repair_session.json"
            repair_session = json.loads(repair_session_path.read_text(encoding="utf-8"))
            repair_session["source_artifacts"]["active_candidate"]["source_ref"] = active_ref
            repair_session["source_artifacts"]["promotion_gate"]["source_ref"] = gate_ref
            repair_session_path.write_text(json.dumps(repair_session), encoding="utf-8")
            handoff_path = runs_dir / "repaired_candidate_promotion_handoff_report.json"
            handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff["output_artifacts"]["repaired_active_candidate"]["source_ref"] = active_ref
            handoff["output_artifacts"]["repaired_repair_session"]["source_ref"] = session_ref
            handoff["output_artifacts"]["repaired_promotion_gate"]["source_ref"] = gate_ref
            handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                str(Path("graph-repository-service.example.json").resolve()),
                "--runs-dir",
                str(runs_dir),
                "--repaired-handoff",
                str(handoff_path),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["ready_for_branch"])

    def test_graph_repository_plan_prefers_runs_dir_repaired_handoff_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            runs_dir = tmp_root / "runs"
            runs_dir.mkdir()
            self.write_graph_repository_run_artifacts(
                runs_dir,
                candidate_ready=False,
                repair_session_ready_for_candidate_approval=False,
            )
            self.write_graph_repository_repaired_run_artifacts(runs_dir)
            operator_cwd = tmp_root / "operator"
            operator_cwd.mkdir()
            (
                operator_cwd / "repaired_candidate_promotion_handoff_report.json"
            ).write_text(
                json.dumps({"artifact_kind": "wrong_cwd_handoff"}),
                encoding="utf-8",
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                str(Path("graph-repository-service.example.json").resolve()),
                "--runs-dir",
                str(runs_dir),
                "--repaired-handoff",
                "repaired_candidate_promotion_handoff_report.json",
                "--format",
                "json",
                cwd=operator_cwd,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        repaired_handoff = next(
            artifact
            for artifact in payload["source_artifacts"]
            if artifact["key"] == "repaired_handoff"
        )
        self.assertTrue(repaired_handoff["available"])
        self.assertEqual(
            repaired_handoff["source_ref"],
            "runs/repaired_candidate_promotion_handoff_report.json",
        )

    def test_graph_repository_plan_repaired_handoff_ignores_stale_default_session(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(runs_dir)
            default_session_path = runs_dir / "idea_to_spec_repair_session.json"
            default_session = json.loads(default_session_path.read_text(encoding="utf-8"))
            default_session["source_artifacts"]["active_candidate"]["source_ref"] = (
                "runs/stale_active_idea_to_spec_candidate.json"
            )
            default_session_path.write_text(
                json.dumps(default_session),
                encoding="utf-8",
            )
            self.write_graph_repository_repaired_run_artifacts(runs_dir)

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--repaired-handoff",
                "repaired_candidate_promotion_handoff_report.json",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source_mode"], "repaired_handoff")
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertNotIn("graph_repository_repair_session_source_ref_stale", codes)

    def test_graph_repository_plan_rejects_stale_repaired_handoff_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(runs_dir)
            self.write_graph_repository_repaired_run_artifacts(
                runs_dir,
                stale_handoff_ref=True,
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--repaired-handoff",
                "repaired_candidate_promotion_handoff_report.json",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_approval_repaired_handoff_ref_stale", codes)
        self.assertFalse(payload["ok"])

    def test_graph_repository_plan_repaired_session_diagnostic_uses_repaired_subject(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(runs_dir)
            self.write_graph_repository_repaired_run_artifacts(runs_dir)
            repaired_session_path = runs_dir / "repaired_idea_to_spec_repair_session.json"
            repaired_session = json.loads(
                repaired_session_path.read_text(encoding="utf-8")
            )
            repaired_session["source_artifacts"]["active_candidate"]["source_ref"] = (
                "runs/stale_repaired_active_idea_to_spec_candidate.json"
            )
            repaired_session_path.write_text(
                json.dumps(repaired_session),
                encoding="utf-8",
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--repaired-handoff",
                "repaired_candidate_promotion_handoff_report.json",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        diagnostic = next(
            item
            for item in payload["diagnostics"]
            if item["code"] == "graph_repository_repair_session_source_ref_stale"
        )
        self.assertTrue(
            diagnostic["subject"].startswith(
                "runs.repaired_idea_to_spec_repair_session.json"
            )
        )

    def test_graph_repository_plan_blocks_unresolved_ontology_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                unresolved_ontology_gap_count=2,
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        operations = {
            operation["name"]: operation for operation in payload["operations"]
        }
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["ready_for_branch"])
        self.assertEqual(operations["validate_candidate_graph"]["status"], "blocked")
        self.assertEqual(operations["prepare_branch"]["status"], "blocked")
        blockers = set(operations["prepare_branch"]["reason"].split(","))
        self.assertIn("rerun_preview_unresolved_ontology_gaps", blockers)
        self.assertIn("rerun_materialization_unresolved_ontology_gaps", blockers)

    def test_graph_repository_plan_blocks_missing_unresolved_gap_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                include_unresolved_ontology_gap_count=False,
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        operations = {
            operation["name"]: operation for operation in payload["operations"]
        }
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_required_summary_count_missing", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_for_branch"])
        blockers = set(operations["prepare_branch"]["reason"].split(","))
        self.assertIn("rerun_preview_unresolved_gap_count_invalid", blockers)
        self.assertIn("rerun_materialization_unresolved_gap_count_invalid", blockers)

    def test_graph_repository_plan_blocks_malformed_unresolved_gap_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                unresolved_ontology_gap_count="unknown",
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_required_summary_count_invalid", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_for_branch"])

    def test_graph_repository_plan_rejects_artifact_authority_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                candidate_authority_expanded=True,
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_artifact_authority_expanded", codes)
        self.assertFalse(payload["ok"])

    def test_product_repair_rerun_plan_builds_execution_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            output = specgraph_dir / "runs" / "product_repair_rerun_plan.json"

            result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_repair_rerun_execution_plan",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["ready_to_execute"])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertEqual(
                payload["target_make"]["target"],
                "product-workspace-requested-repair-draft-rerun",
            )
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertEqual(payload["summary"]["workspace_id"], "idea-alpha-workspace")

    def test_product_repair_rerun_import_preview_rebases_draft_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            repair_session_path = specgraph_dir / "runs" / "idea_to_spec_repair_session.json"
            repair_session = json.loads(repair_session_path.read_text(encoding="utf-8"))
            repair_session["session"]["session_id"] = "repair-session.idea-alpha"
            repair_session_path.write_text(json.dumps(repair_session), encoding="utf-8")
            draft_state = Path(tmp_dir) / "specspace-state" / "idea_to_spec_repair_drafts.json"
            draft_state.parent.mkdir(parents=True)
            draft_state.write_text(
                json.dumps(
                    {
                        "artifact_kind": "specspace_idea_to_spec_repair_draft_state",
                        "schema_version": 1,
                        "state_owner": "SpecSpace",
                        "canonical_mutations_allowed": False,
                        "tracked_artifacts_written": False,
                        "source_artifacts": {
                            "idea_to_spec_repair_session": "runs/stale_repair_session.json"
                        },
                        "drafts": [
                            {
                                "workspace_id": "idea-alpha-workspace",
                                "candidate_id": "idea-alpha",
                                "repair_session_ref": "runs/stale_repair_session.json",
                                "source_artifact": "runs/stale_repair_session.json",
                                "request_id": "clarification.repair.ontology-gap",
                                "allowed_action": "propose_project_local_term",
                                "answer_value": {"terms": ["Decision Owner"]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report_path = (
                specgraph_dir
                / "runs"
                / "platform_product_repair_draft_import_preview_execution_report.json"
            )

            result = self.run_cli(
                "product-repair-rerun",
                "import-preview",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--draft-state",
                str(draft_state),
                "--repair-session",
                "runs/idea_to_spec_repair_session.json",
                "--clarification-requests",
                "runs/idea_to_spec_clarification_requests.json",
                "--workspace-id",
                "idea-alpha-workspace",
                "--output",
                str(report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_repair_draft_import_preview_execution_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(
                payload["target_make"]["target"],
                "specspace-repair-draft-import-preview",
            )
            self.assertTrue(payload["draft_state_copied_to_run_dir"])
            handoff_state = json.loads(
                (
                    specgraph_dir
                    / "runs"
                    / "idea-alpha"
                    / "idea_to_spec_repair_drafts.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                handoff_state["source_artifacts"]["idea_to_spec_repair_session"],
                "runs/idea_to_spec_repair_session.json",
            )
            self.assertEqual(
                handoff_state["drafts"][0]["repair_session_ref"],
                "runs/idea_to_spec_repair_session.json",
            )
            self.assertEqual(
                handoff_state["drafts"][0]["repair_session_id"],
                "repair-session.idea-alpha",
            )
            self.assertTrue(payload["output_artifacts"]["import_preview"]["ready"])
            self.assertEqual(
                payload["output_artifacts"]["import_preview"]["summary"][
                    "accepted_for_rerun_count"
                ],
                1,
            )
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])

    def test_product_repair_rerun_request_gate_runs_specgraph_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            runs_dir = specgraph_dir / "runs"
            runs_dir.mkdir()
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            request_state = runs_dir / "idea_to_spec_repair_rerun_requests.json"
            request_state.write_text(
                json.dumps(
                    {
                        "artifact_kind": "specspace_idea_to_spec_repair_rerun_request_state",
                        "schema_version": 1,
                        "state_owner": "SpecSpace",
                        "canonical_mutations_allowed": False,
                        "tracked_artifacts_written": False,
                        "requests": [
                            {
                                "id": "repair-rerun-request.idea-alpha",
                                "status": "requested",
                                "requested_action": "prepare_repair_draft_rerun",
                                "workspace_id": "idea-alpha-workspace",
                                "candidate_id": "idea-alpha",
                                "repair_session_ref": "runs/stale_repair_session.json",
                                "draft_state_ref": "specspace-state://idea_to_spec_repair_drafts.json",
                                "import_preview_ref": "runs/stale_import_preview.json",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            run_dir = runs_dir / "idea-alpha"
            gate_path = run_dir / "specspace_repair_rerun_request_gate.json"
            report_path = (
                runs_dir
                / "platform_product_repair_rerun_request_gate_execution_report.json"
            )

            result = self.run_cli(
                "product-repair-rerun",
                "request-gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--rerun-request",
                "runs/idea_to_spec_repair_rerun_requests.json",
                "--import-preview",
                "runs/specspace_repair_draft_import_preview.json",
                "--repair-session",
                "runs/idea_to_spec_repair_session.json",
                "--workspace-id",
                "idea-alpha-workspace",
                "--output-gate",
                "runs/idea-alpha/specspace_repair_rerun_request_gate.json",
                "--output",
                str(report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_repair_rerun_request_gate_execution_report",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(gate_path.is_file())
            handoff_state = json.loads(
                (run_dir / "idea_to_spec_repair_rerun_requests.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                handoff_state["requests"][0]["repair_session_ref"],
                "runs/idea_to_spec_repair_session.json",
            )
            self.assertEqual(
                handoff_state["requests"][0]["import_preview_ref"],
                "runs/specspace_repair_draft_import_preview.json",
            )
            self.assertTrue(payload["request_state_copied_to_run_dir"])
            self.assertEqual(
                payload["target_make"]["target"],
                "specspace-repair-rerun-request-gate",
            )
            self.assertEqual(
                payload["output_artifacts"]["request_gate"]["artifact_kind"],
                "specspace_repair_rerun_request_gate",
            )
            self.assertTrue(payload["output_artifacts"]["request_gate"]["ready"])
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])

    def test_product_real_idea_continuation_execute_runs_specgraph_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)
            answer_state = (
                Path(tmp_dir)
                / "specspace-state"
                / "idea_to_spec_intake_clarification_answers.json"
            )
            answer_state.parent.mkdir(parents=True)
            answer_state.write_text(
                json.dumps(
                    {
                        "artifact_kind": "specspace_idea_intake_clarification_answer_state",
                        "answers": [
                            {
                                "workspace_id": "team-decision-log",
                                "request_id": "clarification.intake.question-active-frame-domain-refs",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = (
                specgraph_dir
                / "runs"
                / "platform_real_idea_answer_continuation_execution_report.json"
            )

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--answer-state",
                str(answer_state),
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_real_idea_answer_continuation_execution_report",
            )
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["dry_run"])
            self.assertEqual(
                payload["target_make"]["target"],
                "real-idea-intake-continue-from-specspace-answers",
            )
            self.assertEqual(
                payload["target_make"]["variables"]["REAL_IDEA_SMOKE_RUN_DIR"],
                "runs/idea-alpha",
            )
            self.assertTrue(payload["answer_state_copied_to_run_dir"])
            self.assertEqual(
                payload["target_make"]["variables"]["SPECSPACE_REAL_IDEA_ANSWER_STATE"],
                "runs/idea-alpha/idea_to_spec_intake_clarification_answers.json",
            )
            self.assertTrue(
                (
                    specgraph_dir
                    / "runs"
                    / "idea-alpha"
                    / "idea_to_spec_intake_clarification_answers.json"
                ).exists()
            )
            handoff_state = json.loads(
                (
                    specgraph_dir
                    / "runs"
                    / "idea-alpha"
                    / "idea_to_spec_intake_clarification_answers.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                handoff_state["source_artifacts"]["intake_clarification_requests"],
                "runs/idea-alpha/idea_intake_clarification_requests.json",
            )
            self.assertEqual(
                handoff_state["selected_workspace_id"],
                "team-decision-log",
            )
            self.assertEqual(
                handoff_state["source_artifacts"]["real_idea_answer_template"],
                "runs/idea-alpha/real_idea_answer_template.json",
            )
            self.assertEqual(payload["command_result"]["returncode"], 0)
            self.assertTrue(payload["output_artifacts"]["import_preview"]["ready"])
            self.assertTrue(
                payload["output_artifacts"]["continuation_report"]["ready"]
            )
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])

    def test_product_real_idea_continuation_execute_requested_uses_specspace_request(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)
            state_dir = root / "specspace-state"
            answer_state = state_dir / "idea_to_spec_intake_clarification_answers.json"
            answer_state.parent.mkdir(parents=True)
            answer_state.write_text(
                json.dumps(
                    {
                        "artifact_kind": "specspace_idea_intake_clarification_answer_state",
                        "answers": [
                            {
                                "workspace_id": "pantry-rotation",
                                "request_id": "clarification.intake.domain",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            initialization = root / "platform_product_workspace_initialization_execution_report.json"
            self.write_workspace_initialization_execution_report(initialization)
            self.write_real_idea_entry_intake_execution_report(
                specgraph_dir / "runs" / "platform_real_idea_entry_intake_execution_report.json"
            )
            execution_request = (
                state_dir / "real_idea_answer_continuation_execution_requests.json"
            )
            self.write_real_idea_answer_continuation_execution_request_state(
                execution_request,
                workspace_initialization_ref=str(initialization),
            )
            output = (
                specgraph_dir
                / "runs"
                / "platform_real_idea_answer_continuation_execution_report.json"
            )

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute-requested",
                "--specgraph-dir",
                str(specgraph_dir),
                "--execution-request",
                str(execution_request),
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["execution_request_ref"], str(execution_request.resolve()))
            self.assertEqual(
                payload["intake_execution_ref"],
                str(
                    (
                        specgraph_dir
                        / "runs"
                        / "platform_real_idea_entry_intake_execution_report.json"
                    ).resolve()
                ),
            )
            self.assertEqual(payload["run_dir"], "runs/pantry-rotation")
            self.assertEqual(
                payload["target_make"]["variables"]["SPECSPACE_REAL_IDEA_ANSWER_STATE"],
                "runs/pantry-rotation/idea_to_spec_intake_clarification_answers.json",
            )
            self.assertTrue(payload["answer_state_copied_to_run_dir"])
            self.assertTrue(
                (
                    specgraph_dir
                    / "runs"
                    / "pantry-rotation"
                    / "idea_to_spec_intake_clarification_answers.json"
                ).is_file()
            )
            self.assertTrue(payload["output_artifacts"]["continuation_report"]["ready"])

    def test_product_real_idea_continuation_execute_requested_rejects_authority_expansion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)
            execution_request = (
                root
                / "specspace-state"
                / "real_idea_answer_continuation_execution_requests.json"
            )
            self.write_real_idea_answer_continuation_execution_request_state(
                execution_request,
                authority_expanded=True,
            )

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute-requested",
                "--specgraph-dir",
                str(specgraph_dir),
                "--execution-request",
                str(execution_request),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_answer_continuation_execution_request_authority_expanded",
                codes,
            )
            self.assertFalse(payload["authority_boundary"]["executes_specgraph_make_target"])

    def test_product_real_idea_continuation_execute_requested_rejects_escaped_state_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)
            initialization = root / "platform_product_workspace_initialization_execution_report.json"
            self.write_workspace_initialization_execution_report(initialization)
            self.write_real_idea_entry_intake_execution_report(
                specgraph_dir / "runs" / "platform_real_idea_entry_intake_execution_report.json"
            )
            execution_request = (
                root
                / "specspace-state"
                / "real_idea_answer_continuation_execution_requests.json"
            )
            self.write_real_idea_answer_continuation_execution_request_state(
                execution_request,
                answer_state_ref="specspace-state://../outside.json",
                workspace_initialization_ref=str(initialization),
            )

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute-requested",
                "--specgraph-dir",
                str(specgraph_dir),
                "--execution-request",
                str(execution_request),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_answer_continuation_execution_request_answer_state_ref_invalid",
                codes,
            )
            self.assertFalse(payload["authority_boundary"]["executes_specgraph_make_target"])

    def test_product_real_idea_continuation_defaults_to_run_dir_answer_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)
            run_dir = specgraph_dir / "runs" / "idea-alpha"
            answer_handoff = run_dir / "idea_to_spec_intake_clarification_answers.json"
            answer_handoff.parent.mkdir(parents=True)
            answer_handoff.write_text(
                json.dumps(
                    {
                        "artifact_kind": "specspace_idea_intake_clarification_answer_state",
                        "answers": [
                            {
                                "workspace_id": "team-decision-log",
                                "request_id": "clarification.intake.question-active-frame-domain-refs",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["answer_state_explicit"])
            self.assertFalse(payload["answer_state_copied_to_run_dir"])
            self.assertEqual(
                payload["answer_state_source_ref"],
                "runs/idea-alpha/idea_to_spec_intake_clarification_answers.json",
            )
            self.assertEqual(
                payload["target_make"]["variables"]["SPECSPACE_REAL_IDEA_ANSWER_STATE"],
                "runs/idea-alpha/idea_to_spec_intake_clarification_answers.json",
            )

    def test_product_real_idea_continuation_rejects_implicit_handoff_overwrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)
            run_dir = specgraph_dir / "runs" / "idea-alpha"
            handoff = run_dir / "idea_to_spec_intake_clarification_answers.json"
            handoff.parent.mkdir(parents=True)
            handoff.write_text('{"artifact_kind":"existing"}', encoding="utf-8")
            external_answer_state = (
                Path(tmp_dir)
                / "specspace-state"
                / "idea_to_spec_intake_clarification_answers.json"
            )
            external_answer_state.parent.mkdir(parents=True)
            external_answer_state.write_text(
                '{"artifact_kind":"replacement"}',
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--answer-state",
                str(external_answer_state),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_answer_continuation_answer_state_handoff_exists",
                codes,
            )
            self.assertFalse(payload["answer_state_copied_to_run_dir"])
            self.assertEqual(
                json.loads(handoff.read_text(encoding="utf-8"))["artifact_kind"],
                "existing",
            )

    def test_product_real_idea_continuation_execute_supports_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--dry-run",
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["status"], "dry_run")
            self.assertFalse(
                payload["authority_boundary"]["executes_specgraph_make_target"]
            )

    def test_product_real_idea_continuation_rejects_run_dir_outside_specgraph(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)
            outside_dir = Path(tmp_dir) / "outside"

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                str(outside_dir),
                "--dry-run",
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_answer_continuation_run_dir_outside_specgraph",
                codes,
            )
            self.assertEqual(payload["output_artifacts"], {})

    def test_product_real_idea_continuation_rejects_missing_answer_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--answer-state",
                str(Path(tmp_dir) / "missing_answers.json"),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_answer_continuation_answer_state_missing",
                codes,
            )
            self.assertEqual(
                payload["operations"][0]["status"],
                "skipped",
            )

    def test_product_real_idea_continuation_rejects_output_authority_expansion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_answer_continuation_makefile(specgraph_dir)
            makefile = (specgraph_dir / "Makefile").read_text(encoding="utf-8")
            makefile = makefile.replace(
                '"may_create_branch_or_commit":false',
                '"may_create_branch_or_commit":true',
                1,
            )
            (specgraph_dir / "Makefile").write_text(makefile, encoding="utf-8")
            answer_state = (
                Path(tmp_dir)
                / "specspace-state"
                / "idea_to_spec_intake_clarification_answers.json"
            )
            answer_state.parent.mkdir(parents=True)
            answer_state.write_text(
                '{"artifact_kind":"specspace_idea_intake_clarification_answer_state"}',
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-real-idea-continuation",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--answer-state",
                str(answer_state),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_answer_continuation_output_authority_expanded",
                codes,
            )
            self.assertEqual(
                payload["output_artifacts"]["import_preview"]["authority_boundary"][
                    "may_create_branch_or_commit"
                ],
                True,
            )

    def test_product_real_idea_intake_execute_runs_specgraph_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            entry_requests = root / "specspace-state" / "real_idea_entry_requests.json"
            entry_requests.parent.mkdir()
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )
            output = (
                specgraph_dir
                / "runs"
                / "platform_real_idea_entry_intake_execution_report.json"
            )

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--entry-requests",
                str(entry_requests),
                "--workspace-id",
                "idea-alpha",
                "--request-id",
                "entry-001",
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_real_idea_entry_intake_execution_report",
            )
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["dry_run"])
            self.assertEqual(
                payload["target_make"]["target"],
                "real-idea-intake-from-entry-request",
            )
            self.assertEqual(
                payload["target_make"]["variables"]["REAL_IDEA_SMOKE_RUN_DIR"],
                "runs/idea-alpha",
            )
            self.assertEqual(
                payload["target_make"]["variables"]["SPECSPACE_REAL_IDEA_ENTRY_REQUESTS"],
                "runs/idea-alpha/real_idea_entry_requests.json",
            )
            self.assertEqual(payload["command_result"]["returncode"], 0)
            self.assertTrue(
                (specgraph_dir / "runs" / "idea-alpha" / "real_idea_entry_requests.json").exists()
            )
            self.assertTrue(payload["output_artifacts"]["entry_import_preview"]["ready"])
            self.assertTrue(payload["output_artifacts"]["entry_intake_report"]["ready"])
            self.assertTrue(payload["output_artifacts"]["raw_input"]["present"])
            self.assertTrue(payload["output_artifacts"]["raw_input"]["local_only"])
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])

    def test_product_real_idea_intake_binds_initialized_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            entry_requests = root / "specspace-state" / "real_idea_entry_requests.json"
            entry_requests.parent.mkdir()
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )
            initialization = root / "platform_product_workspace_initialization_execution_report.json"
            self.write_workspace_initialization_execution_report(initialization)

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-initialization",
                str(initialization),
                "--entry-requests",
                str(entry_requests),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["run_dir"], "runs/pantry-rotation")
            self.assertEqual(payload["summary"]["workspace_id"], "pantry-rotation")
            self.assertEqual(
                payload["summary"]["workspace_initialization_ref"],
                str(initialization.resolve()),
            )
            self.assertEqual(
                payload["workspace_initialization"]["workspace_id"],
                "pantry-rotation",
            )
            self.assertEqual(
                payload["target_make"]["variables"]["REAL_IDEA_SMOKE_RUN_DIR"],
                "runs/pantry-rotation",
            )
            self.assertEqual(
                payload["target_make"]["variables"]["SPECSPACE_REAL_IDEA_ENTRY_WORKSPACE_ID"],
                "pantry-rotation",
            )
            self.assertEqual(
                payload["target_make"]["variables"]["SPECSPACE_REAL_IDEA_ENTRY_REQUESTS"],
                "runs/pantry-rotation/real_idea_entry_requests.json",
            )
            self.assertTrue(payload["entry_requests_copied_to_run_dir"])
            self.assertTrue(
                (
                    specgraph_dir
                    / "runs"
                    / "pantry-rotation"
                    / "real_idea_entry_requests.json"
                ).is_file()
            )

    def test_product_real_idea_intake_execute_requested_uses_specspace_request(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            state_dir = root / "specspace-state"
            entry_requests = state_dir / "real_idea_entry_requests.json"
            entry_requests.parent.mkdir()
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )
            initialization = root / "platform_product_workspace_initialization_execution_report.json"
            self.write_workspace_initialization_execution_report(initialization)
            execution_request = state_dir / "real_idea_intake_execution_requests.json"
            self.write_real_idea_intake_execution_request_state(
                execution_request,
                workspace_initialization_ref=str(initialization),
            )
            output = (
                specgraph_dir
                / "runs"
                / "platform_real_idea_entry_intake_execution_report.json"
            )

            result = self.run_cli(
                "product-real-idea-intake",
                "execute-requested",
                "--specgraph-dir",
                str(specgraph_dir),
                "--execution-request",
                str(execution_request),
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["execution_request_ref"], str(execution_request.resolve()))
            self.assertEqual(payload["run_dir"], "runs/pantry-rotation")
            self.assertEqual(payload["summary"]["workspace_id"], "pantry-rotation")
            self.assertEqual(
                payload["target_make"]["variables"]["SPECSPACE_REAL_IDEA_ENTRY_REQUEST_ID"],
                "real-idea-entry.pantry-rotation.20260704.abcd12",
            )
            self.assertEqual(
                payload["target_make"]["variables"]["SPECSPACE_REAL_IDEA_ENTRY_REQUESTS"],
                "runs/pantry-rotation/real_idea_entry_requests.json",
            )
            self.assertTrue(payload["entry_requests_copied_to_run_dir"])
            self.assertTrue(
                (
                    specgraph_dir
                    / "runs"
                    / "pantry-rotation"
                    / "real_idea_entry_requests.json"
                ).is_file()
            )

    def test_product_real_idea_intake_execute_requested_rejects_authority_expansion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            execution_request = root / "specspace-state" / "real_idea_intake_execution_requests.json"
            self.write_real_idea_intake_execution_request_state(
                execution_request,
                authority_expanded=True,
            )

            result = self.run_cli(
                "product-real-idea-intake",
                "execute-requested",
                "--specgraph-dir",
                str(specgraph_dir),
                "--execution-request",
                str(execution_request),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_intake_execution_request_authority_expanded",
                codes,
            )
            self.assertFalse(payload["authority_boundary"]["executes_specgraph_make_target"])

    def test_product_real_idea_intake_execute_requested_rejects_truthy_authority_value(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            execution_request = root / "specspace-state" / "real_idea_intake_execution_requests.json"
            self.write_real_idea_intake_execution_request_state(
                execution_request,
                authority_value="true",
            )

            result = self.run_cli(
                "product-real-idea-intake",
                "execute-requested",
                "--specgraph-dir",
                str(specgraph_dir),
                "--execution-request",
                str(execution_request),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_intake_execution_request_authority_expanded",
                codes,
            )

    def test_product_real_idea_intake_execute_requested_rejects_request_id_mismatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            execution_request = root / "specspace-state" / "real_idea_intake_execution_requests.json"
            self.write_real_idea_intake_execution_request_state(execution_request)

            result = self.run_cli(
                "product-real-idea-intake",
                "execute-requested",
                "--specgraph-dir",
                str(specgraph_dir),
                "--execution-request",
                str(execution_request),
                "--request-id",
                "real-idea-entry.other",
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_intake_execution_request_entry_request_mismatch",
                codes,
            )
            self.assertFalse(payload["authority_boundary"]["executes_specgraph_make_target"])

    def test_product_real_idea_intake_rejects_workspace_initialization_mismatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            entry_requests = root / "real_idea_entry_requests.json"
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )
            initialization = root / "platform_product_workspace_initialization_execution_report.json"
            self.write_workspace_initialization_execution_report(initialization)

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-initialization",
                str(initialization),
                "--workspace-id",
                "different-workspace",
                "--entry-requests",
                str(entry_requests),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_entry_intake_workspace_initialization_workspace_mismatch",
                codes,
            )

    def test_product_real_idea_intake_reports_bad_workspace_initialization_json(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            entry_requests = root / "real_idea_entry_requests.json"
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )
            initialization = root / "platform_product_workspace_initialization_execution_report.json"
            initialization.write_text("{not-json", encoding="utf-8")

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-initialization",
                str(initialization),
                "--entry-requests",
                str(entry_requests),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "real_idea_entry_intake_workspace_initialization_unreadable",
                codes,
            )

    def test_product_real_idea_intake_uses_inside_specgraph_entry_source_without_copy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            entry_requests = specgraph_dir / "specspace-state" / "real_idea_entry_requests.json"
            entry_requests.parent.mkdir()
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--entry-requests",
                str(entry_requests),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["target_make"]["variables"]["SPECSPACE_REAL_IDEA_ENTRY_REQUESTS"],
                "specspace-state/real_idea_entry_requests.json",
            )
            self.assertEqual(
                payload["entry_requests_handoff_ref"],
                "specspace-state/real_idea_entry_requests.json",
            )
            self.assertFalse(payload["entry_requests_copied_to_run_dir"])
            self.assertFalse(
                (specgraph_dir / "runs" / "idea-alpha" / "real_idea_entry_requests.json").exists()
            )

    def test_product_real_idea_intake_execute_supports_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            entry_requests = root / "real_idea_entry_requests.json"
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--entry-requests",
                str(entry_requests),
                "--dry-run",
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["status"], "dry_run")
            self.assertFalse(
                (specgraph_dir / "runs" / "idea-alpha" / "real_idea_entry_requests.json").exists()
            )
            self.assertFalse(
                payload["authority_boundary"]["executes_specgraph_make_target"]
            )

    def test_product_real_idea_intake_rejects_missing_entry_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--entry-requests",
                str(Path(tmp_dir) / "missing.json"),
                "--dry-run",
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("real_idea_entry_intake_entry_requests_missing", codes)

    def test_product_real_idea_intake_rejects_output_authority_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            makefile = (specgraph_dir / "Makefile").read_text(encoding="utf-8")
            makefile = makefile.replace(
                '"may_create_branch_or_commit":false',
                '"may_create_branch_or_commit":true',
                1,
            )
            (specgraph_dir / "Makefile").write_text(makefile, encoding="utf-8")
            entry_requests = root / "real_idea_entry_requests.json"
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--entry-requests",
                str(entry_requests),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("real_idea_entry_intake_output_authority_expanded", codes)
            self.assertEqual(
                payload["output_artifacts"]["entry_import_preview"]["authority_boundary"][
                    "may_create_branch_or_commit"
                ],
                True,
            )

    def test_product_real_idea_intake_requires_source_for_ready_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            makefile = (specgraph_dir / "Makefile").read_text(encoding="utf-8")
            makefile = makefile.replace(
                '"readiness":{"ready":false,"review_state":"needs_clarification"}',
                '"readiness":{"ready":true,"review_state":"ready"}',
            )
            (specgraph_dir / "Makefile").write_text(makefile, encoding="utf-8")
            entry_requests = root / "real_idea_entry_requests.json"
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--entry-requests",
                str(entry_requests),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("real_idea_entry_intake_output_missing", codes)

    def test_product_real_idea_intake_validates_present_source_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            specgraph_dir = root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_real_idea_entry_intake_makefile(specgraph_dir)
            makefile = (specgraph_dir / "Makefile").read_text(encoding="utf-8")
            makefile += (
                '\n\t@printf \'%s\\n\' \'{"artifact_kind":"user_idea_intake_source",'
                '"canonical_mutations_allowed":false,"tracked_artifacts_written":false,'
                '"readiness":{"ready":true},'
                '"authority_boundary":{"may_create_branch_or_commit":true}}\' '
                '> $(REAL_IDEA_SMOKE_RUN_DIR)/user_idea_intake_source.json\n'
            )
            (specgraph_dir / "Makefile").write_text(makefile, encoding="utf-8")
            entry_requests = root / "real_idea_entry_requests.json"
            entry_requests.write_text(
                '{"artifact_kind":"specspace_real_idea_entry_request_state","requests":[]}',
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-real-idea-intake",
                "execute",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--entry-requests",
                str(entry_requests),
                "--no-write-report",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("real_idea_entry_intake_output_authority_expanded", codes)
            self.assertEqual(
                payload["output_artifacts"]["intake_source"]["authority_boundary"][
                    "may_create_branch_or_commit"
                ],
                True,
            )

    def test_product_repair_rerun_plan_rejects_authority_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(
                specgraph_dir,
                request_authority_expanded=True,
            )

            result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_repair_rerun_request_authority_expanded", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_to_execute"])

    def test_product_repair_rerun_plan_accepts_selected_run_dir_repair_session_refs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            runs_dir = specgraph_dir / "runs"
            selected_run_dir = runs_dir / "idea-alpha"
            selected_run_dir.mkdir()
            for filename in (
                "idea_to_spec_repair_rerun_requests.json",
                "specspace_repair_draft_import_preview.json",
                "specspace_repair_rerun_request_gate.json",
                "idea_to_spec_repair_session.json",
            ):
                shutil.copyfile(runs_dir / filename, selected_run_dir / filename)
            repair_session_path = selected_run_dir / "idea_to_spec_repair_session.json"
            repair_session = json.loads(repair_session_path.read_text(encoding="utf-8"))
            for entry in repair_session["source_artifacts"].values():
                if isinstance(entry, dict) and isinstance(entry.get("source_ref"), str):
                    entry["source_ref"] = f"runs/idea-alpha/{Path(entry['source_ref']).name}"
            repair_session_path.write_text(
                json.dumps(repair_session),
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--rerun-request",
                str(selected_run_dir / "idea_to_spec_repair_rerun_requests.json"),
                "--import-preview",
                str(selected_run_dir / "specspace_repair_draft_import_preview.json"),
                "--repair-session",
                str(repair_session_path),
                "--request-gate",
                str(selected_run_dir / "specspace_repair_rerun_request_gate.json"),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["ready_to_execute"])
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertNotIn("graph_repository_repair_session_source_ref_stale", codes)
        self.assertEqual(
            Path(payload["expected_outputs"]["repair_session"]).resolve(),
            (selected_run_dir / "idea_to_spec_repair_session.json").resolve(),
        )
        self.assertEqual(
            Path(payload["repaired_expected_outputs"]["repaired_handoff"]).resolve(),
            (
                selected_run_dir / "repaired_candidate_promotion_handoff_report.json"
            ).resolve(),
        )
        self.assertEqual(
            payload["target_make"]["variables"]["IDEA_TO_SPEC_REPAIR_SESSION_OUTPUT"],
            "runs/idea-alpha/idea_to_spec_repair_session.json",
        )
        self.assertEqual(
            payload["target_make"]["variables"]["SPECSPACE_REPAIR_DRAFT_IMPORT_DRAFTS"],
            "runs/idea-alpha/idea_to_spec_repair_drafts.json",
        )
        self.assertEqual(
            payload["target_make"]["variables"][
                "SPECSPACE_REPAIR_DRAFT_IMPORT_CLARIFICATION_REQUESTS"
            ],
            "runs/idea-alpha/idea_to_spec_clarification_requests.json",
        )

    def test_product_repair_rerun_plan_rejects_stale_selected_run_dir_repair_session_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            runs_dir = specgraph_dir / "runs"
            selected_run_dir = runs_dir / "idea-alpha"
            selected_run_dir.mkdir()
            for filename in (
                "idea_to_spec_repair_rerun_requests.json",
                "specspace_repair_draft_import_preview.json",
                "specspace_repair_rerun_request_gate.json",
                "idea_to_spec_repair_session.json",
            ):
                shutil.copyfile(runs_dir / filename, selected_run_dir / filename)
            repair_session_path = selected_run_dir / "idea_to_spec_repair_session.json"
            repair_session = json.loads(repair_session_path.read_text(encoding="utf-8"))
            for entry in repair_session["source_artifacts"].values():
                if isinstance(entry, dict) and isinstance(entry.get("source_ref"), str):
                    entry["source_ref"] = f"runs/idea-alpha/{Path(entry['source_ref']).name}"
            repair_session["source_artifacts"]["rerun_preview"][
                "source_ref"
            ] = "runs/idea-alpha/stale_rerun_preview.json"
            repair_session_path.write_text(
                json.dumps(repair_session),
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--rerun-request",
                str(selected_run_dir / "idea_to_spec_repair_rerun_requests.json"),
                "--import-preview",
                str(selected_run_dir / "specspace_repair_draft_import_preview.json"),
                "--repair-session",
                str(repair_session_path),
                "--request-gate",
                str(selected_run_dir / "specspace_repair_rerun_request_gate.json"),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_repair_session_source_ref_stale", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_to_execute"])

    def test_product_repair_rerun_execute_runs_specgraph_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(execution_report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_repair_rerun_execution_report",
            )
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["dry_run"])
            self.assertEqual(payload["command_result"]["returncode"], 0)
            self.assertTrue(payload["output_artifacts"]["rerun_report"]["ready"])
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])

    def test_product_repair_rerun_execute_builds_repaired_handoff(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--build-repaired-handoff",
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(
                payload["repaired_handoff_command_result"]["returncode"],
                0,
            )
            self.assertTrue(payload["summary"]["repaired_handoff_requested"])
            self.assertTrue(payload["summary"]["repaired_handoff_built"])
            self.assertTrue(payload["summary"]["rerun_report_ready"])
            self.assertFalse(
                payload["summary"]["rerun_report_accepted_as_intermediate_evidence"]
            )
            self.assertIsInstance(
                payload["summary"]["repaired_handoff_digest"],
                str,
            )
            self.assertIsInstance(
                payload["summary"]["repaired_repair_session_digest"],
                str,
            )
            self.assertTrue(
                payload["output_artifacts"]["repaired_handoff"]["ready"]
            )
            self.assertTrue(
                payload["output_artifacts"]["repaired_repair_session"]["ready"]
            )
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(
                statuses["execute_specgraph_requested_rerun"],
                "succeeded",
            )
            self.assertEqual(
                statuses["execute_specgraph_repaired_promotion_handoff"],
                "succeeded",
            )
            self.assertTrue(
                (
                    specgraph_dir
                    / "runs"
                    / "repaired_candidate_promotion_handoff_report.json"
                ).is_file()
            )

    def test_product_repair_rerun_execute_surfaces_intermediate_rerun_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            makefile = (specgraph_dir / "Makefile").read_text(encoding="utf-8")
            makefile = makefile.replace(
                '"readiness":{"ready":true,"review_state":"repair_draft_rerun_ready"}',
                '"readiness":{"ready":false,"review_state":"repair_draft_rerun_review_required"}',
            )
            makefile = makefile.replace(
                '"summary":{"status":"ready"}}',
                '"summary":{"status":"repair_draft_rerun_review_required"}}',
            )
            (specgraph_dir / "Makefile").write_text(makefile, encoding="utf-8")
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--build-repaired-handoff",
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["summary"]["rerun_report_ready"])
        self.assertTrue(
            payload["summary"]["rerun_report_accepted_as_intermediate_evidence"]
        )
        self.assertEqual(
            payload["output_artifacts"]["rerun_report"]["status"],
            "repair_draft_rerun_review_required",
        )

    def test_product_repair_rerun_execute_builds_repaired_handoff_in_run_dir(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            selected_run_dir = specgraph_dir / "runs" / "idea-alpha"
            selected_run_dir.mkdir()
            for filename in (
                "idea_to_spec_repair_rerun_requests.json",
                "specspace_repair_draft_import_preview.json",
                "specspace_repair_rerun_request_gate.json",
                "idea_to_spec_repair_session.json",
            ):
                shutil.copyfile(
                    specgraph_dir / "runs" / filename,
                    selected_run_dir / filename,
                )
            repair_session_path = selected_run_dir / "idea_to_spec_repair_session.json"
            repair_session = json.loads(repair_session_path.read_text(encoding="utf-8"))
            for entry in repair_session["source_artifacts"].values():
                if isinstance(entry, dict) and isinstance(entry.get("source_ref"), str):
                    entry["source_ref"] = f"runs/idea-alpha/{Path(entry['source_ref']).name}"
            repair_session_path.write_text(
                json.dumps(repair_session),
                encoding="utf-8",
            )
            plan_path = selected_run_dir / "product_repair_rerun_plan.json"
            execution_report_path = selected_run_dir / "product_repair_rerun_execution.json"
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--run-dir",
                "runs/idea-alpha",
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stdout)

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--build-repaired-handoff",
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(
                (
                    selected_run_dir
                    / "repaired_candidate_promotion_handoff_report.json"
                ).is_file()
            )
            self.assertFalse(
                (
                    specgraph_dir
                    / "runs"
                    / "repaired_candidate_promotion_handoff_report.json"
                ).is_file()
            )
            self.assertEqual(
                Path(payload["output_artifacts"]["repaired_handoff"]["path"]).resolve(),
                (
                    selected_run_dir / "repaired_candidate_promotion_handoff_report.json"
                ).resolve(),
            )

    def test_product_repair_rerun_execute_rejects_tampered_plan_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            with (specgraph_dir / "Makefile").open("a", encoding="utf-8") as makefile:
                makefile.write(
                    "\nunapproved-target:\n"
                    "\t@printf 'ran' > runs/unapproved-target-ran\n"
                )
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["target_make"]["target"] = "unapproved-target"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_plan_make_target_unsupported", codes)
            self.assertFalse((specgraph_dir / "runs" / "unapproved-target-ran").exists())

    def test_product_repair_rerun_execute_rejects_tampered_plan_cwd(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            other_dir = Path(tmp_dir) / "OtherSpecGraph"
            specgraph_dir.mkdir()
            other_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_makefile(other_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["target_make"]["cwd"] = str(other_dir)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_plan_cwd_mismatch", codes)

    def test_product_repair_rerun_execute_requires_specgraph_makefile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            (specgraph_dir / "Makefile").unlink()

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_plan_specgraph_makefile_missing", codes)

    def test_product_repair_rerun_publish_verifies_public_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            publication_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_publication.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            execute_result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )
            self.assertEqual(execute_result.returncode, 0, execute_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(execution_report_path),
                "--output",
                str(publication_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(publication_report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_repair_rerun_publication_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["published_artifact_count"], 4)
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])

    def test_product_repair_rerun_publish_surfaces_idea_maturity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            publication_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_publication.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            execute_result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )
            self.assertEqual(execute_result.returncode, 0, execute_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(execution_report_path),
                "--output",
                str(publication_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["idea_maturity"]["status"], "available")
            self.assertTrue(payload["idea_maturity"]["trusted"])
            self.assertEqual(payload["idea_maturity"]["validation_status"], "ok")
            self.assertEqual(payload["idea_maturity"]["lifecycle_state"], "promotion_requested")
            self.assertEqual(payload["idea_maturity"]["failed_gate_count"], 1)
            self.assertTrue(payload["idea_maturity"]["contract"]["available"])
            self.assertEqual(
                payload["idea_maturity"]["contract"]["report"]["schema_ref"],
                "schemas/idea_maturity_metrics_report.schema.json",
            )
            self.assertEqual(
                payload["idea_maturity"]["contract"]["report"][
                    "validation_report_schema_ref"
                ],
                "schemas/idea_maturity_metrics_validation_report.schema.json",
            )
            self.assertEqual(
                payload["idea_maturity"]["contract"]["report"]["compatibility_policy"],
                "additive_v1",
            )
            self.assertEqual(
                payload["idea_maturity"]["contract"]["validator"]["id"],
                "metrics.idea_maturity_metrics.validator.v0.1",
            )
            self.assertEqual(
                payload["idea_maturity"]["contract"]["validator"]["version"],
                "0.1.0",
            )
            self.assertEqual(
                payload["idea_maturity"]["readiness_explainer_count"],
                1,
            )
            self.assertEqual(
                payload["idea_maturity"]["readiness_explainers"][0]["kind"],
                "pre_sib_finding",
            )
            self.assertEqual(
                payload["idea_maturity"]["readiness_explainers"][0]["blocks"],
                ["pre_sib_review", "candidate_approval"],
            )
            self.assertEqual(
                payload["idea_maturity"]["answer_materialization"],
                {
                    "accepted_answer_count": 3,
                    "per_gap_materialized_answer_count": 2,
                    "aggregate_answer_count": 1,
                    "dismissed_answer_count": 0,
                    "closure_evidence_answer_count": 3,
                    "ordinary_unmaterialized_answer_count": 0,
                },
            )
            self.assertEqual(
                payload["idea_maturity"]["project_local_ontology_review"],
                {
                    "status": "project_local_ontology_decision_effect_ready",
                    "accepted_decision_count": 2,
                    "maturity_evidence_decision_count": 2,
                    "keep_project_local_count": 1,
                    "bind_existing_count": 1,
                    "alias_count": 0,
                    "request_promotion_count": 0,
                    "reject_count": 0,
                    "deferred_count": 0,
                    "invalid_decision_count": 0,
                    "missing_decision_count": 0,
                    "blocking_decision_count": 0,
                    "follow_up_decision_count": 0,
                    "effect_count": 2,
                    "ready_for_maturity": True,
                    "evidence_refs": [
                        "runs/project_local_ontology_review_decisions.json"
                    ],
                },
            )
            self.assertIn(
                "Inspect Pre-SIB coherence findings",
                payload["idea_maturity"]["readiness_explainers"][0]["next_action"],
            )
            self.assertEqual(
                payload["idea_maturity"]["public_artifacts"]["published_count"],
                2,
            )
            self.assertEqual(
                payload["summary"]["idea_maturity_status"],
                "available",
            )

    def test_product_repair_rerun_publish_uses_legacy_answer_accounting_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(specgraph_dir)
            metrics_path = specgraph_dir / "runs" / "idea_maturity_metrics_report.json"
            metrics_report = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics_report["groups"].pop("answer_materialization")
            metrics_report["groups"].pop("ontology_grounding")
            metrics_report["metrics"] = {
                "accepted_answer_count": 4,
                "materialized_answer_count": 2,
                "unmaterialized_answer_count": 2,
                "project_local_ontology_review_status": (
                    "project_local_ontology_decision_effect_ready"
                ),
                "project_local_ontology_accepted_decision_count": 3,
                "project_local_ontology_keep_local_count": 2,
                "project_local_ontology_bind_existing_count": 1,
                "project_local_ontology_alias_count": 0,
                "project_local_ontology_request_promotion_count": 0,
                "project_local_ontology_reject_count": 0,
                "project_local_ontology_deferred_decision_count": 0,
                "project_local_ontology_invalid_decision_count": 0,
                "project_local_ontology_missing_decision_count": 0,
                "project_local_ontology_blocking_decision_count": 0,
            }
            metrics_path.write_text(
                json.dumps(metrics_report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            publication_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_publication.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            execute_result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )
            self.assertEqual(execute_result.returncode, 0, execute_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(execution_report_path),
                "--output",
                str(publication_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["idea_maturity"]["answer_materialization"],
                {
                    "accepted_answer_count": 4,
                    "per_gap_materialized_answer_count": 2,
                    "aggregate_answer_count": 0,
                    "dismissed_answer_count": 0,
                    "closure_evidence_answer_count": 2,
                    "ordinary_unmaterialized_answer_count": 2,
                },
            )
            self.assertEqual(
                payload["idea_maturity"]["project_local_ontology_review"][
                    "accepted_decision_count"
                ],
                3,
            )
            self.assertEqual(
                payload["idea_maturity"]["project_local_ontology_review"][
                    "keep_project_local_count"
                ],
                2,
            )

    def test_product_repair_rerun_publish_verifies_repaired_bundle(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            publication_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_publication.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            execute_result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--build-repaired-handoff",
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )
            self.assertEqual(execute_result.returncode, 0, execute_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(execution_report_path),
                "--output",
                str(publication_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["published_artifact_count"], 12)
            self.assertTrue(
                (
                    specgraph_dir
                    / "dist"
                    / "specgraph-public"
                    / "runs"
                    / "repaired_candidate_promotion_handoff_report.json"
                ).is_file()
            )
            self.assertTrue(
                (
                    specgraph_dir
                    / "dist"
                    / "specgraph-public"
                    / "runs"
                    / "repaired_idea_to_spec_repair_session.json"
                ).is_file()
            )
            self.assertTrue(
                (
                    specgraph_dir
                    / "dist"
                    / "specgraph-public"
                    / "runs"
                    / "repaired_candidate_spec_graph.json"
                ).is_file()
            )

    def test_product_repair_rerun_publish_rejects_dry_run_execution_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            execute_result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--dry-run",
                "--format",
                "json",
            )
            self.assertEqual(execute_result.returncode, 0, execute_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(execution_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_execution_report_dry_run", codes)

    def test_product_repair_rerun_publish_requires_specgraph_makefile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            other_dir = Path(tmp_dir) / "OtherSpecGraph"
            specgraph_dir.mkdir()
            other_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            execute_result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )
            self.assertEqual(execute_result.returncode, 0, execute_result.stderr)
            execution_report = json.loads(
                execution_report_path.read_text(encoding="utf-8")
            )
            execution_report["specgraph_dir"] = str(other_dir)
            execution_report_path.write_text(
                json.dumps(execution_report),
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(execution_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_publish_specgraph_makefile_missing", codes)

    def test_product_repair_rerun_smoke_runs_full_demo_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            smoke_report_path = (
                specgraph_dir / "runs" / "platform_product_repair_rerun_smoke.json"
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(smoke_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(smoke_report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_repair_rerun_smoke_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["status"], "passed")
            self.assertEqual(payload["summary"]["profile"], "strict")
            self.assertEqual(payload["summary"]["profile_status"], "passed")
            self.assertEqual(payload["summary"]["strict_status"], "passed")
            self.assertTrue(payload["summary"]["plan_ok"])
            self.assertTrue(payload["summary"]["execution_ok"])
            self.assertTrue(payload["summary"]["publication_ok"])
            self.assertIsInstance(payload["summary"]["rerun_report_digest"], str)
            self.assertIsInstance(payload["summary"]["repair_session_digest"], str)
            self.assertIsInstance(payload["summary"]["manifest_digest"], str)
            self.assertEqual(payload["summary"]["published_artifact_count"], 4)
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])
            self.assertFalse(payload["authority_boundary"]["writes_ontology_packages"])
            self.assertFalse(payload["authority_boundary"]["mutates_canonical_specs"])
            self.assertFalse(
                payload["authority_boundary"]["candidate_approval_performed"]
            )
            self.assertFalse(
                payload["authority_boundary"]["git_service_promotion_started"]
            )
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["plan_product_repair_rerun"], "succeeded")
            self.assertEqual(statuses["execute_specgraph_requested_rerun"], "succeeded")
            self.assertEqual(statuses["publish_public_safe_bundle"], "succeeded")
            self.assertTrue(payload["phase_reports"]["plan"]["present"])
            self.assertTrue(payload["phase_reports"]["execution"]["present"])
            self.assertTrue(payload["phase_reports"]["publication"]["present"])
            self.assertTrue(
                (
                    specgraph_dir
                    / "dist"
                    / "specgraph-public"
                    / "runs"
                    / "idea_to_spec_repair_session.json"
                ).is_file()
            )

    def test_product_repair_rerun_smoke_builds_repaired_handoff_and_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            self.write_product_candidate_approval_intent_state(specgraph_dir)
            smoke_report_path = (
                specgraph_dir / "runs" / "platform_product_repair_rerun_smoke.json"
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--build-repaired-handoff",
                "--output",
                str(smoke_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["status"], "passed")
            self.assertEqual(payload["summary"]["profile"], "strict")
            self.assertEqual(payload["summary"]["profile_status"], "passed")
            self.assertEqual(payload["summary"]["strict_status"], "passed")
            self.assertTrue(payload["summary"]["candidate_approval_gate_ok"])
            self.assertTrue(payload["summary"]["ready_to_materialize"])
            self.assertIsInstance(
                payload["summary"]["repaired_handoff_digest"],
                str,
            )
            self.assertIsInstance(
                payload["summary"]["repaired_repair_session_digest"],
                str,
            )
            self.assertEqual(payload["summary"]["published_artifact_count"], 12)
            self.assertEqual(
                payload["summary"]["candidate_approval_approved_path_count"],
                1,
            )
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["plan_product_repair_rerun"], "succeeded")
            self.assertEqual(statuses["execute_specgraph_requested_rerun"], "succeeded")
            self.assertEqual(statuses["publish_public_safe_bundle"], "succeeded")
            self.assertEqual(statuses["validate_candidate_approval_gate"], "succeeded")
            execution_report = json.loads(
                Path(payload["phase_reports"]["execution"]["path"]).read_text(
                    encoding="utf-8"
                )
            )
            execution_statuses = {
                operation["name"]: operation["status"]
                for operation in execution_report["operations"]
            }
            self.assertEqual(
                execution_statuses["execute_specgraph_repaired_promotion_handoff"],
                "succeeded",
            )
            self.assertTrue(payload["phase_reports"]["candidate_approval_gate"]["present"])
            self.assertFalse(
                payload["authority_boundary"]["candidate_approval_performed"]
            )
            self.assertFalse(
                payload["authority_boundary"]["git_service_promotion_started"]
            )
            self.assertTrue(
                (
                    specgraph_dir
                    / "dist"
                    / "specgraph-public"
                    / "runs"
                    / "repaired_candidate_promotion_handoff_report.json"
                ).is_file()
            )

    def test_product_repair_rerun_smoke_happy_profile_requires_approval_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            self.write_product_candidate_approval_intent_state(specgraph_dir)

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--build-repaired-handoff",
                "--profile",
                "happy-path-promotion-dry-run",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(
                payload["summary"]["profile"],
                "happy-path-promotion-dry-run",
            )
            self.assertEqual(payload["summary"]["profile_status"], "passed")
            self.assertEqual(payload["summary"]["profile_observed"], "happy_path_ready")
            self.assertEqual(payload["summary"]["strict_status"], "passed")
            self.assertTrue(payload["summary"]["candidate_approval_gate_ok"])
            self.assertTrue(payload["summary"]["ready_to_materialize"])
            self.assertTrue(payload["profile"]["candidate_approval_gate_ready"])

    def test_product_repair_rerun_smoke_happy_profile_requires_repaired_handoff(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--profile",
                "happy-path-promotion-dry-run",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(
                payload["summary"]["profile"],
                "happy-path-promotion-dry-run",
            )
            self.assertEqual(payload["summary"]["profile_status"], "failed")
            self.assertEqual(
                payload["summary"]["profile_observed"],
                "missing_repaired_handoff",
            )
            self.assertEqual(payload["summary"]["strict_status"], "passed")
            self.assertIsNone(payload["summary"]["candidate_approval_gate_ok"])

    def test_product_repair_rerun_smoke_surfaces_idea_maturity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(specgraph_dir)
            smoke_report_path = (
                specgraph_dir / "runs" / "platform_product_repair_rerun_smoke.json"
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(smoke_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["idea_maturity"]["status"], "available")
            self.assertTrue(payload["idea_maturity"]["trusted"])
            self.assertEqual(payload["summary"]["idea_maturity_status"], "available")
            self.assertTrue(payload["summary"]["idea_maturity_trusted"])

    def test_product_repair_rerun_smoke_surfaces_workspace_state_hygiene(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            hygiene_path = self.write_workspace_state_hygiene_artifact(specgraph_dir)
            smoke_report_path = (
                specgraph_dir / "runs" / "platform_product_repair_rerun_smoke.json"
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-state-hygiene",
                str(hygiene_path),
                "--output",
                str(smoke_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["workspace_state_hygiene"]["status"], "blocked")
            self.assertTrue(payload["workspace_state_hygiene"]["trusted"])
            self.assertEqual(
                payload["workspace_state_hygiene"]["stale_state_count"],
                1,
            )
            self.assertEqual(
                payload["summary"]["workspace_state_hygiene_status"],
                "blocked",
            )
            self.assertEqual(
                payload["summary"]["workspace_state_hygiene_stale_state_count"],
                1,
            )
            self.assertEqual(
                payload["summary"][
                    "workspace_state_hygiene_recommended_action_count"
                ],
                1,
            )
            self.assertEqual(
                payload["workspace_state_hygiene"]["recommended_actions"][0][
                    "id"
                ],
                "workspace_state.recreate_repair_rerun_request",
            )
            self.assertFalse(
                payload["workspace_state_hygiene"]["recommended_actions"][0][
                    "enabled"
                ]
            )
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("workspace_state_hygiene_stale_state", codes)

    def test_product_repair_rerun_smoke_rejects_hygiene_action_authority_expansion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            hygiene_path = self.write_workspace_state_hygiene_artifact(specgraph_dir)
            hygiene = json.loads(hygiene_path.read_text(encoding="utf-8"))
            hygiene["recommended_actions"][0]["authority_boundary"][
                "may_execute_platform"
            ] = True
            hygiene_path.write_text(json.dumps(hygiene), encoding="utf-8")

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-state-hygiene",
                str(hygiene_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["workspace_state_hygiene"]["trusted"])
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "workspace_state_hygiene_recommended_action_boundary_expanded",
                codes,
            )

    def test_product_repair_rerun_smoke_rejects_hygiene_action_apply_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            hygiene_path = self.write_workspace_state_hygiene_artifact(specgraph_dir)
            hygiene = json.loads(hygiene_path.read_text(encoding="utf-8"))
            hygiene["recommended_actions"][0]["authority_boundary"][
                "may_apply_state"
            ] = True
            hygiene_path.write_text(json.dumps(hygiene), encoding="utf-8")

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-state-hygiene",
                str(hygiene_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["workspace_state_hygiene"]["trusted"])
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "workspace_state_hygiene_recommended_action_boundary_expanded",
                codes,
            )

    def test_product_repair_rerun_smoke_allows_missing_optional_hygiene_action_apply_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            hygiene_path = self.write_workspace_state_hygiene_artifact(specgraph_dir)
            hygiene = json.loads(hygiene_path.read_text(encoding="utf-8"))
            hygiene["recommended_actions"][0]["authority_boundary"].pop(
                "may_apply_state",
                None,
            )
            hygiene_path.write_text(json.dumps(hygiene), encoding="utf-8")

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-state-hygiene",
                str(hygiene_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["workspace_state_hygiene"]["trusted"])
            subjects = {
                diagnostic["subject"] for diagnostic in payload["diagnostics"]
            }
            self.assertNotIn(
                "workspace_state_hygiene.recommended_actions[0].authority_boundary.may_apply_state",
                subjects,
            )

    def test_product_repair_rerun_smoke_preserves_zero_hygiene_action_counts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            hygiene_path = self.write_workspace_state_hygiene_artifact(
                specgraph_dir,
                stale_state_count=0,
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-state-hygiene",
                str(hygiene_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["workspace_state_hygiene"]["recommended_action_count"],
                0,
            )
            self.assertEqual(
                payload["workspace_state_hygiene"][
                    "enabled_recommended_action_count"
                ],
                0,
            )

    def test_product_repair_rerun_smoke_warns_on_missing_workspace_state_hygiene(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            missing_hygiene_path = (
                specgraph_dir / "runs" / "missing_workspace_state_hygiene.json"
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-state-hygiene",
                str(missing_hygiene_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["workspace_state_hygiene"]["status"], "missing")
            self.assertFalse(payload["workspace_state_hygiene"]["trusted"])
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("workspace_state_hygiene_missing", codes)

    def test_product_repair_rerun_smoke_resolves_caller_relative_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            caller_dir = tmp_root / "caller"
            caller_dir.mkdir()
            specgraph_dir = tmp_root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            profile_path = caller_dir / "profile.json"
            profile_path.write_text(
                (
                    REPO_ROOT / "deployment-profile.product-idea-to-spec.example.json"
                ).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            inputs_dir = caller_dir / "inputs"
            inputs_dir.mkdir()
            for filename in (
                "idea_to_spec_repair_rerun_requests.json",
                "specspace_repair_draft_import_preview.json",
                "idea_to_spec_repair_session.json",
                "specspace_repair_rerun_request_gate.json",
            ):
                (inputs_dir / filename).write_text(
                    (specgraph_dir / "runs" / filename).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--deployment-profile",
                "profile.json",
                "--specgraph-dir",
                os.path.relpath(specgraph_dir, caller_dir),
                "--rerun-request",
                "inputs/idea_to_spec_repair_rerun_requests.json",
                "--import-preview",
                "inputs/specspace_repair_draft_import_preview.json",
                "--repair-session",
                "inputs/idea_to_spec_repair_session.json",
                "--request-gate",
                "inputs/specspace_repair_rerun_request_gate.json",
                "--format",
                "json",
                cwd=caller_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            plan_ref = Path(payload["phase_reports"]["plan"]["path"])
            plan = json.loads(plan_ref.read_text(encoding="utf-8"))
            source_paths = {
                Path(source["path"])
                for source in plan["source_artifacts"]
                if source.get("key")
            }
            self.assertTrue(
                all(
                    path.resolve().is_relative_to(inputs_dir.resolve())
                    for path in source_paths
                )
            )

    def test_product_repair_rerun_smoke_keeps_execute_authority_after_publish_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            makefile_path = specgraph_dir / "Makefile"
            makefile = makefile_path.read_text(encoding="utf-8")
            makefile_path.write_text(
                makefile.split("\npublish-bundle:\n", 1)[0],
                encoding="utf-8",
            )
            self.write_product_repair_rerun_artifacts(specgraph_dir)

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(payload["summary"]["execution_ok"])
            self.assertFalse(payload["summary"]["publication_ok"])
            self.assertTrue(
                payload["authority_boundary"]["executes_specgraph_make_target"]
            )

    def test_product_repair_rerun_smoke_stops_when_plan_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(
                specgraph_dir,
                request_authority_expanded=True,
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["plan_product_repair_rerun"], "failed")
            self.assertEqual(statuses["execute_specgraph_requested_rerun"], "skipped")
            self.assertEqual(statuses["publish_public_safe_bundle"], "skipped")
            self.assertFalse(
                (
                    specgraph_dir
                    / "runs"
                    / "platform_product_repair_rerun_execution_report.json"
                ).exists()
            )
            self.assertFalse(
                (
                    specgraph_dir
                    / "runs"
                    / "platform_product_repair_rerun_publication_report.json"
                ).exists()
            )

    def test_product_repair_rerun_smoke_diagnostic_profile_accepts_expected_block(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(
                specgraph_dir,
                request_gate_ready=False,
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--profile",
                "diagnostic-blocked",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["status"], "passed")
            self.assertEqual(payload["summary"]["profile"], "diagnostic-blocked")
            self.assertEqual(payload["summary"]["profile_status"], "passed")
            self.assertEqual(
                payload["summary"]["profile_observed"],
                "expected_diagnostic_block",
            )
            self.assertEqual(payload["summary"]["strict_status"], "failed")
            self.assertFalse(payload["summary"]["plan_ok"])
            self.assertTrue(payload["profile"]["diagnostic_block_observed"])
            self.assertFalse(payload["profile"]["authority_or_infra_error"])
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["plan_product_repair_rerun"], "failed")
            self.assertEqual(statuses["execute_specgraph_requested_rerun"], "skipped")
            self.assertEqual(statuses["publish_public_safe_bundle"], "skipped")

    def test_product_repair_rerun_smoke_diagnostic_profile_rejects_authority_expansion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(
                specgraph_dir,
                request_authority_expanded=True,
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--profile",
                "diagnostic-blocked",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["summary"]["profile"], "diagnostic-blocked")
            self.assertEqual(payload["summary"]["profile_status"], "failed")
            self.assertEqual(payload["summary"]["strict_status"], "failed")
            self.assertTrue(payload["profile"]["diagnostic_block_observed"])
            self.assertTrue(payload["profile"]["authority_or_infra_error"])
            plan_ref = Path(payload["phase_reports"]["plan"]["path"])
            plan = json.loads(plan_ref.read_text(encoding="utf-8"))
            codes = {diagnostic["code"] for diagnostic in plan["diagnostics"]}
            self.assertIn("product_repair_rerun_request_authority_expanded", codes)

    def test_product_candidate_approval_gate_builds_ready_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            output = specgraph_dir / "runs" / "candidate_approval_gate.json"

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_candidate_approval_intent_gate_report",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["ready_to_materialize"])
            self.assertEqual(payload["summary"]["candidate_id"], "idea-alpha")
            self.assertEqual(payload["summary"]["workspace_id"], "idea-alpha")
            self.assertEqual(payload["summary"]["approved_path_count"], 1)
            self.assertEqual(
                payload["approved_paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])
            self.assertFalse(payload["authority_boundary"]["writes_ontology_packages"])
            self.assertFalse(payload["authority_boundary"]["mutates_canonical_specs"])

    def test_product_candidate_approval_gate_surfaces_idea_maturity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(specgraph_dir)

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["ready_to_materialize"])
            self.assertEqual(payload["idea_maturity"]["status"], "available")
            self.assertTrue(payload["idea_maturity"]["trusted"])
            self.assertEqual(
                payload["idea_maturity"]["readiness_explainer_count"],
                1,
            )
            self.assertEqual(
                payload["idea_maturity"]["readiness_explainers"][0]["source"],
                "repaired_pre_sib",
            )
            self.assertEqual(
                payload["summary"]["idea_maturity_validation_status"],
                "ok",
            )
            self.assertEqual(
                payload["idea_maturity"]["contract"]["validator"][
                    "compatibility_policy_ref"
                ],
                "VALIDATOR_CONTRACT.md#compatibility-policy",
            )

    def test_product_candidate_approval_gate_accepts_legacy_maturity_without_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(
                specgraph_dir,
                include_contract_metadata=False,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["idea_maturity"]["status"], "available")
            self.assertTrue(payload["idea_maturity"]["trusted"])
            self.assertFalse(payload["idea_maturity"]["contract"]["available"])

    def test_product_candidate_approval_gate_sanitizes_maturity_contract_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(specgraph_dir)
            metrics_path = (
                specgraph_dir / "runs" / "idea_maturity_metrics_report.json"
            )
            validation_path = (
                specgraph_dir
                / "runs"
                / "idea_maturity_metrics_validation_report.json"
            )
            metrics_report = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics_report["contract"]["schema_ref"] = "/private/tmp/schema.json"
            metrics_report["contract"]["validation_report_schema_ref"] = (
                "../schemas/idea_maturity_metrics_validation_report.schema.json"
            )
            metrics_report["contract"]["compatibility_policy_ref"] = (
                "VALIDATOR_CONTRACT.md#compatibility-policy\nleak"
            )
            metrics_report["contract"]["metrics_rfc_ref"] = (
                "https://example.invalid/IDEA_MATURITY_METRICS.md"
            )
            metrics_path.write_text(json.dumps(metrics_report), encoding="utf-8")
            validation_report = json.loads(
                validation_path.read_text(encoding="utf-8")
            )
            validation_report["validator"]["schema_ref"] = (
                "file:///private/tmp/schema.json"
            )
            validation_report["validator"]["script_ref"] = (
                "/Users/operator/Metrics/scripts/metrics.py"
            )
            validation_report["validator"]["compatibility_policy_ref"] = (
                "../VALIDATOR_CONTRACT.md#compatibility-policy"
            )
            validation_path.write_text(
                json.dumps(validation_report),
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["idea_maturity"]["trusted"])
            contract = payload["idea_maturity"]["contract"]
            self.assertTrue(contract["available"])
            self.assertEqual(
                contract["report"]["validator_id"],
                "metrics.idea_maturity_metrics.validator.v0.1",
            )
            self.assertEqual(contract["report"]["compatibility_policy"], "additive_v1")
            self.assertNotIn("schema_ref", contract["report"])
            self.assertNotIn("validation_report_schema_ref", contract["report"])
            self.assertNotIn("compatibility_policy_ref", contract["report"])
            self.assertNotIn("metrics_rfc_ref", contract["report"])
            self.assertEqual(
                contract["validator"]["id"],
                "metrics.idea_maturity_metrics.validator.v0.1",
            )
            self.assertEqual(contract["validator"]["version"], "0.1.0")
            self.assertNotIn("schema_ref", contract["validator"])
            self.assertNotIn("script_ref", contract["validator"])
            self.assertNotIn("compatibility_policy_ref", contract["validator"])

    def test_product_candidate_approval_gate_bounds_maturity_explainers_after_filtering(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(specgraph_dir)
            metrics_path = specgraph_dir / "runs" / "idea_maturity_metrics_report.json"
            metrics_report = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics_report["readiness_explainers"] = [
                None,
                {"kind": "missing_id"},
                *[
                    {
                        "id": f"readiness-explainer.pre-sib-{index}",
                        "kind": "pre_sib_finding",
                        "source": "repaired_pre_sib",
                        "severity": "high",
                        "blocks": ["candidate_approval"],
                        "next_action": f"Inspect Pre-SIB finding {index}.",
                    }
                    for index in range(10)
                ],
            ]
            metrics_path.write_text(json.dumps(metrics_report), encoding="utf-8")

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["idea_maturity"]["readiness_explainer_count"],
                10,
            )
            self.assertEqual(
                payload["idea_maturity"]["readiness_explainer_omitted_count"],
                2,
            )
            self.assertEqual(len(payload["idea_maturity"]["readiness_explainers"]), 8)
            self.assertEqual(
                payload["idea_maturity"]["readiness_explainers"][0]["id"],
                "readiness-explainer.pre-sib-0",
            )

    def test_product_candidate_approval_gate_keeps_invalid_maturity_report_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(
                specgraph_dir,
                validation_status="invalid",
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["ready_to_materialize"])
            self.assertEqual(payload["idea_maturity"]["status"], "validation_failed")
            self.assertFalse(payload["idea_maturity"]["trusted"])
            codes = {
                diagnostic["code"]
                for diagnostic in payload["idea_maturity"]["diagnostics"]
            }
            self.assertIn("idea_maturity_validation_not_ok", codes)
            self.assertEqual(payload["diagnostics"], [])

    def test_product_candidate_approval_gate_keeps_write_capable_maturity_untrusted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(
                specgraph_dir,
                authority_expanded=True,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["ready_to_materialize"])
            self.assertEqual(payload["idea_maturity"]["status"], "available")
            self.assertFalse(payload["idea_maturity"]["trusted"])
            codes = {
                diagnostic["code"]
                for diagnostic in payload["idea_maturity"]["diagnostics"]
            }
            self.assertIn("idea_maturity_authority_expanded", codes)
            self.assertEqual(payload["diagnostics"], [])

    def test_product_candidate_approval_gate_requires_maturity_privacy_boundary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(
                specgraph_dir,
                include_privacy_boundary=False,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["idea_maturity"]["trusted"])
            codes = {
                diagnostic["code"]
                for diagnostic in payload["idea_maturity"]["diagnostics"]
            }
            self.assertIn("idea_maturity_privacy_boundary_missing", codes)
            self.assertEqual(payload["diagnostics"], [])

    def test_product_candidate_approval_gate_handles_maturity_validation_without_reports(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            self.write_idea_maturity_artifacts(specgraph_dir)
            validation_path = (
                specgraph_dir / "runs" / "idea_maturity_metrics_validation_report.json"
            )
            validation_report = json.loads(validation_path.read_text(encoding="utf-8"))
            validation_report.pop("reports")
            validation_path.write_text(
                json.dumps(validation_report),
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["idea_maturity"]["status"], "validation_failed")
            self.assertFalse(payload["idea_maturity"]["trusted"])
            codes = {
                diagnostic["code"]
                for diagnostic in payload["idea_maturity"]["diagnostics"]
            }
            self.assertIn("idea_maturity_validation_not_ok", codes)
            self.assertEqual(payload["diagnostics"], [])

    def test_product_candidate_approval_materialize_writes_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            gate_report = specgraph_dir / "runs" / "candidate_approval_gate.json"
            decision_path = specgraph_dir / "runs" / "candidate_approval_decision.json"
            gate_result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--output",
                str(gate_report),
                "--format",
                "json",
            )
            self.assertEqual(gate_result.returncode, 0, gate_result.stderr)

            result = self.run_cli(
                "product-candidate-approval",
                "materialize",
                "--gate-report",
                str(gate_report),
                "--output",
                str(decision_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(decision_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(payload["artifact_kind"], "candidate_approval_decision")
            self.assertEqual(
                payload["contract_ref"],
                "specgraph.idea-to-spec.candidate-approval-decision.v0.1",
            )
            self.assertEqual(payload["decision"]["state"], "approved")
            self.assertTrue(payload["readiness"]["ready"])
            self.assertEqual(payload["candidate"]["candidate_id"], "idea-alpha")
            self.assertEqual(
                payload["promotion_request"]["paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertFalse(
                payload["authority_boundary"]["may_create_branch_or_commit"]
            )
            self.assertFalse(payload["authority_boundary"]["may_open_pull_request"])
            self.assertFalse(
                payload["authority_boundary"]["may_execute_git_service_operation"]
            )

    def test_product_candidate_approval_approve_materializes_decision_and_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            gate_path = specgraph_dir / "runs" / "candidate_approval_gate.json"
            decision_path = specgraph_dir / "runs" / "candidate_approval_decision.json"
            report_path = (
                specgraph_dir
                / "runs"
                / "platform_candidate_approval_execution_report.json"
            )

            result = self.run_cli(
                "product-candidate-approval",
                "approve",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--gate-output",
                str(gate_path),
                "--decision-output",
                str(decision_path),
                "--output",
                str(report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertTrue(gate_path.is_file())
            self.assertEqual(
                payload["artifact_kind"],
                "platform_candidate_approval_execution_report",
            )
            self.assertEqual(payload["status"], "candidate_approval_materialized")
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["dry_run"])
            self.assertEqual(payload["candidate_id"], "idea-alpha")
            self.assertEqual(payload["workspace_id"], "idea-alpha")
            self.assertEqual(
                payload["candidate_approval_decision_ref"],
                str(decision_path.resolve()),
            )
            self.assertEqual(decision["artifact_kind"], "candidate_approval_decision")
            self.assertTrue(
                payload["output_artifacts"]["candidate_approval_decision"]["present"]
            )
            self.assertTrue(
                payload["output_artifacts"]["candidate_approval_decision"]["ready"]
            )
            self.assertEqual(
                {
                    operation["name"]: operation["status"]
                    for operation in payload["operations"]
                },
                {
                    "build_candidate_approval_gate": "ready",
                    "materialize_candidate_approval_decision": "succeeded",
                },
            )
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])
            self.assertFalse(payload["authority_boundary"]["mutates_canonical_specs"])

    def test_product_candidate_approval_approve_dry_run_does_not_write_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            gate_path = specgraph_dir / "runs" / "candidate_approval_gate.json"
            decision_path = specgraph_dir / "runs" / "candidate_approval_decision.json"
            report_path = (
                specgraph_dir
                / "runs"
                / "platform_candidate_approval_execution_report.json"
            )

            result = self.run_cli(
                "product-candidate-approval",
                "approve",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--gate-output",
                str(gate_path),
                "--decision-output",
                str(decision_path),
                "--output",
                str(report_path),
                "--dry-run",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "candidate_approval_dry_run_ready")
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dry_run"])
            self.assertFalse(gate_path.exists())
            self.assertFalse(decision_path.exists())
            self.assertTrue(report_path.is_file())
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(
                statuses["materialize_candidate_approval_decision"],
                "skipped_dry_run",
            )

    def test_product_candidate_approval_approve_resolves_relative_gate_output_under_specgraph(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            relative_gate = f"runs/{Path(tmp_dir).name}_relative_gate.json"
            gate_path = specgraph_dir / relative_gate
            caller_relative_gate_path = REPO_ROOT / relative_gate
            decision_path = specgraph_dir / "runs" / "candidate_approval_decision.json"
            report_path = (
                specgraph_dir
                / "runs"
                / "platform_candidate_approval_execution_report.json"
            )

            result = self.run_cli(
                "product-candidate-approval",
                "approve",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--gate-output",
                relative_gate,
                "--decision-output",
                str(decision_path),
                "--output",
                str(report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            self.assertTrue(gate_path.is_file())
            self.assertFalse(caller_relative_gate_path.exists())
            self.assertEqual(payload["gate_report_ref"], str(gate_path.resolve()))
            self.assertEqual(
                decision["source_artifacts"]["candidate_approval_gate"],
                str(gate_path.resolve()),
            )

    def test_product_candidate_approval_approve_rejects_blocked_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                repair_session_ready_for_candidate_approval=False,
            )
            gate_path = specgraph_dir / "runs" / "candidate_approval_gate.json"
            decision_path = specgraph_dir / "runs" / "candidate_approval_decision.json"
            report_path = (
                specgraph_dir
                / "runs"
                / "platform_candidate_approval_execution_report.json"
            )

            result = self.run_cli(
                "product-candidate-approval",
                "approve",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--gate-output",
                str(gate_path),
                "--decision-output",
                str(decision_path),
                "--output",
                str(report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "candidate_approval_blocked")
            self.assertTrue(gate_path.is_file())
            self.assertFalse(decision_path.exists())
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn(
                "product_candidate_approval_repair_session_not_ready_for_candidate_approval",
                codes,
            )

    def test_product_candidate_approval_gate_rejects_authority_expansion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                intent_authority_expanded="true",
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_approval_intent_authority_expanded", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_rejects_promotion_gate_non_boolean_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                promotion_gate_authority_value=1,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_approval_promotion_gate_authority_expanded",
            codes,
        )
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_rejects_unready_repair_session(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                repair_session_ready_for_candidate_approval=False,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_approval_repair_session_not_ready_for_candidate_approval",
            codes,
        )
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_requires_publication_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                publication_dry_run=True,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_approval_publication_report_dry_run", codes)
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_requires_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_approval_paths_missing", codes)
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_rejects_disallowed_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "README.md",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_approval_path_not_allowed", codes)
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_honors_overridden_input_refs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                intent_repair_session_ref="inputs/idea_to_spec_repair_session.json",
                intent_promotion_gate_ref="inputs/idea_to_spec_promotion_gate.json",
            )
            inputs_dir = specgraph_dir / "inputs"
            inputs_dir.mkdir()
            for filename in (
                "idea_to_spec_repair_session.json",
                "idea_to_spec_promotion_gate.json",
            ):
                (inputs_dir / filename).write_text(
                    (specgraph_dir / "runs" / filename).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--repair-session",
                "inputs/idea_to_spec_repair_session.json",
                "--promotion-gate",
                "inputs/idea_to_spec_promotion_gate.json",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ready_to_materialize"])
        self.assertEqual(
            payload["selected_intent"]["repair_session_ref"],
            "inputs/idea_to_spec_repair_session.json",
        )
        self.assertEqual(
            payload["selected_intent"]["promotion_gate_ref"],
            "inputs/idea_to_spec_promotion_gate.json",
        )

    def test_product_candidate_approval_gate_accepts_repaired_handoff_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                intent_repair_session_ref=(
                    "runs/repaired_idea_to_spec_repair_session.json"
                ),
                intent_promotion_gate_ref=(
                    "runs/repaired_idea_to_spec_promotion_gate.json"
                ),
                include_repaired_handoff=True,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--active-candidate",
                "runs/repaired_active_idea_to_spec_candidate.json",
                "--repair-session",
                "runs/repaired_idea_to_spec_repair_session.json",
                "--promotion-gate",
                "runs/repaired_idea_to_spec_promotion_gate.json",
                "--repaired-handoff",
                "runs/repaired_candidate_promotion_handoff_report.json",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
                cwd=specgraph_dir,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ready_to_materialize"])
        self.assertEqual(payload["summary"]["candidate_id"], "idea-alpha")
        source_keys = {item["key"] for item in payload["source_artifacts"]}
        self.assertIn("active_idea_to_spec_candidate", source_keys)
        self.assertIn("repaired_candidate_promotion_handoff_report", source_keys)
        operations = {item["name"]: item for item in payload["operations"]}
        self.assertEqual(
            operations["validate_repaired_candidate_handoff"]["status"],
            "ready",
        )
        self.assertEqual(
            payload["source_refs"]["repair_session"],
            "runs/repaired_idea_to_spec_repair_session.json",
        )
        self.assertEqual(
            payload["source_refs"]["promotion_gate"],
            "runs/repaired_idea_to_spec_promotion_gate.json",
        )
        self.assertEqual(
            payload["source_refs"]["active_candidate"],
            "runs/repaired_active_idea_to_spec_candidate.json",
        )
        self.assertEqual(
            payload["source_refs"]["repaired_handoff"],
            "runs/repaired_candidate_promotion_handoff_report.json",
        )

    def test_product_candidate_approval_gate_accepts_isolated_repaired_input_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                intent_repair_session_ref=(
                    "runs/repaired_idea_to_spec_repair_session.json"
                ),
                intent_promotion_gate_ref=(
                    "runs/repaired_idea_to_spec_promotion_gate.json"
                ),
                include_repaired_handoff=True,
            )
            isolated_dir = specgraph_dir / "runs" / "ui-started-smoke"
            isolated_dir.mkdir()
            for filename in (
                "repaired_active_idea_to_spec_candidate.json",
                "repaired_idea_to_spec_repair_session.json",
                "repaired_idea_to_spec_promotion_gate.json",
                "repaired_candidate_promotion_handoff_report.json",
            ):
                shutil.copyfile(
                    specgraph_dir / "runs" / filename,
                    isolated_dir / filename,
                )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--active-candidate",
                str(isolated_dir / "repaired_active_idea_to_spec_candidate.json"),
                "--repair-session",
                str(isolated_dir / "repaired_idea_to_spec_repair_session.json"),
                "--promotion-gate",
                str(isolated_dir / "repaired_idea_to_spec_promotion_gate.json"),
                "--repaired-handoff",
                str(isolated_dir / "repaired_candidate_promotion_handoff_report.json"),
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
                cwd=specgraph_dir,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_rejects_stale_repaired_handoff_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                intent_repair_session_ref=(
                    "runs/repaired_idea_to_spec_repair_session.json"
                ),
                intent_promotion_gate_ref=(
                    "runs/repaired_idea_to_spec_promotion_gate.json"
                ),
                include_repaired_handoff=True,
                repaired_handoff_stale_ref=True,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--active-candidate",
                "runs/repaired_active_idea_to_spec_candidate.json",
                "--repair-session",
                "runs/repaired_idea_to_spec_repair_session.json",
                "--promotion-gate",
                "runs/repaired_idea_to_spec_promotion_gate.json",
                "--repaired-handoff",
                "runs/repaired_candidate_promotion_handoff_report.json",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
                cwd=specgraph_dir,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_approval_repaired_handoff_ref_stale",
            codes,
        )
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_rejects_stale_handoff_repair_session_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                intent_repair_session_ref=(
                    "runs/repaired_idea_to_spec_repair_session.json"
                ),
                intent_promotion_gate_ref=(
                    "runs/repaired_idea_to_spec_promotion_gate.json"
                ),
                include_repaired_handoff=True,
                repaired_handoff_stale_repair_session_ref=True,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--active-candidate",
                "runs/repaired_active_idea_to_spec_candidate.json",
                "--repair-session",
                "runs/repaired_idea_to_spec_repair_session.json",
                "--promotion-gate",
                "runs/repaired_idea_to_spec_promotion_gate.json",
                "--repaired-handoff",
                "runs/repaired_candidate_promotion_handoff_report.json",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_approval_repaired_handoff_ref_stale",
            codes,
        )
        subjects = {diagnostic["subject"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            (
                "repaired_handoff.output_artifacts."
                "repaired_repair_session.source_ref"
            ),
            subjects,
        )
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_rejects_invalid_handoff_gap_count(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                intent_repair_session_ref=(
                    "runs/repaired_idea_to_spec_repair_session.json"
                ),
                intent_promotion_gate_ref=(
                    "runs/repaired_idea_to_spec_promotion_gate.json"
                ),
                include_repaired_handoff=True,
            )
            handoff_path = (
                specgraph_dir / "runs" / "repaired_candidate_promotion_handoff_report.json"
            )
            handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff["summary"]["unresolved_candidate_gap_count"] = "0"
            handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--active-candidate",
                "runs/repaired_active_idea_to_spec_candidate.json",
                "--repair-session",
                "runs/repaired_idea_to_spec_repair_session.json",
                "--promotion-gate",
                "runs/repaired_idea_to_spec_promotion_gate.json",
                "--repaired-handoff",
                "runs/repaired_candidate_promotion_handoff_report.json",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_approval_repaired_handoff_gap_count_invalid",
            codes,
        )
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_materialize_rejects_blocked_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            gate_report = Path(tmp_dir) / "blocked_gate.json"
            gate_report.write_text(
                json.dumps(
                    {
                        "artifact_kind": (
                            "platform_candidate_approval_intent_gate_report"
                        ),
                        "schema_version": 1,
                        "ok": False,
                        "ready_to_materialize": False,
                        "canonical_mutations_allowed": False,
                        "ontology_writes_allowed": False,
                        "tracked_artifacts_written": False,
                        "approved_paths": [],
                        "authority_boundary": {
                            "executes_git_commands": "true",
                            "opens_pull_requests": False,
                            "writes_ontology_packages": False,
                            "mutates_canonical_specs": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-candidate-approval",
                "materialize",
                "--gate-report",
                str(gate_report),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = set(payload["readiness"]["blocked_by"])
        self.assertIn("product_candidate_approval_gate_report_not_ok", codes)
        self.assertIn("product_candidate_approval_gate_not_ready", codes)
        self.assertIn("product_candidate_approval_gate_authority_expanded", codes)

    def test_product_candidate_promotion_request_uses_approval_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(tmp_root)
            output = tmp_root / "graph_repository_promotion_request.json"

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_promotion_request",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["candidate_id"], "idea-alpha")
            self.assertEqual(payload["workflow_lane"], "product_idea_to_spec")
            self.assertEqual(payload["target_repository_role"], "product_spec_workspace")
            self.assertEqual(payload["authority_profile"], "workspace_owner_controlled")
            self.assertEqual(
                payload["commit_paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertEqual(payload["candidate_branch"], "graph-candidate/idea-alpha")
            self.assertEqual(
                payload["requested_operations"],
                ["prepare_branch", "create_commit", "open_review"],
            )
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["creates_commits"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])

    def test_product_candidate_promotion_request_dry_run_does_not_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(tmp_root)
            output = tmp_root / "graph_repository_promotion_request.json"

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--output",
                str(output),
                "--dry-run",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["local_files_written"], [])
            self.assertFalse(output.exists())

    def test_product_candidate_promotion_request_rejects_blocked_plan(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(
                tmp_root,
                repair_ready=False,
                context_required_count=1,
            )
            approval_decision = self.write_candidate_approval_decision(tmp_root)

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_plan_not_ready", codes)
        self.assertIn("graph_repository_prepare_branch_not_ready", codes)
        self.assertNotIn("git_service_candidate_approval_paths_mismatch", codes)
        self.assertFalse(payload["ok"])

    def test_product_candidate_promotion_request_rejects_cross_run_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root / "plan-b")
            approval_decision = self.write_candidate_approval_decision(tmp_root / "plan-a")

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_promotion_source_plan_mismatch", codes)
        self.assertFalse(payload["ok"])

    def test_product_candidate_promotion_request_rejects_unapproved_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                decision_state="needs_context",
                ready=False,
            )

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_promotion_approval_not_approved", codes)
        self.assertIn("product_candidate_promotion_approval_not_ready", codes)
        self.assertIn("git_service_candidate_approval_not_approved", codes)
        self.assertFalse(payload["ok"])

    def test_product_candidate_promotion_request_rejects_unsupported_path_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                paths=["README.md"],
            )

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_promotion_path_not_allowed", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["commit_paths"], [])

    def test_product_candidate_promotion_request_rejects_truthy_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(tmp_root)
            payload = json.loads(approval_decision.read_text(encoding="utf-8"))
            payload["authority_boundary"]["may_open_pull_request"] = "true"
            approval_decision.write_text(json.dumps(payload), encoding="utf-8")

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_promotion_approval_authority_expanded",
            codes,
        )
        self.assertFalse(payload["ok"])

    def test_product_candidate_promotion_execute_dry_run_plans_git_service(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request, approval_decision = (
                self.build_product_candidate_promotion_request(tmp_root)
            )
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"
            output = tmp_root / "product_candidate_promotion_execution_report.json"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--dry-run",
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_candidate_promotion_execution_report",
            )
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["status"], "dry_run")
            self.assertFalse(workspace_dir.exists())
            self.assertFalse(payload["summary"]["worktree_prepared"])
            self.assertEqual(payload["summary"]["worktree_prepare_status"], "dry_run")
            self.assertTrue(payload["summary"]["worktree_prepare_planned"])
            self.assertTrue(payload["summary"]["worktree_prepare_dry_run"])
            self.assertFalse(payload["summary"]["physical_worktree_created"])
            self.assertTrue(payload["git_review"]["worktree_prepare_planned"])
            self.assertTrue(payload["git_review"]["worktree_prepare_dry_run"])
            self.assertFalse(payload["git_review"]["physical_worktree_created"])
            self.assertTrue(output.is_file())
            git_service_output = tmp_root / "git_service_promotion_execution_report.json"
            self.assertTrue(git_service_output.is_file())
            self.assertTrue(payload["git_service_execution"]["ok"])
            self.assertIsNone(payload["git_review"]["commit_sha"])
            self.assertIsNone(payload["git_review"]["review_url"])
            self.assertFalse(payload["git_review"]["review_opened"])
            self.assertEqual(payload["git_review"]["copied_file_count"], 0)
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["git_service_execution"]["operations"]
            }
            self.assertEqual(statuses["prepare_worktree"], "dry_run")
            self.assertEqual(statuses["commit_candidate"], "skipped_dry_run")
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])

    def test_product_candidate_promotion_execute_defaults_repaired_source_dir(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                paths=[
                    "runs/repaired_materialized_candidate_specs/IDEA-ALPHA.yaml",
                ],
            )
            promotion_request = tmp_root / "graph_repository_promotion_request.json"
            request_result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--output",
                str(promotion_request),
                "--format",
                "json",
            )
            self.assertEqual(request_result.returncode, 0, request_result.stderr)
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--dry-run",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["diagnostics"])
            expected_source_dir = tmp_root.resolve()
            self.assertEqual(
                payload["materialized_source_dir"],
                str(expected_source_dir),
            )
            self.assertIn(
                str(expected_source_dir),
                payload["git_service_command"],
            )

    def test_product_candidate_promotion_execute_copies_repaired_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                paths=[
                    "runs/repaired_materialized_candidate_specs/IDEA-ALPHA.yaml",
                ],
            )
            promotion_request = tmp_root / "graph_repository_promotion_request.json"
            request_result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--output",
                str(promotion_request),
                "--format",
                "json",
            )
            self.assertEqual(request_result.returncode, 0, request_result.stderr)
            repaired_spec_path = (
                tmp_root
                / "runs"
                / "repaired_materialized_candidate_specs"
                / "IDEA-ALPHA.yaml"
            )
            repaired_spec_path.parent.mkdir(parents=True, exist_ok=True)
            repaired_spec_path.write_text(
                "id: IDEA-ALPHA\nsummary: Repaired candidate spec\n",
                encoding="utf-8",
            )
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--open-review-dry-run",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertEqual(payload["summary"]["status"], "completed")
            self.assertEqual(payload["git_review"]["copied_file_count"], 1)
            self.assertTrue(
                (
                    workspace_dir
                    / "runs"
                    / "repaired_materialized_candidate_specs"
                    / "IDEA-ALPHA.yaml"
                ).is_file()
            )

    def test_product_candidate_promotion_execute_resolves_relative_child_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request, approval_decision = (
                self.build_product_candidate_promotion_request(tmp_root)
            )
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"
            operator_cwd = tmp_root / "operator"
            operator_cwd.mkdir()

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                os.path.relpath(promotion_request, operator_cwd),
                "--approval-decision",
                os.path.relpath(approval_decision, operator_cwd),
                "--repository-dir",
                os.path.relpath(repository_dir, operator_cwd),
                "--workspace-dir",
                os.path.relpath(workspace_dir, operator_cwd),
                "--dry-run",
                "--format",
                "json",
                cwd=operator_cwd,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload["diagnostics"])
        self.assertTrue(payload["git_service_execution"]["ok"])
        self.assertFalse(workspace_dir.exists())

    def test_product_candidate_promotion_execute_runs_controlled_local_adapter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request, approval_decision = (
                self.build_product_candidate_promotion_request(tmp_root)
            )
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            materialized_source = tmp_root / "materialized"
            spec_path = materialized_source / "specs" / "nodes" / "SG-SPEC-CANDIDATE.yaml"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text(
                "id: SG-SPEC-CANDIDATE\nsummary: Candidate spec\n",
                encoding="utf-8",
            )
            workspace_dir = tmp_root / "candidate-worktree"
            output = tmp_root / "product_candidate_promotion_execution_report.json"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--materialized-source-dir",
                str(materialized_source),
                "--open-review-dry-run",
                "--repo",
                "0al-spec/SpecGraph",
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertFalse(payload["dry_run"])
            self.assertTrue(payload["open_review_dry_run"])
            self.assertTrue(payload["authority_boundary"]["controlled_git_service_execution"])
            self.assertTrue(
                payload["authority_boundary"]["creates_candidate_worktree_or_branch"]
            )
            self.assertTrue(payload["authority_boundary"]["creates_candidate_commit"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])
            self.assertTrue(payload["child_report_refs"]["prepare_worktree"])
            self.assertTrue(payload["child_report_refs"]["commit_candidate"])
            self.assertIsNone(payload["child_report_refs"]["open_review"])
            self.assertTrue(payload["git_review"]["commit_sha"])
            self.assertIsNone(payload["git_review"]["review_url"])
            self.assertFalse(payload["git_review"]["review_opened"])
            self.assertTrue(payload["git_review"]["open_review_dry_run"])
            self.assertEqual(payload["git_review"]["copied_file_count"], 1)
            self.assertIsNone(payload["git_review"]["open_review_report_ref"])
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["git_service_execution"]["operations"]
            }
            self.assertEqual(statuses["prepare_worktree"], "succeeded")
            self.assertEqual(statuses["commit_candidate"], "succeeded")
            self.assertEqual(statuses["open_review"], "dry_run")
            self.assertTrue(output.is_file())
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "git_service_promotion_execution_report.json"
                ).is_file()
            )
            self.assertTrue((workspace_dir / "specs/nodes/SG-SPEC-CANDIDATE.yaml").is_file())
            subject = self.run_git(
                workspace_dir,
                "log",
                "-1",
                "--pretty=%s",
            ).stdout.strip()
            self.assertEqual(subject, "Promote Idea Alpha candidate spec graph")

    def test_product_candidate_promotion_execute_rejects_truthy_request_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request, approval_decision = (
                self.build_product_candidate_promotion_request(tmp_root)
            )
            request_payload = json.loads(promotion_request.read_text(encoding="utf-8"))
            request_payload["authority_boundary"]["opens_pull_requests"] = "true"
            promotion_request.write_text(
                json.dumps(request_payload),
                encoding="utf-8",
            )
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_promotion_request_authority_expanded",
            codes,
        )
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["git_service_command_result"])

    def test_product_candidate_promotion_execute_rejects_cross_run_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(
                tmp_root / "plan-b"
            )
            approval_decision = self.write_candidate_approval_decision(tmp_root / "plan-a")
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_promotion_source_plan_mismatch", codes)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["git_service_command_result"])

    def test_product_candidate_promotion_review_status_marks_merged_review(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            execution_report, workspace_dir, _open_review_report = (
                self.write_product_candidate_promotion_execution_report(tmp_root)
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            output = tmp_root / "product_candidate_promotion_review_status_report.json"

            result = self.run_cli(
                "product-candidate-promotion",
                "review-status",
                "--execution-report",
                str(execution_report),
                "--gh-bin",
                str(fake_gh),
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_candidate_promotion_review_status_report",
            )
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertEqual(payload["review_state"], "merged")
            self.assertTrue(payload["summary"]["review_merged"])
            self.assertEqual(
                payload["summary"]["status"],
                "ready_for_read_model_publication",
            )
            self.assertFalse(payload["authority_boundary"]["publishes_read_models"])
            self.assertFalse(payload["authority_boundary"]["merges_pull_requests"])
            self.assertTrue(output.is_file())
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_review_status_report.json"
                ).is_file()
            )

    def test_product_candidate_promotion_review_status_rejects_dry_run_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            execution_report, _workspace_dir, _open_review_report = (
                self.write_product_candidate_promotion_execution_report(
                    tmp_root,
                    dry_run=True,
                )
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )

            result = self.run_cli(
                "product-candidate-promotion",
                "review-status",
                "--execution-report",
                str(execution_report),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_promotion_execution_dry_run", codes)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["graph_repository_command_result"])
        self.assertIsNone(payload["graph_repository_review_status_report_ref"])

    def test_product_candidate_promotion_review_status_resolves_relative_open_review_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            execution_report, _workspace_dir, open_review_report = (
                self.write_product_candidate_promotion_execution_report(tmp_root)
            )
            payload = json.loads(execution_report.read_text(encoding="utf-8"))
            payload["git_service_execution"]["report_refs"]["open_review"] = (
                os.path.relpath(open_review_report, execution_report.parent)
            )
            execution_report.write_text(json.dumps(payload), encoding="utf-8")
            operator_cwd = tmp_root / "operator"
            operator_cwd.mkdir()
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )

            result = self.run_cli(
                "product-candidate-promotion",
                "review-status",
                "--execution-report",
                str(execution_report),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
                cwd=operator_cwd,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload["diagnostics"])
        self.assertEqual(payload["review_state"], "merged")

    def test_product_candidate_promotion_publish_read_model_copies_bundle(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            execution_report, _workspace_dir, _open_review_report = (
                self.write_product_candidate_promotion_execution_report(tmp_root)
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            status_output = (
                tmp_root / "product_candidate_promotion_review_status_report.json"
            )
            status_result = self.run_cli(
                "product-candidate-promotion",
                "review-status",
                "--execution-report",
                str(execution_report),
                "--gh-bin",
                str(fake_gh),
                "--output",
                str(status_output),
                "--format",
                "json",
            )
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"
            publish_output = (
                tmp_root
                / "product_candidate_promotion_read_model_publication_report.json"
            )

            result = self.run_cli(
                "product-candidate-promotion",
                "publish-read-model",
                "--review-status-report",
                str(status_output),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--output",
                str(publish_output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_candidate_promotion_read_model_publication_report",
            )
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertEqual(payload["summary"]["status"], "published")
            self.assertTrue(payload["summary"]["read_model_published"])
            self.assertTrue(payload["authority_boundary"]["publishes_read_models"])
            self.assertFalse(payload["authority_boundary"]["merges_pull_requests"])
            self.assertFalse(payload["authority_boundary"]["ontology_package_write"])
            self.assertTrue((output_dir / "artifact_manifest.json").is_file())
            self.assertTrue(
                (output_dir / "runs" / "candidate_spec_graph.json").is_file()
            )
            self.assertTrue(publish_output.is_file())
            self.assertTrue(
                (
                    output_dir
                    / ".platform"
                    / "graph_repository_publish_read_model_report.json"
                ).is_file()
            )

    def test_product_candidate_promotion_publish_read_model_rejects_unmerged_review(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            execution_report, _workspace_dir, _open_review_report = (
                self.write_product_candidate_promotion_execution_report(tmp_root)
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "OPEN",
                    "isDraft": False,
                    "mergedAt": None,
                    "mergeCommit": None,
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            status_output = (
                tmp_root / "product_candidate_promotion_review_status_report.json"
            )
            status_result = self.run_cli(
                "product-candidate-promotion",
                "review-status",
                "--execution-report",
                str(execution_report),
                "--gh-bin",
                str(fake_gh),
                "--output",
                str(status_output),
                "--format",
                "json",
            )
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "product-candidate-promotion",
                "publish-read-model",
                "--review-status-report",
                str(status_output),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_promotion_review_not_merged", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["summary"]["read_model_published"])
        self.assertIsNone(payload["graph_repository_publish_read_model_report_ref"])
        self.assertFalse(output_dir.exists())

    def test_product_candidate_promotion_publish_read_model_rejects_non_product_lane(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            execution_report, _workspace_dir, _open_review_report = (
                self.write_product_candidate_promotion_execution_report(tmp_root)
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            status_output = (
                tmp_root / "product_candidate_promotion_review_status_report.json"
            )
            status_result = self.run_cli(
                "product-candidate-promotion",
                "review-status",
                "--execution-report",
                str(execution_report),
                "--gh-bin",
                str(fake_gh),
                "--output",
                str(status_output),
                "--format",
                "json",
            )
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            status_payload = json.loads(status_output.read_text(encoding="utf-8"))
            status_payload["workflow_lane"] = "specgraph_bootstrap"
            status_output.write_text(json.dumps(status_payload), encoding="utf-8")
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "product-candidate-promotion",
                "publish-read-model",
                "--review-status-report",
                str(status_output),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_promotion_review_status_workflow_mismatch",
            codes,
        )
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["graph_repository_publish_read_model_report_ref"])
        self.assertFalse(output_dir.exists())

    def test_graph_repository_prepare_local_writes_workspace_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            workspace_dir = tmp_root / "candidate-workspace"

            result = self.run_cli(
                "graph-repository",
                "prepare-local",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_local_prepare_report",
            )
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["dry_run"])
            self.assertEqual(payload["candidate_branch"], "graph-candidate/idea-alpha")
            self.assertEqual(payload["git_commands_executed"], [])
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertTrue(
                (workspace_dir / "candidate_workspace_manifest.json").is_file()
            )
            self.assertTrue(
                (workspace_dir / "graph_repository_local_prepare_report.json").is_file()
            )
            manifest = json.loads(
                (workspace_dir / "candidate_workspace_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["artifact_kind"],
                "platform_graph_repository_candidate_workspace_manifest",
            )
            self.assertFalse(
                manifest["authority_boundary"]["canonical_specs_mutated"]
            )
            self.assertFalse(
                manifest["authority_boundary"]["ontology_packages_written"]
            )

    def test_graph_repository_prepare_local_rejects_invalid_branch_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            workspace_dir = tmp_root / "candidate-workspace"

            result = self.run_cli(
                "graph-repository",
                "prepare-local",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea..alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_candidate_branch_invalid", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["local_files_written"], [])
        self.assertFalse(workspace_dir.exists())

    def test_graph_repository_prepare_local_rejects_not_ready_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(
                tmp_root,
                repair_ready=False,
                context_required_count=1,
            )
            workspace_dir = tmp_root / "candidate-workspace"

            result = self.run_cli(
                "graph-repository",
                "prepare-local",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_plan_not_ready", codes)
        self.assertIn("graph_repository_prepare_branch_not_ready", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["local_files_written"], [])
        self.assertFalse(workspace_dir.exists())

    def test_graph_repository_promotion_request_writes_review_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            output = tmp_root / "graph_repository_promotion_request.json"

            result = self.run_cli(
                "graph-repository",
                "promotion-request",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--title",
                "Add candidate spec graph",
                "--body",
                "Review materialized candidate graph from the idea-to-spec flow.",
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_promotion_request",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["workflow_lane"], "product_idea_to_spec")
            self.assertEqual(
                payload["deployment_profile_id"],
                "product_idea_to_spec_workbench",
            )
            self.assertEqual(payload["target_repository_role"], "product_spec_workspace")
            self.assertEqual(payload["authority_profile"], "workspace_owner_controlled")
            self.assertEqual(payload["candidate_branch"], "graph-candidate/idea-alpha")
            self.assertEqual(
                payload["commit_paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertEqual(
                payload["requested_operations"],
                ["prepare_branch", "create_commit", "open_review"],
            )
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertEqual(payload["write_actions_executed"], [])
            self.assertEqual(payload["git_commands_executed"], [])
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["creates_commits"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])
            self.assertEqual(payload["summary"]["commit_path_count"], 1)
            self.assertTrue(payload["summary"]["promotion_ready"])

    def test_graph_repository_promotion_request_rejects_unsafe_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            output = tmp_root / "graph_repository_promotion_request.json"

            result = self.run_cli(
                "graph-repository",
                "promotion-request",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--path",
                "../outside.yaml",
                "--title",
                "Add candidate spec graph",
                "--body",
                "Review materialized candidate graph.",
                "--output",
                str(output),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_commit_path_outside_worktree", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["commit_paths"], [])
        self.assertFalse(output.exists())

    def test_graph_repository_promotion_request_rejects_unsupported_path_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)

            result = self.run_cli(
                "graph-repository",
                "promotion-request",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--path",
                "README.md",
                "--title",
                "Add candidate spec graph",
                "--body",
                "Review materialized candidate graph.",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_promotion_path_not_allowed", codes)
        self.assertFalse(payload["ok"])

    def test_graph_repository_promotion_request_rejects_not_ready_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(
                tmp_root,
                repair_ready=False,
                context_required_count=1,
            )

            result = self.run_cli(
                "graph-repository",
                "promotion-request",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--title",
                "Add candidate spec graph",
                "--body",
                "Review materialized candidate graph.",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_plan_not_ready", codes)
        self.assertIn("graph_repository_prepare_branch_not_ready", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["commit_paths"], [])

    def test_graph_repository_prepare_worktree_creates_git_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "graph-repository",
                "prepare-worktree",
                "--plan",
                str(plan_path),
                "--repository-dir",
                str(repository_dir),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_worktree_prepare_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["candidate_branch"], "graph-candidate/idea-alpha")
            self.assertEqual(len(payload["git_commands_executed"]), 2)
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertEqual(payload["commits_created"], [])
            self.assertEqual(payload["merges_performed"], [])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertTrue((workspace_dir / ".git").exists())
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_worktree_prepare_report.json"
                ).is_file()
            )
            branch = self.run_git(
                workspace_dir,
                "rev-parse",
                "--abbrev-ref",
                "HEAD",
            ).stdout.strip()
            self.assertEqual(branch, "graph-candidate/idea-alpha")

    def test_graph_repository_prepare_worktree_resolves_relative_workspace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "relative-candidate-worktree"
            relative_workspace = Path(os.path.relpath(workspace_dir, REPO_ROOT))

            result = self.run_cli(
                "graph-repository",
                "prepare-worktree",
                "--plan",
                str(plan_path),
                "--repository-dir",
                str(repository_dir),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(relative_workspace),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["workspace_dir"], str(workspace_dir.resolve()))
            self.assertEqual(
                payload["git_commands_executed"][1]["command"][5],
                str(workspace_dir.resolve()),
            )
            self.assertTrue((workspace_dir / ".git").exists())
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_worktree_prepare_report.json"
                ).is_file()
            )

    def test_graph_repository_prepare_worktree_rejects_missing_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "graph-repository",
                "prepare-worktree",
                "--plan",
                str(plan_path),
                "--repository-dir",
                str(tmp_root / "missing-repository"),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_repository_missing", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(workspace_dir.exists())

    def test_graph_repository_commit_worktree_creates_candidate_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir = self.prepare_graph_repository_worktree(tmp_root)
            spec_path = workspace_dir / "specs" / "nodes" / "SG-SPEC-CANDIDATE.yaml"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text(
                "id: SG-SPEC-CANDIDATE\nsummary: Candidate spec\n",
                encoding="utf-8",
            )
            prepare_report = (
                workspace_dir
                / ".platform"
                / "graph_repository_worktree_prepare_report.json"
            )

            result = self.run_cli(
                "graph-repository",
                "commit-worktree",
                "--prepare-report",
                str(prepare_report),
                "--worktree-dir",
                str(workspace_dir),
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--message",
                "Add candidate spec",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_review_commit_report",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["candidate_tracked_artifacts_written"])
            self.assertFalse(payload["canonical_tracked_artifacts_written"])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertEqual(payload["merges_performed"], [])
            self.assertEqual(
                payload["committed_paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertIsInstance(payload["commit_sha"], str)
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_review_commit_report.json"
                ).is_file()
            )
            subject = self.run_git(
                workspace_dir,
                "log",
                "--format=%s",
                "-1",
            ).stdout.strip()
            self.assertEqual(subject, "Add candidate spec")

    def test_graph_repository_commit_worktree_force_adds_explicit_ignored_candidate_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir = self.prepare_graph_repository_worktree(tmp_root)
            (workspace_dir / ".gitignore").write_text("runs/\n", encoding="utf-8")
            ignored_path = (
                workspace_dir
                / "runs"
                / "repaired_materialized_candidate_specs"
                / "CANDIDATE-CANDIDATE-SPEC-PRODUCT-BOUNDARY.yaml"
            )
            ignored_path.parent.mkdir(parents=True)
            ignored_path.write_text(
                "id: CANDIDATE-CANDIDATE-SPEC-PRODUCT-BOUNDARY\n",
                encoding="utf-8",
            )
            check_ignore = self.run_git(
                workspace_dir,
                "check-ignore",
                "runs/repaired_materialized_candidate_specs/CANDIDATE-CANDIDATE-SPEC-PRODUCT-BOUNDARY.yaml",
            )
            self.assertEqual(check_ignore.returncode, 0, check_ignore.stderr)
            prepare_report = (
                workspace_dir
                / ".platform"
                / "graph_repository_worktree_prepare_report.json"
            )

            result = self.run_cli(
                "graph-repository",
                "commit-worktree",
                "--prepare-report",
                str(prepare_report),
                "--worktree-dir",
                str(workspace_dir),
                "--path",
                "runs/repaired_materialized_candidate_specs/CANDIDATE-CANDIDATE-SPEC-PRODUCT-BOUNDARY.yaml",
                "--message",
                "Add ignored candidate spec",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["candidate_tracked_artifacts_written"])
            self.assertEqual(
                payload["committed_paths"],
                [
                    "runs/repaired_materialized_candidate_specs/CANDIDATE-CANDIDATE-SPEC-PRODUCT-BOUNDARY.yaml"
                ],
            )
            add_command = payload["git_commands_executed"][0]["command"]
            self.assertIn("-f", add_command)
            committed_files = self.run_git(
                workspace_dir,
                "show",
                "--name-only",
                "--format=",
                "HEAD",
            ).stdout.splitlines()
            self.assertIn(
                "runs/repaired_materialized_candidate_specs/CANDIDATE-CANDIDATE-SPEC-PRODUCT-BOUNDARY.yaml",
                committed_files,
            )

    def test_graph_repository_commit_worktree_rejects_directory_pathspec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir = self.prepare_graph_repository_worktree(tmp_root)
            candidate_dir = workspace_dir / "runs" / "repaired_materialized_candidate_specs"
            candidate_dir.mkdir(parents=True)
            (candidate_dir / "CANDIDATE-CANDIDATE-SPEC-PRODUCT-BOUNDARY.yaml").write_text(
                "id: CANDIDATE-CANDIDATE-SPEC-PRODUCT-BOUNDARY\n",
                encoding="utf-8",
            )
            prepare_report = (
                workspace_dir
                / ".platform"
                / "graph_repository_worktree_prepare_report.json"
            )

            result = self.run_cli(
                "graph-repository",
                "commit-worktree",
                "--prepare-report",
                str(prepare_report),
                "--worktree-dir",
                str(workspace_dir),
                "--path",
                "runs/repaired_materialized_candidate_specs",
                "--message",
                "Add ignored candidate specs",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1, result.stdout)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("graph_repository_commit_path_not_file", codes)
            self.assertEqual(payload["git_commands_executed"], [])

    def test_graph_repository_commit_worktree_rejects_outside_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir = self.prepare_graph_repository_worktree(tmp_root)
            prepare_report = (
                workspace_dir
                / ".platform"
                / "graph_repository_worktree_prepare_report.json"
            )

            result = self.run_cli(
                "graph-repository",
                "commit-worktree",
                "--prepare-report",
                str(prepare_report),
                "--worktree-dir",
                str(workspace_dir),
                "--path",
                "../outside.yaml",
                "--message",
                "Attempt outside path",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_commit_path_outside_worktree", codes)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["commit_sha"])

    def test_graph_repository_open_review_pushes_branch_and_invokes_gh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, commit_report = self.commit_graph_repository_candidate(
                tmp_root
            )
            fake_gh = self.write_fake_gh(tmp_root)

            result = self.run_cli(
                "graph-repository",
                "open-review",
                "--commit-report",
                str(commit_report),
                "--worktree-dir",
                str(workspace_dir),
                "--base",
                "main",
                "--title",
                "Add candidate spec",
                "--body",
                "Review candidate spec graph.",
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_open_review_report",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["candidate_branch_pushed"])
            self.assertEqual(
                payload["review_url"],
                "https://github.com/example/repo/pull/123",
            )
            self.assertEqual(
                payload["pull_requests_opened"],
                ["https://github.com/example/repo/pull/123"],
            )
            self.assertEqual(payload["commits_created"], [])
            self.assertEqual(payload["merges_performed"], [])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["canonical_tracked_artifacts_written"])
            self.assertEqual(len(payload["commands_executed"]), 2)
            self.assertEqual(payload["commands_executed"][1]["cwd"], str(workspace_dir))
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_open_review_report.json"
                ).is_file()
            )
            remote_heads = self.run_git(
                workspace_dir,
                "ls-remote",
                "--heads",
                "origin",
                "graph-candidate/idea-alpha",
            ).stdout
            self.assertIn("refs/heads/graph-candidate/idea-alpha", remote_heads)

    def test_graph_repository_open_review_preserves_push_status_on_gh_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, commit_report = self.commit_graph_repository_candidate(
                tmp_root
            )
            fake_gh = self.write_failing_fake_gh(tmp_root)

            result = self.run_cli(
                "graph-repository",
                "open-review",
                "--commit-report",
                str(commit_report),
                "--worktree-dir",
                str(workspace_dir),
                "--base",
                "main",
                "--title",
                "Add candidate spec",
                "--body",
                "Review candidate spec graph.",
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(payload["candidate_branch_pushed"])
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertIsNone(payload["review_url"])
            self.assertEqual(len(payload["commands_executed"]), 2)
            self.assertEqual(payload["commands_executed"][1]["cwd"], str(workspace_dir))
            remote_heads = self.run_git(
                workspace_dir,
                "ls-remote",
                "--heads",
                "origin",
                "graph-candidate/idea-alpha",
            ).stdout
            self.assertIn("refs/heads/graph-candidate/idea-alpha", remote_heads)

    def test_graph_repository_open_review_rejects_failed_commit_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, commit_report = self.commit_graph_repository_candidate(
                tmp_root
            )
            payload = json.loads(commit_report.read_text(encoding="utf-8"))
            payload["ok"] = False
            commit_report.write_text(json.dumps(payload), encoding="utf-8")
            fake_gh = self.write_fake_gh(tmp_root)

            result = self.run_cli(
                "graph-repository",
                "open-review",
                "--commit-report",
                str(commit_report),
                "--worktree-dir",
                str(workspace_dir),
                "--title",
                "Add candidate spec",
                "--body",
                "Review candidate spec graph.",
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_commit_report_not_ok", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["pull_requests_opened"], [])

    def test_graph_repository_review_status_reads_open_pull_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "OPEN",
                    "isDraft": False,
                    "mergedAt": None,
                    "mergeCommit": None,
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )

            result = self.run_cli(
                "graph-repository",
                "review-status",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_review_status_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["review_state"], "open")
            self.assertEqual(payload["review_decision"], "APPROVED")
            self.assertFalse(payload["summary"]["review_merged"])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["canonical_tracked_artifacts_written"])
            self.assertEqual(payload["merges_performed"], [])
            self.assertEqual(payload["read_models_published"], [])
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_review_status_report.json"
                ).is_file()
            )

    def test_graph_repository_review_status_marks_merged_pull_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )

            result = self.run_cli(
                "graph-repository",
                "review-status",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["review_state"], "merged")
        self.assertTrue(payload["summary"]["review_merged"])
        self.assertEqual(payload["merges_performed"], [])
        self.assertEqual(payload["read_models_published"], [])

    def test_graph_repository_review_status_marks_merged_state_without_timestamp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": None,
                    "mergeCommit": None,
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )

            result = self.run_cli(
                "graph-repository",
                "review-status",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["review_state"], "merged")
        self.assertTrue(payload["summary"]["review_merged"])

    def test_graph_repository_publish_read_model_copies_public_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            _workspace_dir, review_status_report = (
                self.merged_graph_repository_review_status(tmp_root)
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "graph-repository",
                "publish-read-model",
                "--review-status-report",
                str(review_status_report),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_publish_read_model_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["review_state"], "merged")
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["canonical_tracked_artifacts_written"])
            self.assertFalse(payload["ontology_packages_written"])
            self.assertEqual(payload["merges_performed"], [])
            self.assertEqual(
                payload["read_models_published"],
                [str(output_dir / "artifact_manifest.json")],
            )
            self.assertTrue((output_dir / "artifact_manifest.json").is_file())
            self.assertTrue(
                (output_dir / "runs" / "candidate_spec_graph.json").is_file()
            )
            self.assertTrue(
                (
                    output_dir
                    / ".platform"
                    / "graph_repository_publish_read_model_report.json"
                ).is_file()
            )

    def test_graph_repository_publish_read_model_rejects_unmerged_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "OPEN",
                    "isDraft": False,
                    "mergedAt": None,
                    "mergeCommit": None,
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            status_result = self.run_cli(
                "graph-repository",
                "review-status",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            review_status_report = (
                workspace_dir
                / ".platform"
                / "graph_repository_review_status_report.json"
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "graph-repository",
                "publish-read-model",
                "--review-status-report",
                str(review_status_report),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_review_not_merged", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["read_models_published"], [])
        self.assertFalse(output_dir.exists())

    def test_graph_repository_publish_read_model_rejects_escaped_manifest_name(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            _workspace_dir, review_status_report = (
                self.merged_graph_repository_review_status(tmp_root)
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            external_manifest = tmp_root / "external_manifest.json"
            external_manifest.write_text(
                json.dumps({"artifact_kind": "external_manifest"}),
                encoding="utf-8",
            )

            for index, manifest_name in enumerate(
                ["../external_manifest.json", str(external_manifest)]
            ):
                with self.subTest(manifest_name=manifest_name):
                    output_dir = tmp_root / f"published-read-model-{index}"
                    result = self.run_cli(
                        "graph-repository",
                        "publish-read-model",
                        "--review-status-report",
                        str(review_status_report),
                        "--bundle-dir",
                        str(bundle_dir),
                        "--output-dir",
                        str(output_dir),
                        "--manifest-name",
                        manifest_name,
                        "--format",
                        "json",
                    )

                    self.assertEqual(result.returncode, 1)
                    payload = json.loads(result.stdout)
                    codes = {
                        diagnostic["code"] for diagnostic in payload["diagnostics"]
                    }
                    self.assertIn(
                        "graph_repository_read_model_manifest_name_invalid",
                        codes,
                    )
                    self.assertFalse(payload["ok"])
                    self.assertEqual(payload["read_models_published"], [])
                    self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
