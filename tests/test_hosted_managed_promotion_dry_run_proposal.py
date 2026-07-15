from __future__ import annotations

from pathlib import Path
import unittest

from scripts import hosted_managed_operations as operations


class HostedManagedPromotionDryRunProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
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
            "conditionally suitable, not approved for production enablement",
            normalized,
        )
        self.assertIn(
            "proceed to an implementation PR, not enable production",
            normalized,
        )
        self.assertIn("does not authorize a continuous worker", normalized)
        self.assertIn("no branch, commit, or pull request was created", normalized)


if __name__ == "__main__":
    unittest.main()
