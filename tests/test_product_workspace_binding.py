from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import platform


def _specgraph_binding_evidence(workspace_id: str) -> dict:
    evidence = {
        "contract_ref": "specgraph.product-workspace.binding-evidence.v0.1",
        "proposal_id": "0211",
        "status": "ready",
        "identity": {
            "workspace_id": workspace_id,
            "display_name": "Pantry Rotation",
            "governance_profile": "product_workspace",
            "repository_role": "product_spec_workspace",
        },
        "layout": {
            "root_reference": "workspace_relative",
            "project_config_ref": "specgraph.project.yaml",
            "specs_root_ref": "specs",
            "proposals_root_ref": "docs/proposals",
            "runs_root_ref": "runs",
            "supervisor_state_root_ref": ".specgraph",
        },
        "project_config": {
            "source_ref": "specgraph.project.yaml",
            "source_sha256": "3" * 64,
        },
        "repository": {
            "repository_role": "product_spec_workspace",
            "workspace_identity": workspace_id,
            "worktree_identity": f"product-workspace/{workspace_id}",
            "creates_worktree": False,
        },
        "privacy_boundary": {
            "workspace_relative_refs_only": True,
            "local_input_path_persisted": False,
            "raw_root_intent_published": False,
        },
        "authority_boundary": {
            "report_only": True,
            "may_execute_platform": False,
            "may_mutate_canonical_specs": False,
            "may_write_ontology_packages": False,
            "may_accept_ontology_terms": False,
            "may_create_git_commit": False,
            "may_open_pull_request": False,
        },
    }
    evidence["evidence_sha256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return evidence


class ProductWorkspaceBindingTests(unittest.TestCase):
    def test_ready_platform_binding_is_versioned_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binding = platform.product_workspace_initialization_binding(
                workspace_id="pantry-rotation",
                display_name="Pantry Rotation",
                route="/pantry-rotation",
                workspace_root=Path(tmp) / "PantryRotation",
                governance_profile="product_workspace",
                artifact_base_url="https://specgraph.tech",
                status="ready",
                plan_ref="runs/pantry-rotation/plan.json",
                plan_sha256="1" * 64,
                specgraph_initialization_report_ref=(
                    "runs/pantry-rotation/product_workspace_initialization.json"
                ),
                specgraph_initialization_report_sha256="2" * 64,
            )

        self.assertEqual(
            binding["binding_id"],
            "product-workspace-binding://pantry-rotation",
        )
        self.assertEqual(
            binding["execution"]["platform_default_run_dir_ref"],
            "runs/pantry-rotation",
        )
        self.assertEqual(
            binding["routing"]["specspace_state_namespace_ref"],
            "specspace-state://workspace/pantry-rotation",
        )
        self.assertEqual(
            platform.product_workspace_binding_diagnostics(
                binding,
                expected_workspace_id="pantry-rotation",
                require_ready=True,
            ),
            [],
        )

    def test_platform_binding_rejects_tampered_logical_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binding = platform.product_workspace_initialization_binding(
                workspace_id="pantry-rotation",
                display_name="Pantry Rotation",
                route="/pantry-rotation",
                workspace_root=Path(tmp) / "PantryRotation",
                governance_profile="product_workspace",
            )
        tampered = copy.deepcopy(binding)
        tampered["routing"]["specspace_state_namespace_ref"] = (
            "specspace-state://workspace/foreign"
        )
        tampered["routing"]["product_artifact_manifest_url"] = (
            "https://attacker.invalid/manifest.json"
        )

        codes = {
            diagnostic.code
            for diagnostic in platform.product_workspace_binding_diagnostics(
                tampered,
                expected_workspace_id="pantry-rotation",
            )
        }

        self.assertIn("product_workspace_binding_state_namespace_mismatch", codes)
        self.assertIn(
            "product_workspace_binding_artifact_manifest_url_mismatch",
            codes,
        )
        self.assertIn("product_workspace_binding_revision_mismatch", codes)

    def test_specgraph_binding_evidence_is_digest_checked(self) -> None:
        report = {
            "workspace_binding_evidence": _specgraph_binding_evidence(
                "pantry-rotation"
            )
        }

        self.assertEqual(
            platform.specgraph_workspace_binding_evidence_diagnostics(
                report,
                expected_workspace_id="pantry-rotation",
            ),
            [],
        )

        report["workspace_binding_evidence"]["layout"]["runs_root_ref"] = (
            "runs/foreign"
        )
        codes = {
            diagnostic.code
            for diagnostic in platform.specgraph_workspace_binding_evidence_diagnostics(
                report,
                expected_workspace_id="pantry-rotation",
            )
        }
        self.assertIn("product_workspace_binding_specgraph_layout_mismatch", codes)
        self.assertIn(
            "product_workspace_binding_specgraph_evidence_digest_mismatch",
            codes,
        )

    def test_approval_decision_keeps_workspace_binding_identity(self) -> None:
        binding_context = {
            "contract_ref": "platform.product-workspace.binding.v1",
            "binding_id": "product-workspace-binding://pantry-workspace",
            "binding_revision_sha256": "4" * 64,
            "status": "ready",
            "source_ref": "runs/pantry-workspace/initialization.json",
            "source_sha256": "5" * 64,
            "workspace_id": "pantry-workspace",
            "display_name": "Pantry Workspace",
            "route": "/pantry-workspace",
            "repository_role": "product_spec_workspace",
            "specspace_state_namespace_ref": (
                "specspace-state://workspace/pantry-workspace"
            ),
            "platform_default_run_dir_ref": "runs/pantry-workspace",
            "product_artifact_bundle_ref": (
                "dist/specgraph-public/workspaces/pantry-workspace"
            ),
            "product_artifact_manifest_ref": (
                "dist/specgraph-public/workspaces/pantry-workspace/manifest.json"
            ),
            "repository": {
                "workspace_identity": "pantry-workspace",
                "worktree_identity": "product-workspace/pantry-workspace",
                "creates_worktree": False,
            },
            "provenance": {
                "plan_sha256": "1" * 64,
                "specgraph_initialization_report_sha256": "2" * 64,
            },
            "authority_boundary": {
                "report_only": True,
                "may_execute_platform": False,
                "may_execute_specgraph": False,
                "may_create_git_commit": False,
                "may_open_pull_request": False,
                "may_publish_read_model": False,
            },
        }
        gate_report = {
            "workspace_binding": binding_context,
            "selected_intent": {
                "id": "approval-intent-1",
                "workspace_id": "pantry-workspace",
                "candidate_id": "pantry-candidate-v2",
                "requested_by": "operator",
            },
            "summary": {
                "workspace_id": "pantry-workspace",
                "candidate_id": "pantry-candidate-v2",
            },
            "source_refs": {},
            "approved_paths": ["runs/materialized_candidate_specs/pantry.yaml"],
        }

        decision = platform.build_candidate_approval_decision(
            gate_report_path=Path("runs/pantry-workspace/approval-gate.json"),
            gate_report=gate_report,
        )

        self.assertEqual(decision["workspace_binding"], binding_context)
        self.assertEqual(
            decision["workspace"]["workspace_id"],
            "pantry-workspace",
        )
        self.assertEqual(
            decision["candidate"]["candidate_id"],
            "pantry-candidate-v2",
        )
        codes = {
            diagnostic.code
            for diagnostic in platform.product_candidate_promotion_decision_diagnostics(
                decision
            )
        }
        self.assertNotIn("managed_workspace_binding_workspace_mismatch", codes)
        request = platform.build_graph_repository_promotion_request_payload(
            plan_path=Path("runs/pantry-workspace/graph-plan.json"),
            plan={"source_artifacts": []},
            contract={},
            workspace_id="pantry-workspace",
            candidate_id="pantry-candidate-v2",
            paths=["runs/materialized_candidate_specs/pantry.yaml"],
            title="Promote pantry candidate",
            body="Review the candidate.",
            base="main",
            workflow_lane="product_idea_to_spec",
            deployment_profile_id="product-idea-to-spec-workbench",
            target_repository_role="product_spec_workspace",
            authority_profile="workspace_owner_controlled",
            output_path=None,
            dry_run=True,
            diagnostics=[],
        )
        request["workspace_binding"] = binding_context
        self.assertEqual(request["workspace_id"], "pantry-workspace")
        request_codes = {
            diagnostic.code
            for diagnostic in platform.product_candidate_promotion_request_execution_diagnostics(
                request
            )
        }
        self.assertNotIn(
            "managed_workspace_binding_workspace_mismatch",
            request_codes,
        )
