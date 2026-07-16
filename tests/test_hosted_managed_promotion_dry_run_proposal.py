from __future__ import annotations

from pathlib import Path
import unittest

from scripts import hosted_managed_operations as operations


class HostedManagedPromotionDryRunProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.root = root
        self.proposal = (
            root / "docs" / "hosted-managed-promotion-dry-run-rollout-proposal.md"
        ).read_text(encoding="utf-8")

    def test_proposal_matches_registered_dry_run_contract(self) -> None:
        definition = operations.operation_by_id("promotion_execute_dry_run")
        self.assertIsNotNone(definition)
        assert definition is not None

        self.assertTrue(definition.dry_run_only)
        self.assertFalse(definition.irreversible)
        self.assertEqual(definition.side_effect_class, "git_dry_run")
        self.assertEqual(definition.replay_policy, "same_request_dry_run_only")
        self.assertEqual(definition.timeout_seconds, 120)

        for token in (
            *definition.platform_command,
            *definition.input_refs,
            *definition.output_reports,
            definition.side_effect_class,
            definition.replay_policy,
        ):
            self.assertIn(f"`{token}`", self.proposal)

    def test_proposal_does_not_claim_rollout_authority(self) -> None:
        normalized = " ".join(self.proposal.split())
        self.assertIn(
            "clean-VM and production rollout evidence pending",
            normalized,
        )
        self.assertIn(
            "proceed to local and clean-VM validation, not enable production yet",
            normalized,
        )
        self.assertIn("does not authorize a continuous worker", normalized)
        self.assertIn("no branch, commit, or pull request was created", normalized)

    def test_implemented_profile_remains_one_shot_and_operation_specific(self) -> None:
        policy = (
            self.root
            / "deploy"
            / "hosted-managed"
            / "promotion-dry-run-worker-window-policy.json"
        ).read_text(encoding="utf-8")
        compose = (
            self.root / "docker-compose.hosted-managed-production.example.yml"
        ).read_text(encoding="utf-8")

        self.assertIn('"promotion_execute_dry_run"', policy)
        self.assertNotIn("review_status_execute", policy)
        self.assertIn("promotion-dry-run-window", compose)
        self.assertIn("restart: \"no\"", compose)
        self.assertIn(
            "promotion-dry-run-worker-window-policy.json",
            compose,
        )

    def test_hosted_runtime_includes_promotion_wrapper_dependencies(self) -> None:
        requirements = (self.root / "requirements-hosted.txt").read_text(
            encoding="utf-8"
        )
        workflow = (
            self.root / ".github" / "workflows" / "deploy-bundle.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("jsonschema>=", requirements)
        self.assertIn("psycopg[binary]>=", requirements)
        self.assertIn("import jsonschema, psycopg", workflow)


if __name__ == "__main__":
    unittest.main()
