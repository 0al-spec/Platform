from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import hosted_managed_promotion_review as contract


WORKSPACE_ID = "pantry-control"
OPERATOR_REF = "operator://specspace-basic/session-a"
DRY_RUN_FRAGMENT = "0123456789abcdef01234567"
CONFIRMATION_FRAGMENT = "0123456789abcdef0123456789abcdef"
CONFIRMATION_REF = (
    "specspace-state://confirmations/pantry-control/promotion_review_execute/"
    f"{CONFIRMATION_FRAGMENT}.json"
)


def write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def product_report() -> dict:
    return {
        "artifact_kind": "platform_product_candidate_promotion_execution_report",
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


def git_service_report() -> dict:
    return {
        "artifact_kind": "platform_git_service_promotion_execution_report",
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


class PromotionReviewConfirmationContractTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[dict, dict[str, str], dict[str, Path]]:
        input_digests = {
            contract.PROMOTION_REQUEST_REF: "1" * 64,
            contract.APPROVAL_DECISION_REF: "2" * 64,
            contract.EXECUTION_PLAN_REF: "3" * 64,
        }
        execution_ref = (
            "runs/managed-promotion-dry-runs/"
            f"{DRY_RUN_FRAGMENT}.product_candidate_promotion_execution_report.json"
        )
        git_ref = (
            "runs/managed-promotion-dry-runs/"
            f"{DRY_RUN_FRAGMENT}.git_service_promotion_execution_report.json"
        )
        paths = {
            execution_ref: root / "execution.json",
            git_ref: root / "git-service.json",
        }
        execution_digest = write_json(paths[execution_ref], product_report())
        git_digest = write_json(paths[git_ref], git_service_report())
        payload = {
            "artifact_kind": contract.CONFIRMATION_KIND,
            "schema_version": 1,
            "contract_ref": contract.CONFIRMATION_CONTRACT_REF,
            "confirmation_id": (
                "confirmation://pantry-control/promotion_review_execute/"
                "0123456789abcdef0123456789abcdef"
            ),
            "workspace_id": WORKSPACE_ID,
            "operation_id": contract.CONFIRMATION_OPERATION_ID,
            "operator_ref": OPERATOR_REF,
            "status": "ready",
            "confirmed": True,
            "issued_at": "2026-08-01T10:00:00Z",
            "expires_at": "2026-08-01T10:15:00Z",
            "workspace_binding": {
                "binding_id": "product-workspace-binding://pantry-control",
                "binding_revision_sha256": "4" * 64,
                "source_sha256": "5" * 64,
            },
            "inputs": {
                name: {
                    "logical_ref": ref,
                    "sha256": input_digests[ref],
                }
                for name, ref in contract.BOUND_INPUT_REFS.items()
            },
            "predecessor_dry_run": {
                "request_id": (
                    "managed-operation://pantry-control/"
                    f"promotion_execute_dry_run/{DRY_RUN_FRAGMENT}"
                ),
                "execution_report": {
                    "logical_ref": execution_ref,
                    "sha256": execution_digest,
                },
                "git_service_report": {
                    "logical_ref": git_ref,
                    "sha256": git_digest,
                },
            },
            "authority_boundary": dict(contract.AUTHORITY_BOUNDARY),
        }
        return payload, input_digests, paths

    def diagnostics(self, payload: dict, digests: dict, paths: dict) -> list[str]:
        return contract.confirmation_diagnostics(
            payload,
            expected_workspace_id=WORKSPACE_ID,
            expected_operator_ref=OPERATOR_REF,
            expected_confirmation_ref=CONFIRMATION_REF,
            expected_binding={
                "binding_id": "product-workspace-binding://pantry-control",
                "binding_revision_sha256": "4" * 64,
                "source_sha256": "5" * 64,
            },
            expected_input_digests=digests,
            now_iso="2026-08-01T10:05:00Z",
            resolve_ref=lambda ref: paths[ref],
        )

    def test_current_confirmation_and_dry_run_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload, digests, paths = self.fixture(Path(temp_dir))
            diagnostics = self.diagnostics(payload, digests, paths)

        self.assertEqual(diagnostics, [])

    def test_expired_confirmation_and_changed_input_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload, digests, paths = self.fixture(Path(temp_dir))
            payload["expires_at"] = "2026-08-01T10:04:59Z"
            payload["inputs"]["execution_plan"]["sha256"] = "6" * 64
            diagnostics = self.diagnostics(payload, digests, paths)

        self.assertTrue(any("expired" in item for item in diagnostics))
        self.assertIn("confirmation inputs.execution_plan digest changed", diagnostics)

    def test_confirmation_state_ref_must_match_confirmation_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload, digests, paths = self.fixture(Path(temp_dir))
            diagnostics = contract.confirmation_diagnostics(
                payload,
                expected_workspace_id=WORKSPACE_ID,
                expected_operator_ref=OPERATOR_REF,
                expected_confirmation_ref=(
                    "specspace-state://confirmations/pantry-control/"
                    "promotion_review_execute/ffffffffffffffffffffffffffffffff.json"
                ),
                expected_binding={
                    "binding_id": "product-workspace-binding://pantry-control",
                    "binding_revision_sha256": "4" * 64,
                    "source_sha256": "5" * 64,
                },
                expected_input_digests=digests,
                now_iso="2026-08-01T10:05:00Z",
                resolve_ref=lambda ref: paths[ref],
            )

        self.assertIn(
            "promotion review confirmation state ref does not match its identity",
            diagnostics,
        )

    def test_dry_run_that_records_git_write_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload, digests, paths = self.fixture(Path(temp_dir))
            git_ref = payload["predecessor_dry_run"]["git_service_report"][
                "logical_ref"
            ]
            report = git_service_report()
            report["operations"][1]["status"] = "succeeded"
            payload["predecessor_dry_run"]["git_service_report"]["sha256"] = (
                write_json(paths[git_ref], report)
            )
            diagnostics = self.diagnostics(payload, digests, paths)

        self.assertIn(
            "predecessor Git Service report records a write operation",
            diagnostics,
        )

    def test_dry_run_with_unknown_authority_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload, digests, paths = self.fixture(Path(temp_dir))
            execution_ref = payload["predecessor_dry_run"]["execution_report"][
                "logical_ref"
            ]
            report = product_report()
            report["authority_boundary"]["may_force_push"] = True
            payload["predecessor_dry_run"]["execution_report"]["sha256"] = (
                write_json(paths[execution_ref], report)
            )
            diagnostics = self.diagnostics(payload, digests, paths)

        self.assertIn(
            "predecessor product report authority boundary does not match "
            "the dry-run contract",
            diagnostics,
        )


if __name__ == "__main__":
    unittest.main()
